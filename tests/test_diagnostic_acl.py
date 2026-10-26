"""Real filesystem ACL tests for the temporary supermin access grant."""
import importlib.util
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('diagnostic_acl', ROOT / 'scripts/diagnostic-acl.py')
acl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acl)


def get_acl(path, *, effective=False):
    command = ['getfacl', '-n']
    if effective:
        command.append('-e')
    command.extend(['-R', '-p', '--', str(path)])
    return subprocess.run(command, check=True, text=True, capture_output=True).stdout

def acl_entries(block):
    entries = {}
    for line in block.splitlines():
        value = line.split('\t', 1)[0]
        if re.match(r'^(?:user|group|mask|other):', value):
            kind, qualifier, permissions = value.split(':', 2)
            entries[f'{kind}:{qualifier}'] = permissions
    return entries


def permission_bits(value):
    return {permission for permission in 'rwx' if permission in value}


def effective_acl(path):
    blocks = {}
    current = None
    for line in get_acl(path, effective=True).splitlines():
        if line.startswith('# file: '):
            current = line.removeprefix('# file: ')
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line.split('\t#effective:', 1)[0])
    result = {}
    for name, lines in blocks.items():
        entries = acl_entries('\n'.join(lines))
        mask = permission_bits(entries.get('mask:', entries.get('group:', '---')))
        result[name] = {key: permission_bits(value) & mask
                        for key, value in entries.items() if key != 'user:'}
    return result


def make_tree(tmp_path):
    tree = tmp_path/'modules'
    module = tree/'kernel/drivers/gpu/virtio-gpu.ko.xz'
    module.parent.mkdir(parents=True)
    module.write_bytes(b'module')
    (tree/'build').symlink_to('/usr/src')
    uid = os.getuid() + 12001
    other_uid = uid + 1
    for path in (tree, module.parent.parent, module.parent):
        subprocess.run(['setfacl', '-m', f'u::rwx,g::rwx,u:{other_uid}:rwx,m::r--,o::---', '--', str(path)], check=True)
    subprocess.run(['setfacl', '-m', f'u::rw-,g::rwx,u:{other_uid}:rwx,m::r--,o::---', '--', str(module)], check=True)
    return tree, module, uid, other_uid


def assert_access_preserved(before, after, tree, module, uid, other_uid):
    before_tree = str(tree)
    before_module = str(module)
    after_tree = after[before_tree]
    after_module = after[before_module]
    assert after_tree['group:'] == before[before_tree]['group:']
    assert after_tree[f'user:{other_uid}'] == before[before_tree][f'user:{other_uid}']
    assert after_module['group:'] == before[before_module]['group:']
    assert after_module[f'user:{other_uid}'] == before[before_module][f'user:{other_uid}']
    assert after_tree[f'user:{uid}'] == {'r', 'x'}
    assert after_module[f'user:{uid}'] == {'r'}


def test_acl_grant_preserves_effective_access_and_restores_exact_tree(tmp_path):
    tree, module, uid, other_uid = make_tree(tmp_path)
    original = get_acl(tree)
    before = effective_acl(tree)
    snapshot = tmp_path/'modules.acl'

    blocks = acl.snapshot(tree, snapshot, uid)
    acl.apply_runner_access(blocks, uid)
    after = effective_acl(tree)
    assert_access_preserved(before, after, tree, module, uid, other_uid)
    acl.restore(snapshot)
    assert get_acl(tree) == original


def test_acl_grant_failure_restores_exact_tree(tmp_path, monkeypatch):
    tree, _, uid, _ = make_tree(tmp_path)
    original = get_acl(tree)
    snapshot = tmp_path/'modules.acl'
    blocks = acl.snapshot(tree, snapshot, uid)
    run = acl.run
    grants = 0

    def fail_after_one_real_grant(args, prefix=None):
        nonlocal grants
        if args[0] == 'setfacl' and '-m' in args:
            grants += 1
            if grants == 2:
                raise subprocess.CalledProcessError(1, args, stderr='injected grant failure')
        return run(args, prefix)

    monkeypatch.setattr(acl, 'run', fail_after_one_real_grant)
    with pytest.raises(subprocess.CalledProcessError):
        acl.grant(tree, snapshot, uid)
    assert get_acl(tree) == original
