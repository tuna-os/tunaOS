"""Real libacl operations only on temporary fixtures; no host ACL changes."""
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('diagnostic_acl', ROOT / 'scripts/diagnostic-acl.py')
acl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acl)


def read(path):
    with acl.physical(path) as (fd, _):
        return acl.read_acl(fd)


def write(path, text):
    with acl.physical(path) as (fd, _):
        acl.write_acl(fd, text)


def tree(tmp_path):
    root = tmp_path/'modules'
    root.mkdir()
    module = root/'module'
    module.write_bytes(b'fixture')
    uid = os.getuid()
    for path in (root, module):
        write(path, f'user::rwx\ngroup:{os.getgid()}:rwx\ngroup::rwx\nmask::r--\nother::---\n')
    return root, module, uid


def effective(text):
    entries = dict(line.rsplit(':', 1) for line in text.splitlines())
    mask = set(entries.get('mask:', 'rwx')) - {'-'}
    return {key: set(value) - {'-'} if key in ('user:', 'other:') else set(value) & mask - {'-'}
            for key, value in entries.items() if key != 'mask:'}


def test_exact_restore_and_effective_rights(tmp_path):
    root, module, uid = tree(tmp_path)
    original = {p: read(p) for p in (root, module)}
    sentinel = tmp_path/'outside'; sentinel.write_text('untouched')
    before = read(sentinel)
    (root/'build').symlink_to(sentinel)
    state = tmp_path/'snapshot'
    acl.grant(root, state, uid)
    for path, old in original.items():
        after = effective(read(path))
        assert after.pop(f'user:{uid}') == ({'r', 'x'} if path == root else {'r'})
        assert after == effective(old)
    acl.restore(state)
    assert {p: read(p) for p in original} == original
    assert read(sentinel) == before


@pytest.mark.parametrize('replacement', ['symlink', 'directory'])
def test_replaced_ancestor_refused_and_recovery_retained(tmp_path, replacement):
    parent = tmp_path/'parent'; parent.mkdir()
    root, module, uid = tree(parent)
    state = tmp_path/'snapshot'
    acl.grant(root, state, uid)
    original = parent.rename(tmp_path/'original')
    sentinel = tmp_path/'sentinel'; sentinel.mkdir()
    outside, outside_module, _ = tree(sentinel)
    before = {p: read(p) for p in (outside, outside_module)}
    if replacement == 'symlink':
        parent.symlink_to(sentinel, target_is_directory=True)
    else:
        parent.mkdir()
        tree(parent)
    with pytest.raises((OSError, ValueError)):
        acl.restore(state)
    assert state.exists()
    assert {p: read(p) for p in before} == before
    if replacement == 'symlink':
        parent.unlink()
    else:
        (parent/'modules/module').unlink(); (parent/'modules').rmdir(); parent.rmdir()
    original.rename(parent)
    acl.restore(state)


def test_symlinked_root_and_snapshot_ancestor_refused(tmp_path):
    root, _, uid = tree(tmp_path)
    link = tmp_path/'link'; link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        acl.grant(link/'modules', tmp_path/'state', uid)
    with pytest.raises(OSError):
        acl.grant(root, link/'state', uid)
    assert not (tmp_path/'state').exists()


@pytest.mark.parametrize('uid', [os.getuid()])
def test_existing_runner_acl_refused_without_state_or_mutation(tmp_path, uid):
    root, module, _ = tree(tmp_path)
    write(module, f'user::rw-\nuser:{uid}:r--\ngroup::r--\nmask::r--\nother::---\n')
    before = {p: read(p) for p in (root, module)}
    state = tmp_path/'snapshot'
    with pytest.raises(ValueError, match='runner ACL already exists'):
        acl.grant(root, state, uid)
    assert not state.exists()
    assert {p: read(p) for p in before} == before


def test_partial_grant_and_restore_failure_retry(tmp_path, monkeypatch):
    root, module, uid = tree(tmp_path)
    before = {p: read(p) for p in (root, module)}
    state = tmp_path/'snapshot'
    real = acl.write_acl
    calls = 0
    def fail(fd, text):
        nonlocal calls
        calls += 1
        if calls in (2, 3):
            raise OSError('injected grant then rollback failure')
        real(fd, text)
    monkeypatch.setattr(acl, 'write_acl', fail)
    with pytest.raises(OSError):
        acl.grant(root, state, uid)
    assert state.exists()
    saved = state.read_bytes()
    with pytest.raises((FileExistsError, ValueError)):
        acl.grant(root, state, uid+2)
    assert state.read_bytes() == saved
    monkeypatch.setattr(acl, 'write_acl', real)
    acl.restore(state)
    assert {p: read(p) for p in before} == before


def test_replacement_during_write_cannot_redirect_descriptor(tmp_path, monkeypatch):
    root, module, uid = tree(tmp_path)
    sentinel = tmp_path/'sentinel'; sentinel.write_text('outside')
    before = read(sentinel)
    real = acl.write_acl
    def replace(fd, text):
        if os.fstat(fd).st_ino == module.stat().st_ino:
            module.rename(root/'original')
            module.symlink_to(sentinel)
        real(fd, text)
    monkeypatch.setattr(acl, 'write_acl', replace)
    with pytest.raises(OSError):
        acl.grant(root, tmp_path/'snapshot', uid)
    assert read(sentinel) == before
    with pytest.raises(OSError):
        acl.restore(tmp_path/'snapshot')


def test_hardlinked_outside_sentinel_refused(tmp_path):
    root, module, uid = tree(tmp_path)
    outside = tmp_path/'outside'
    outside.write_text('outside')
    before = read(outside)
    os.link(outside, root/'alias')
    with pytest.raises(ValueError, match='hardlinked'):
        acl.grant(root, tmp_path/'snapshot', uid)
    (root/'alias').unlink()
    assert read(outside) == before
    assert not (tmp_path/'snapshot').exists()


def test_numeric_existing_unknown_uid_refused():
    with pytest.raises(ValueError, match='runner ACL already exists'):
        acl._safe_acl_modifications(['user:12001:r--', 'group::r--'], 12001, False)
