#!/usr/bin/env python3
"""Verify the locked QEMU set and its Noble apt dependency plan before install."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'requirements-iso-diagnostic-apt.txt'
EXPECTED_NAMES = {'qemu-system-x86', 'qemu-system-common', 'qemu-system-data', 'qemu-utils'}


def verify(run=subprocess.run):
    packages = LOCK.read_text().splitlines()
    parsed = [item.split('=', 1) for item in packages]
    if (len(parsed) != len(EXPECTED_NAMES) or any(len(item) != 2 for item in parsed)
            or {item[0] for item in parsed} != EXPECTED_NAMES
            or len({item[1] for item in parsed}) != 1):
        raise ValueError('QEMU package lock is not the reviewed four-package set')
    version = parsed[0][1]
    for package in packages:
        result = run(['apt-cache', 'show', package], capture_output=True, text=True, check=False)
        if result.returncode or not result.stdout.strip():
            raise ValueError(f'signed Noble apt metadata does not contain {package}')
    simulation = run(['apt-get', '--simulate', 'install', '--no-install-recommends', *packages],
                     capture_output=True, text=True, check=False)
    if simulation.returncode:
        raise ValueError('signed Noble apt cannot resolve the locked QEMU dependency closure')
    resolved = set()
    for line in simulation.stdout.splitlines():
        match = re.match(r'^Inst (qemu-[^\s]+)(?: \[[^]]+\])? \(([^ )]+)', line)
        if match:
            package, candidate = match.groups()
            if candidate != version:
                raise ValueError(f'Noble apt resolves {package} to {candidate}, not {version}')
            resolved.add(package)
    return {'locked_version': version, 'resolved_qemu_packages': sorted(resolved)}


def main():
    try:
        result = verify()
    except (OSError, ValueError) as error:
        print(f'::error::{error}', file=sys.stderr)
        return 1
    print('verified signed Noble QEMU package plan: ' + ', '.join(result['resolved_qemu_packages']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
