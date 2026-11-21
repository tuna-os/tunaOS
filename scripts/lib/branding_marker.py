#!/usr/bin/env python3
"""Consume the runtime branding verdict an installed image prints on serial.

Contract (tunaOS runtime branding, `verify-branding --runtime`): each boot
prints, in order,

    TUNAOS_BRANDING_REPORT {one-line compact JSON}
    TUNAOS_BRANDING_OK variant=<v> desktop=<d> checks=<n> skipped=<n>
 or TUNAOS_BRANDING_FAIL variant=<v> desktop=<d> failed=<id>,<id>

The verdict line is authoritative and self-sufficient (it carries the failed
ids). Serial lines arrive with \\r and interleaved kernel/journal output, so a
REPORT that does not parse is recorded as `report_unparsable` and the verdict
still comes from the OK/FAIL line. Images built before the contract print
neither line: that is `absent`, never a pass.

CLI (used by scripts/iso-e2e.sh on strict installed cold/warm boots only):

    branding_marker.py wait --log FILE --deadline EPOCH [--socket SOCK] [--pid PID]
    branding_marker.py summarize --log FILE --out JSON

`wait` exits 0 once a verdict line is in FILE, 3 at the deadline, 4 when the
guest is gone (QEMU pid dead or serial EOF). With --socket it also reads the
guest serial socket and appends only the TUNAOS_BRANDING lines to FILE.
`summarize` writes the evidence JSON and prints one line
`result=<ok|fail|absent> failed=<ids|-> report=<parsed|report_unparsable|absent>`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

REPORT_PREFIX = 'TUNAOS_BRANDING_REPORT '
# The per-desktop sub-check `TUNAOS_BRANDING_GNOME_FAIL` must not match: the
# token after the prefix is exactly OK or FAIL, then whitespace or line end.
VERDICT_RE = re.compile(r'TUNAOS_BRANDING_(OK|FAIL)(?=\s|$)(.*)')
# Check ids are stable dotted names (`os-release.agree`, `desktop.gnome.user`);
# anything else on a serial line is noise and never reaches evidence lines.
CHECK_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
MARKER = 'TUNAOS_BRANDING'


def _failed_ids(value):
    return [item for item in value.split(',') if CHECK_ID_RE.fullmatch(item)]


def _report(line):
    raw = line[line.index(REPORT_PREFIX) + len(REPORT_PREFIX):].strip()
    try:
        value, _ = json.JSONDecoder().raw_decode(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def parse(text):
    """The last verdict in text and the REPORT that belongs to it.

    A REPORT belongs to a verdict when it appears after the previous verdict
    and before this one, so a log holding several boots never pairs one
    boot's verdict with another boot's report."""
    pending = None
    last = None
    for line in text.replace('\r', '').split('\n'):
        if REPORT_PREFIX in line:
            pending = line
        match = VERDICT_RE.search(line)
        if match is None:
            continue
        fields = dict(token.split('=', 1) for token in match.group(2).split() if '=' in token)
        last = (match.group(1).lower(), fields, pending)
        pending = None
    if last is None:
        return {'result': 'absent', 'failed': [], 'report': 'absent', 'document': None}
    result, fields, report_line = last
    failed = _failed_ids(fields.get('failed', '')) if result == 'fail' else []
    document = _report(report_line) if report_line is not None else None
    if report_line is None:
        status = 'absent'
    elif document is None:
        status = 'report_unparsable'
    else:
        status = 'parsed'
        if result == 'fail' and not failed and isinstance(document.get('failed'), list):
            failed = [item for item in document['failed']
                      if isinstance(item, str) and CHECK_ID_RE.fullmatch(item)]
    return {'result': result, 'failed': failed, 'report': status, 'document': document}


def evidence_document(parsed):
    """The file stored as strict-<mode>-<phase>-branding.json: the image's own
    REPORT when it parsed, otherwise what the verdict line alone proves."""
    if parsed['result'] == 'absent':
        return {'result': 'absent'}
    if parsed['report'] == 'parsed':
        return parsed['document']
    report = 'unparsable' if parsed['report'] == 'report_unparsable' else 'absent'
    return {'result': parsed['result'], 'failed': parsed['failed'], 'report': report}


def summary_line(parsed):
    return 'result={} failed={} report={}'.format(
        parsed['result'], ','.join(parsed['failed']) or '-', parsed['report'])


def has_verdict(path):
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace')
    except FileNotFoundError:
        return False
    return parse(text)['result'] != 'absent'


def _alive(pid):
    if pid is None:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait(log, deadline, sock_path=None, pid=None, clock=time.time, sleep=time.sleep):
    """Block until log holds a verdict (0), the deadline passes (3) or the
    guest is gone (4)."""
    conn = None
    buffered = b''
    checked_at = None
    try:
        while True:
            # The file is re-read at most every 2 s (or right after this
            # reader appended to it): a busy serial line must not turn each
            # received chunk into a full read of a multi-megabyte log.
            now = clock()
            if checked_at is None or now - checked_at >= 2:
                if has_verdict(log):
                    return 0
                checked_at = now
            if now >= deadline:
                return 0 if has_verdict(log) else 3
            if not _alive(pid):
                return 4
            if sock_path is None:
                sleep(min(2, max(0, deadline - now)))
                continue
            if conn is None:
                try:
                    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    conn.settimeout(1)
                    conn.connect(sock_path)
                except OSError:
                    conn.close()
                    conn = None
                    sleep(1)
                    continue
            try:
                data = conn.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                return 4
            if not data:
                return 4 if not has_verdict(log) else 0
            buffered += data
            *lines, buffered = buffered.split(b'\n')
            # Only marker lines are kept: this reader runs after the LUKS
            # unlock helper, whose RedactedSerial is the only serial writer
            # allowed to persist arbitrary guest output.
            kept = [line for line in lines if MARKER.encode() in line]
            if kept:
                with open(log, 'ab') as stream:
                    stream.write(b''.join(line.rstrip(b'\r') + b'\n' for line in kept))
                checked_at = None
    finally:
        if conn is not None:
            conn.close()


def summarize(log, out):
    try:
        text = Path(log).read_text(encoding='utf-8', errors='replace')
    except FileNotFoundError:
        text = ''
    parsed = parse(text)
    Path(out).write_text(json.dumps(evidence_document(parsed), indent=2) + '\n')
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    sub = parser.add_subparsers(dest='command', required=True)
    waiting = sub.add_parser('wait')
    waiting.add_argument('--log', required=True)
    waiting.add_argument('--deadline', required=True, type=int)
    waiting.add_argument('--socket')
    waiting.add_argument('--pid', type=int)
    summary = sub.add_parser('summarize')
    summary.add_argument('--log', required=True)
    summary.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.command == 'wait':
        return wait(args.log, args.deadline, args.socket, args.pid)
    print(summary_line(summarize(args.log, args.out)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
