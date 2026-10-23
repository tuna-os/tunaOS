#!/usr/bin/env python3
"""Diagnostic-only, bounded HTTPS CONNECT proxy. Never logs tunnel contents."""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import select
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

ALLOWED = frozenset({
    'ghcr.io', 'pkg-containers.githubusercontent.com',
    'tuf-repo-cdn.sigstore.dev', 'rekor.sigstore.dev', 'fulcio.sigstore.dev',
    'mirror.stream.centos.org',
})
LIMIT = threading.BoundedSemaphore(12)


def authority(value: str) -> str:
    match = re.fullmatch(r'([a-z0-9.-]+):443', value)
    if not match or match[1] not in ALLOWED:
        raise ValueError('host-or-port-not-admitted')
    return match[1]


def public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not address.is_unspecified)


def safe_target(value: str) -> str:
    return value if re.fullmatch(r'[a-z0-9.-]{1,150}:443', value) else '<invalid-authority>'


def addresses(host: str) -> list[tuple]:
    entries = socket.getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
    if not entries or any(not public_address(e[4][0]) for e in entries):
        raise ValueError('non-public-dns-answer')
    return entries


def connect(host: str) -> socket.socket:
    # Connect to the checked address, not a second DNS lookup susceptible to rebinding.
    errors = []
    for family, kind, proto, _, endpoint in addresses(host):
        peer = socket.socket(family, kind, proto)
        peer.settimeout(15)
        try:
            peer.connect(endpoint)
            return peer
        except OSError as error:
            errors.append(type(error).__name__)
            peer.close()
    raise OSError(','.join(errors))


def emit(decision: str, host: str, **details) -> None:
    print(json.dumps({'decision': decision, 'host': host, **details}, sort_keys=True), flush=True)


class Handler(BaseHTTPRequestHandler):
    timeout = 15
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass  # Do not log raw HTTP lines or credentials.

    def reply(self, status: int) -> None:
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def do_GET(self):
        self.reply(405)

    def do_CONNECT(self):
        # Log bounded authority only, never headers/tokens, even on malformed inputs.
        target = safe_target(self.path)
        try:
            host = authority(self.path)
        except ValueError:
            emit('deny', target, reason='host-or-port-not-admitted')
            self.reply(403)
            return
        allowed_headers = {'host', 'user-agent', 'proxy-connection', 'connection'}
        if (len(self.headers) > 16 or sum(len(k) + len(v) for k, v in self.headers.items()) > 8192
                or any(k.lower() not in allowed_headers for k in self.headers)):
            emit('deny', target, reason='unsupported-proxy-headers')
            self.reply(403)
            return
        try:
            with connect(host) as peer:
                emit('allow', host, address=peer.getpeername()[0])
                self.send_response(200, 'Connection established')
                self.send_header('X-Diagnostic-Upstream-IP', peer.getpeername()[0])
                self.end_headers()
                self.wfile.flush()
                self.close_connection = True
                started, transferred = time.monotonic(), 0
                while time.monotonic() - started < 3600:
                    readable, _, _ = select.select([self.connection, peer], [], [], 120)
                    if not readable:
                        break
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            emit('closed', host, bytes=transferred)
                            return
                        (peer if source is self.connection else self.connection).sendall(data)
                        transferred += len(data)
                emit('closed', host, bytes=transferred)
        except (OSError, ValueError) as error:
            emit('error', host, reason=type(error).__name__)
            # A transport failure must not be mistaken for a policy-denied control.
            try:
                self.reply(502)
            except OSError:
                pass


class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 12

    def process_request(self, request, client_address):
        # Admission happens before a thread can block parsing client headers.
        if not LIMIT.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.1 503 Busy\r\nContent-Length: 0\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            LIMIT.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            LIMIT.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--listen', required=True)
    args = parser.parse_args()
    ipaddress.IPv4Address(args.listen)
    with Server((args.listen, 3128), Handler) as server:
        emit('ready', args.listen)
        server.serve_forever()
