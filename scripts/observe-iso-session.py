#!/usr/bin/env python3
"""Read-only guest session observation for candidate desktop contracts.

Run inside the installed guest after an actual user login. This does not log in,
install, mount, or alter the guest. No output receipt is written on failure.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from contracts.iso_qualification import DESKTOPS, validate_session


def run(*args):
    return subprocess.check_output(args, text=True, timeout=15).strip()


def properties(value):
    return dict(line.split('=', 1) for line in value.splitlines() if '=' in line)


def observe(desktop, platform, mode, phase, command=run, proc=Path('/proc')):
    if desktop not in DESKTOPS:
        raise ValueError('headless or unknown desktop cannot satisfy GUI criterion')
    log = command('journalctl', '-b', '-u', 'tunaos-desktop-contract.service', '--no-pager', '-o', 'cat')
    if ('TUNAOS_DESKTOP_CONTRACT_FAIL' in log or not re.search(
            r'^TUNAOS_DESKTOP_CONTRACT_OK desktop=' + re.escape(desktop) + r'\s', log, re.M)):
        raise ValueError('matching desktop contract absent or failed')
    sessions = command('loginctl', 'list-sessions', '--no-legend', '--no-pager')
    candidates = []
    for line in sessions.splitlines():
        sid = line.split()[0]
        if not re.fullmatch(r'[A-Za-z0-9]+', sid):
            raise ValueError('invalid session identifier')
        data = properties(command('loginctl', 'show-session', sid, '--no-pager'))
        if data.get('Active') == 'yes' and data.get('Class') == 'user' and data.get('Remote') == 'no':
            data['SessionId'] = sid
            candidates.append(data)
    if len(candidates) != 1:
        raise ValueError('need exactly one active local user session')
    data = candidates[0]
    uid = int(data['User'])
    process = DESKTOPS[desktop][1]
    # pgrep is scoped to the logged-in user; greeter/system processes cannot pass.
    pids = command('pgrep', '-u', str(uid), '-x', process).splitlines()
    if len(pids) != 1 or not pids[0].isdigit():
        raise ValueError('desktop process absent or ambiguous')
    pid = int(pids[0])
    status = properties((proc / str(pid) / 'status').read_text().replace(':\t', '='))
    process_uid = int(status['Uid'].split()[0])
    if (proc / str(pid) / 'comm').read_text().strip() != process:
        raise ValueError('desktop process changed during observation')
    cgroups = (proc / str(pid) / 'cgroup').read_text().splitlines()
    scope = data.get('Scope')
    matched = [line.split(':', 2)[-1] for line in cgroups
               if scope and scope in line.split(':', 2)[-1].split('/')]
    if not matched:
        raise ValueError('desktop process is outside the selected login session scope')
    status_json = json.loads(command('bootc', 'status', '--json'))
    image = status_json['status']['booted']['image']
    source = image.get('imageDigest') or image.get('digest')
    if not isinstance(source, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', source):
        raise ValueError('booted source digest missing')
    result = dict(desktop=desktop, architecture=command('uname', '-m'), desktop_contract=True,
                  active=True, remote=False, uid=uid, process_uid=process_uid, process_pid=pid,
                  session_desktop=data.get('Desktop'), type=data.get('Type'), process=process,
                  boot_id=(proc / 'sys/kernel/random/boot_id').read_text().strip(),
                  session_id=data['SessionId'], scope=scope, process_cgroup=matched[0],
                  source_digest=source, mode=mode, phase=phase, **{'class': data.get('Class')})
    validate_session(result, desktop, platform)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', required=True, choices=sorted(DESKTOPS))
    parser.add_argument('--platform', required=True, choices=['linux/amd64','linux/amd64/v2','linux/arm64'])
    parser.add_argument('--mode', required=True, choices=['plain','luks'])
    parser.add_argument('--phase', required=True, choices=['cold','warm'])
    args = parser.parse_args()
    try:
        print(json.dumps(observe(args.desktop, args.platform, args.mode, args.phase), sort_keys=True))
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
