#!/usr/bin/env python3
"""Grant runner access without changing other ACL principals' effective rights."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

_ENTRY = re.compile(r'^(default:)?(user|group|mask|other):([^:]*):([rwx-]{3})$')

def run(args: list[str], prefix: list[str] | None = None) -> str:
    result = subprocess.run([*(prefix or []), *args], check=True, text=True, capture_output=True)
    return result.stdout


def acl_blocks(text: str) -> list[tuple[Path, list[str]]]:
    blocks: list[tuple[Path, list[str]]] = []
    current_path: Path | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith('# file: '):
            if current_path is not None:
                blocks.append((current_path, current_lines))
            current_path = Path(line.removeprefix('# file: '))
            current_lines = [line]
        elif current_path is not None:
            current_lines.append(line)
    if current_path is not None:
        blocks.append((current_path, current_lines))
    return blocks


def permission_bits(value: str) -> set[str]:
    return {permission for permission in 'rwx' if permission in value}


def permission_text(value: set[str]) -> str:
    return ''.join(permission if permission in value else '-' for permission in 'rwx')


def _safe_acl_modifications(lines: list[str], uid: int, directory: bool) -> list[str]:
    entries: dict[str, str] = {}
    for line in lines:
        match = _ENTRY.fullmatch(line.split('\t', 1)[0])
        if match and not match.group(1):
            _, kind, qualifier, permissions = match.groups()
            entries[f'{kind}:{qualifier}'] = permissions

    if f'user:{uid}' in entries:
        raise ValueError('runner ACL already exists; refusing to alter an unowned ACL')
    group_permissions = entries.get('group:')
    if group_permissions is None:
        raise ValueError('ACL snapshot lacks a group entry')
    old_mask = permission_bits(entries.get('mask:', group_permissions))
    grant = {'r', 'x'} if directory else {'r'}
    new_mask = old_mask | grant
    modifications = []

    # Preserve every existing group-class entry's effective permissions.
    for key, permissions in entries.items():
        if key == 'user:':
            continue
        if key.startswith('user:') or key.startswith('group:'):
            effective = permission_bits(permissions) & old_mask
            modifications.append(f'{key}:{permission_text(effective)}')
    modifications.append(f'mask::{permission_text(new_mask)}')
    modifications.append(f'user:{uid}:{permission_text(grant)}')
    return modifications


def snapshot(path: Path, snapshot_path: Path, uid: int,
             prefix: list[str] | None = None) -> list[tuple[Path, list[str]]]:
    text = run(['getfacl', '-n', '-R', '-p', '--', str(path)], prefix)
    blocks = acl_blocks(text)
    if not blocks:
        raise ValueError('getfacl returned no paths')
    for _, lines in blocks:
        if any(line.startswith(f'user:{uid}:') for line in lines):
            raise ValueError('runner ACL already exists; refusing to alter an unowned ACL')
    snapshot_path.write_text(text, encoding='utf-8')
    return blocks


def apply_runner_access(blocks: list[tuple[Path, list[str]]], uid: int,
                        prefix: list[str] | None = None) -> None:
    for path, lines in blocks:
        if path.is_symlink():
            continue
        modifications = _safe_acl_modifications(lines, uid, path.is_dir())
        run(['setfacl', '-m', ','.join(modifications), '--', str(path)], prefix)


def restore(snapshot_path: Path, prefix: list[str] | None = None) -> None:
    run(['setfacl', f'--restore={snapshot_path}'], prefix)


def grant(path: Path, snapshot_path: Path, uid: int,
          prefix: list[str] | None = None) -> None:
    blocks = snapshot(path, snapshot_path, uid, prefix)
    try:
        apply_runner_access(blocks, uid, prefix)
    except Exception:
        restore(snapshot_path, prefix)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--sudo', action='store_true',
                        help='run only fixed getfacl/setfacl commands through sudo')
    subparsers = parser.add_subparsers(dest='action', required=True)
    grant_parser = subparsers.add_parser('grant')
    grant_parser.add_argument('--path', type=Path, required=True)
    grant_parser.add_argument('--snapshot', type=Path, required=True)
    grant_parser.add_argument('--uid', type=int, required=True)
    restore_parser = subparsers.add_parser('restore')
    restore_parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    prefix = ['sudo', '-n'] if args.sudo else []
    if args.action == 'grant':
        grant(args.path, args.snapshot, args.uid, prefix)
    else:
        restore(args.snapshot, prefix)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f'diagnostic ACL operation refused: {error}', file=sys.stderr)
        raise SystemExit(77) from None
