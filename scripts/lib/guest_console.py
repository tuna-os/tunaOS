"""Authenticated guest commands over the harness-owned QEMU UART socket.

No network SSH, host-key exception, guest file injection or boot-argument edits.
Only bounded responses are retained; raw terminal/password exchanges are not.
"""
import base64
import json
import re
import secrets
import shlex
import socket
import time
import zlib


class Console:
    def __init__(self, path, user, password, timeout=60):
        if not re.fullmatch(r'[a-z][a-z0-9]{0,30}', user):
            raise ValueError('invalid console account')
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(1)
        self.sock.connect(str(path))
        self.password = password
        self.timeout = timeout
        self.sock.sendall(b'\r')
        self.expect(rb'login:\s*$')
        self.sock.sendall(user.encode()+b'\r')
        response = self.expect(rb'(?:Password:\s*$|[$#] ?$)')
        if re.search(rb'Password:\s*$', response):
            self.sock.sendall(password.encode()+b'\r')
            self.expect(rb'[$#] ?$')
        # A prompt alone is not authentication; bind the effective account.
        if self.execute("import getpass,json; print(json.dumps(getpass.getuser()))", sudo=False) != user:
            raise ValueError('console authenticated as wrong account')

    def expect(self, pattern):
        deadline = time.monotonic()+self.timeout
        data = b''
        while time.monotonic() < deadline:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise ValueError('console disconnected')
            data += re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', chunk)
            if len(data) > 1024*1024:
                raise ValueError('console response exceeds bound')
            if b'Login incorrect' in data or b'Authentication failure' in data:
                raise ValueError('console authentication failed')
            if re.search(pattern, data):
                return data
        raise ValueError('console response timed out')

    def execute(self, source, sudo=False):
        nonce = secrets.token_hex(16)
        start, end = 'BEGIN_'+nonce, 'END_'+nonce
        # Tokens exist only in encoded source, so terminal command echo cannot
        # impersonate a successful command result. Errors never emit END.
        wrapped = f"print({start!r},flush=True)\n{source}\nprint({end!r},flush=True)"
        encoded = base64.b64encode(zlib.compress(wrapped.encode())).decode()
        code = f"exec(__import__('zlib').decompress(__import__('base64').b64decode('{encoded}')))"
        prefix = "sudo -S -p 'CANDIDATE_SUDO:' " if sudo else ''
        command = prefix + 'python3 -c ' + shlex.quote(code)
        if len(command) > 3900:
            raise ValueError('console command exceeds canonical line bound')
        self.sock.sendall(command.encode()+b'\r')
        pattern = (rb'CANDIDATE_SUDO:\s*$|' + re.escape(end.encode()) + rb'\r?\n')
        response = self.expect(pattern)
        if re.search(rb'CANDIDATE_SUDO:\s*$', response):
            self.sock.sendall(self.password.encode()+b'\r')
            response = self.expect(re.escape(end.encode())+rb'\r?\n')
        match = re.search(re.escape(start.encode())+rb'\r?\n(.*?)\r?\n'+re.escape(end.encode()), response, re.S)
        if not match:
            raise ValueError('console result frame missing')
        return json.loads(match[1])

    def close(self):
        try:
            self.sock.sendall(b'exit\r')
        finally:
            self.sock.close()
