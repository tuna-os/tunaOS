#!/usr/bin/env python3
"""Grant runner access without changing other ACL principals' effective rights."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import json
import os
import stat
from pathlib import Path
import re
import subprocess
import sys

_ENTRY = re.compile(r'^(default:)?(user|group|mask|other):([^:]*):([rwx-]{3})$')

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


# libacl operates on held descriptors: no pathname is passed to a privileged
# ACL writer, including during rollback. Default ACLs are never modified.
_LIB = ctypes.CDLL('libacl.so.1', use_errno=True)
for _name, _args, _result in (
    ('acl_get_fd', [ctypes.c_int], ctypes.c_void_p),
    ('acl_to_any_text', [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char, ctypes.c_int], ctypes.c_void_p),
    ('acl_from_text', [ctypes.c_char_p], ctypes.c_void_p),
    ('acl_set_fd', [ctypes.c_int, ctypes.c_void_p], ctypes.c_int),
    ('acl_free', [ctypes.c_void_p], ctypes.c_int),
):
    getattr(_LIB, _name).argtypes = _args
    getattr(_LIB, _name).restype = _result


def read_acl(fd):
    value = _LIB.acl_get_fd(fd)
    if not value:
        raise OSError(ctypes.get_errno(), 'ACL read failed')
    text = None
    try:
        text = _LIB.acl_to_any_text(value, None, b'\n', 0x08)  # TEXT_NUMERIC_IDS, acl/libacl.h
        if not text:
            raise OSError(ctypes.get_errno(), 'ACL encoding failed')
        return ctypes.string_at(text).decode('ascii')
    finally:
        if text:
            _LIB.acl_free(text)
        _LIB.acl_free(value)


def write_acl(fd, text):
    value = _LIB.acl_from_text(text.encode('ascii'))
    if not value:
        raise ValueError('invalid ACL')
    try:
        if _LIB.acl_set_fd(fd, value) != 0:
            raise OSError(ctypes.get_errno(), 'ACL write failed')
    finally:
        _LIB.acl_free(value)


def identity(fd):
    info = os.fstat(fd)
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise ValueError('hardlinked ACL object refused')
    return [info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_uid, info.st_gid]


@contextmanager
def physical(path):
    """Open each component relative to its held parent, refusing all symlinks."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or path == Path('/'):
        raise ValueError('invalid physical root')
    fds = [os.open('/', os.O_RDONLY | os.O_DIRECTORY)]
    try:
        chain = [identity(fds[0])]
        for index, part in enumerate(path.parts[1:]):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(path.parts) - 2:
                flags |= os.O_DIRECTORY
            fds.append(os.open(part, flags, dir_fd=fds[-1]))
            chain.append(identity(fds[-1]))
        if chain[-1][2] not in (stat.S_IFREG, stat.S_IFDIR):
            raise ValueError('unsupported ACL object')
        yield fds[-1], chain
    finally:
        for fd in reversed(fds):
            os.close(fd)


def snapshot(path, snapshot_path, uid, prefix=None):
    if prefix:
        raise ValueError('descriptor ACL operations require a single privileged helper')
    records = []
    with physical(path) as (root_fd, chain):
        def visit(fd, parts, ancestors):
            info = identity(fd)
            text = read_acl(fd)
            _safe_acl_modifications(text.splitlines(), uid, info[2] == stat.S_IFDIR)
            records.append({'parts': parts, 'chain': ancestors, 'acl': text})
            if info[2] == stat.S_IFDIR:
                for name in sorted(os.listdir(fd)):
                    child = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if stat.S_ISLNK(child.st_mode):
                        continue
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                    child_fd = os.open(name, flags, dir_fd=fd)
                    try:
                        if identity(child_fd)[2] not in (stat.S_IFREG, stat.S_IFDIR):
                            raise ValueError('unsupported ACL object')
                        visit(child_fd, [*parts, name], [*ancestors, identity(child_fd)])
                    finally:
                        os.close(child_fd)
        visit(root_fd, [], chain)
    state = {'version': 1, 'root': str(path), 'records': records}
    # Never clobber a prior recovery record, even after partial failure.
    snapshot_path = Path(snapshot_path)
    with physical(snapshot_path.parent) as (parent_fd, _):
        fd = os.open(snapshot_path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent_fd)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
    return state


def operate(state, uid=None):
    for record in state['records']:
        parts = record['parts']
        if any(not isinstance(p, str) or p in ('', '.', '..') or '/' in p for p in parts):
            raise ValueError('invalid recovery path')
        with physical(Path(state['root']).joinpath(*parts)) as (fd, chain):
            if chain != record['chain']:
                raise ValueError('ACL object or ancestor replaced; recovery retained')
            text = record['acl']
            if uid is not None:
                changes = _safe_acl_modifications(text.splitlines(), uid, chain[-1][2] == stat.S_IFDIR)
                entries = dict((line.rsplit(':', 1)[0], line) for line in text.splitlines() if line)
                entries.update((line.rsplit(':', 1)[0], line) for line in changes)
                text = '\n'.join(entries.values()) + '\n'
            write_acl(fd, text)
            with physical(Path(state['root']).joinpath(*parts)) as (_, after):
                if after != chain:
                    raise ValueError('ACL object or ancestor replaced; recovery retained')


def apply_runner_access(state, uid, prefix=None):
    if prefix:
        raise ValueError('unexpected command prefix')
    operate(state, uid)


def restore(snapshot_path, prefix=None):
    if prefix:
        raise ValueError('unexpected command prefix')
    with physical(snapshot_path) as (fd, _):
        if os.fstat(fd).st_uid != os.geteuid():
            raise ValueError('recovery state owner mismatch')
        with os.fdopen(os.dup(fd)) as stream:
            state = json.load(stream)
    if os.geteuid() == 0:
        validate_host_root(Path(state['root']))
    operate(state)


def grant(path, snapshot_path, uid, prefix=None):
    state = snapshot(path, snapshot_path, uid, prefix)
    try:
        apply_runner_access(state, uid)
    except Exception:
        restore(snapshot_path)
        raise


def validate_host_root(path):
    release = os.uname().release
    if path not in (Path('/boot') / ('vmlinuz-' + release), Path('/usr/lib/modules') / release):
        raise ValueError('not an exact host kernel input')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--sudo', action='store_true',
                        help='run the descriptor-bound helper through sudo')
    subparsers = parser.add_subparsers(dest='action', required=True)
    grant_parser = subparsers.add_parser('grant')
    grant_parser.add_argument('--path', type=Path, required=True)
    grant_parser.add_argument('--snapshot', type=Path, required=True)
    grant_parser.add_argument('--uid', type=int, required=True)
    restore_parser = subparsers.add_parser('restore')
    restore_parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    if args.sudo:
        command = ['sudo', '-n', sys.executable, str(Path(__file__).absolute()),
                   *[value for value in sys.argv[1:] if value != '--sudo']]
        return subprocess.run(command, check=False).returncode
    if os.geteuid() == 0 and args.action == 'grant':
        validate_host_root(args.path)
    if args.action == 'grant':
        grant(args.path, args.snapshot, args.uid)
    else:
        restore(args.snapshot)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f'diagnostic ACL operation refused: {error}', file=sys.stderr)
        raise SystemExit(77) from None
