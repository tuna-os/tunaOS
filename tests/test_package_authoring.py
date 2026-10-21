"""Offline authoring never guesses names or leaves a partly edited policy."""
import copy
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import package_authoring as author


def tar(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name, contents in entries.items():
            data = contents.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


def apt(*names, arch='amd64'):
    return '\n'.join(f'Package: {name}\nVersion: 1.0\nArchitecture: {arch}\n' for name in names).encode()


def receipt(tmp_path, native_family, data, **overrides):
    family = native_family
    index = tmp_path / (family + '.index')
    index.write_bytes(data)
    result = dict(schema_version=1, family=family, format=author.FORMATS[family],
                  repository='https://example.org/official-index', release='test-release',
                  architecture='amd64' if family == 'apt' else 'source' if family == 'emerge' else 'x86_64',
                  retrieved_at=datetime.now(timezone.utc).isoformat(), path=index.name,
                  sha256=hashlib.sha256(data).hexdigest())
    result.update(overrides)
    path = tmp_path / (family + '.json')
    path.write_text(json.dumps(result))
    return path


@pytest.fixture
def config(tmp_path):
    path = tmp_path / 'tunaos.toml'
    path.write_bytes((ROOT / 'tunaos.toml').read_bytes())
    return path


def command(config, *args):
    return subprocess.run([sys.executable, str(ROOT / 'scripts/config-packages.py'),
                           *args, '--config', str(config)], text=True, capture_output=True)


def test_native_indexes_keep_exact_names_and_filter_architecture(tmp_path):
    rpm = b'<metadata xmlns="http://linux.duke.edu/metadata/common"><package type="rpm"><name>htop</name><arch>x86_64</arch></package><package type="rpm"><name>foreign</name><arch>aarch64</arch></package></metadata>'
    pacman = tar({'htop-1/desc': '%NAME%\nhtop\n\n%ARCH%\nx86_64\n'})
    gentoo = tar({'gentoo/sys-process/htop/htop-3.4.1.ebuild': '# fixture only'})
    for family, data, expected in [('apt', gzip.compress(apt('htop') + b'\n' + apt('foreign', arch='arm64')), {'htop'}),
                                    ('pacman', pacman, {'htop'}), ('emerge', gentoo, {'sys-process/htop'})]:
        names, _ = author.load_index(receipt(tmp_path, family, data), family)
        assert names == expected
    for family in ('fedora', 'rawhide', 'hummingbird', 'eln', 'el10', 'zypper'):
        names, _ = author.load_index(receipt(tmp_path, family, rpm), family)
        assert names == {'htop'}


def test_add_htop_resolves_gentoo_and_is_atomic_idempotent(config, tmp_path):
    config.write_bytes(config.read_bytes().replace(b'[desktops.gnome.packages.emerge]', b'# Keep this comment!\n[desktops.gnome.packages.emerge]'))
    original = config.read_bytes()
    apt_index = receipt(tmp_path, 'apt', apt('htop'))
    emerge_index = receipt(tmp_path, 'emerge', tar({'sys-process/htop/htop-3.4.1.ebuild': ''}))
    args = ['add', 'htop', '--target', 'gnome:apt', '--target', 'gnome:emerge',
            '--index', f'gnome:apt={apt_index}', '--index', f'gnome:emerge={emerge_index}']
    dry = command(config, *args, '--dry-run')
    assert dry.returncode == 0, dry.stderr
    assert 'sys-process/htop' in dry.stdout and 'Dry run' in dry.stdout
    assert config.read_bytes() == original
    assert not list(tmp_path.glob('.*.lock'))
    config.chmod(0o640)
    written = command(config, *args, '--write')
    assert written.returncode == 0, written.stderr
    result = config.read_bytes()
    assert b'# Keep this comment!' in result
    assert config.stat().st_mode & 0o777 == 0o640
    assert len(result) > len(original)
    parsed = author.tunaos_config.load(config)
    assert parsed['desktops']['gnome']['packages']['emerge']['required'][-1] == 'sys-process/htop'
    assert parsed['desktops']['gnome']['packages']['apt']['required'][-1] == 'htop'
    again = command(config, *args, '--write')
    assert again.returncode == 0, again.stderr
    assert 'No change' in again.stdout
    assert config.read_bytes() == result


@pytest.mark.parametrize('problem', ['missing', 'ambiguous', 'bad-json', 'hash', 'unknown-version', 'family', 'stale', 'future', 'naive-time', 'format', 'architecture', 'extra-key'])
def test_any_target_failure_leaves_all_original_bytes(config, tmp_path, problem):
    first = receipt(tmp_path, 'apt', apt('htop'))
    entries = {'sys-process/htop/htop-1.ebuild': ''}
    changes = {}
    if problem == 'ambiguous':
        entries['app-misc/htop/htop-1.ebuild'] = ''
    elif problem == 'missing':
        entries = {'sys-process/other/other-1.ebuild': ''}
    elif problem == 'hash':
        changes['sha256'] = '0' * 64
    elif problem == 'unknown-version':
        changes['schema_version'] = 2
    elif problem == 'family':
        changes['family'] = 'apt'
    elif problem == 'stale':
        changes['retrieved_at'] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    elif problem == 'future':
        changes['retrieved_at'] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    elif problem == 'naive-time':
        changes['retrieved_at'] = '2026-10-21T01:00:00'
    elif problem == 'format':
        changes['format'] = 'invented'
    elif problem == 'architecture':
        changes['architecture'] = 'amd64'
    elif problem == 'extra-key':
        changes['unknown'] = 'value'
    second = receipt(tmp_path, 'emerge', tar(entries), **changes)
    if problem == 'bad-json':
        second.write_text('{')
    before = config.read_bytes()
    result = command(config, 'add', 'htop', '--target', 'gnome:apt', '--target', 'gnome:emerge',
                     '--index', f'gnome:apt={first}', '--index', f'gnome:emerge={second}', '--write')
    assert result.returncode == 1
    assert config.read_bytes() == before
    assert not list(tmp_path.glob('.*.lock'))


def test_search_reports_native_names_and_provenance_without_editing(config, tmp_path):
    index = receipt(tmp_path, 'emerge', tar({'sys-process/htop/htop-1.ebuild': '', 'app-misc/htop/htop-1.ebuild': ''}))
    original = config.read_bytes()
    result = command(config, 'search', 'htop', '--target', 'gnome:emerge', '--index', f'gnome:emerge={index}')
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)[0]
    assert found['matches'] == ['app-misc/htop', 'sys-process/htop']
    assert found['evidence']['sha256']
    assert config.read_bytes() == original


def test_explicit_native_override_must_exist(config, tmp_path):
    index = receipt(tmp_path, 'apt', apt('renamed-tool'))
    args = ['add', 'intent', '--target', 'gnome:apt', '--index', f'gnome:apt={index}']
    assert command(config, *args).returncode == 1
    good = command(config, *args, '--native', 'gnome:apt=renamed-tool', '--write')
    assert good.returncode == 0, good.stderr
    assert author.tunaos_config.load(config)['desktops']['gnome']['packages']['apt']['required'][-1] == 'renamed-tool'


def test_missing_index_unknown_target_and_duplicate_target_fail(config, tmp_path):
    for args in [('--target', 'gnome:apt'), ('--target', 'unknown:apt'),
                 ('--target', 'gnome:apt', '--target', 'gnome:apt')]:
        result = command(config, 'add', 'htop', *args, '--write')
        assert result.returncode == 1


def test_changed_file_is_not_overwritten(config):
    source = config.read_bytes()
    config.write_bytes(source + b'\n# concurrent edit\n')
    with pytest.raises(author.AuthoringError, match='changed'):
        author.atomic_write(config, source, source + b'\n# our edit\n')
    assert config.read_bytes().endswith(b'# concurrent edit\n')


def test_failed_replace_cleans_temporary_and_preserves_original(config, monkeypatch):
    source = config.read_bytes()
    def fail(*args):
        raise OSError('injected disk failure')
    monkeypatch.setattr(author.os, 'replace', fail)
    with pytest.raises(OSError, match='disk failure'):
        author.atomic_write(config, source, source + b'\n')
    assert config.read_bytes() == source
    assert [p.name for p in config.parent.glob('.tunaos.toml.*')] == ['.tunaos.toml.packages.lock']


def test_symlink_config_is_not_replaced(config, tmp_path):
    link = tmp_path / 'linked.toml'
    link.symlink_to(config)
    with pytest.raises(author.AuthoringError, match='non-symlink'):
        author.atomic_write(link, config.read_bytes(), b'bad')


@pytest.mark.parametrize('kind,data,arch', [('apt-packages', b'garbage', 'amd64'),
    ('rpm-primary', b'<!DOCTYPE x [<!ENTITY a "boom">]><x/>', 'x86_64'),
    ('pacman-db', tar({'pkg/desc': '%NAME%\nhtop\n'}), 'x86_64'),
    ('gentoo-tree', tar({'sys-process/htop/wrong-1.ebuild': ''}), 'source')])
def test_malformed_native_index_rejected(kind, data, arch):
    with pytest.raises(author.AuthoringError):
        author.native_names(data, kind, arch)


def test_preserves_inline_comments_order_and_shared_includes(config):
    source = config.read_bytes().replace(b'"gnome-base/gnome-light",', b'"gnome-base/gnome-light", # keep item comment')
    document = author.tunaos_config.validate(author.tunaos_config.tomllib.loads(source.decode()))
    edited = author.edit(source, document, {'gnome:emerge': ('gnome', 'emerge')}, {'gnome:emerge': 'sys-process/htop'})
    assert b'"gnome-base/gnome-light", # keep item comment' in edited
    before = copy.deepcopy(document)
    before['desktops']['gnome']['packages']['emerge']['required'].append('sys-process/htop')
    assert author.tunaos_config.tomllib.loads(edited.decode()) == before


def test_shared_required_is_noop_and_missing_required_array_is_created(config):
    source = config.read_bytes()
    document = author.tunaos_config.validate(author.tunaos_config.tomllib.loads(source.decode()))
    policy = document['desktops']['gnome']['packages']['emerge']
    name = policy['required'][0]
    unchanged = author.edit(source, document, {'gnome:emerge': ('gnome', 'emerge')}, {'gnome:emerge': name})
    assert unchanged == source
    # A group inclusion with no local required array is valid existing schema.
    import tomlkit
    tree = tomlkit.parse(source.decode())
    tree['package_groups']['author-test'] = {'required': [name]}
    target = tree['desktops']['gnome']['packages']['emerge']
    del target['required']
    target['include'] = ['author-test']
    source = tomlkit.dumps(tree).encode()
    document = author.tunaos_config.validate(author.tunaos_config.tomllib.loads(source.decode()))
    assert author.edit(source, document, {'gnome:emerge': ('gnome', 'emerge')}, {'gnome:emerge': name}) == source
    result = author.edit(source, document, {'gnome:emerge': ('gnome', 'emerge')}, {'gnome:emerge': 'sys-process/htop'})
    assert author.tunaos_config.tomllib.loads(result.decode())['desktops']['gnome']['packages']['emerge']['required'] == ['sys-process/htop']


def test_excluded_package_requires_manual_reconciliation(config):
    import tomlkit
    tree = tomlkit.parse(config.read_text())
    tree['desktops']['gnome']['packages']['fedora']['exclude'] = ['htop']
    source = tomlkit.dumps(tree).encode()
    document = author.tunaos_config.validate(author.tunaos_config.tomllib.loads(source.decode()))
    with pytest.raises(author.AuthoringError, match='excluded'):
        author.edit(source, document, {'gnome:fedora': ('gnome', 'fedora')}, {'gnome:fedora': 'htop'})


def test_duplicate_receipt_fields_fail(tmp_path):
    path = receipt(tmp_path, 'apt', apt('htop'))
    path.write_text(path.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    with pytest.raises(author.AuthoringError, match='duplicate receipt'):
        author.load_index(path, 'apt')


def test_index_decompression_is_bounded(monkeypatch):
    monkeypatch.setattr(author, 'MAX_BYTES', 100)
    with pytest.raises(author.AuthoringError, match='limit'):
        author.native_names(gzip.compress(b'x' * 101), 'apt-packages', 'amd64')


def test_missing_lossless_editor_has_actionable_error(config, monkeypatch):
    source = config.read_bytes()
    document = author.tunaos_config.validate(author.tunaos_config.tomllib.loads(source.decode()))
    monkeypatch.setitem(sys.modules, 'tomlkit', None)
    with pytest.raises(author.AuthoringError, match='requirements-package-authoring.txt'):
        author.edit(source, document, {'gnome:emerge': ('gnome', 'emerge')}, {'gnome:emerge': 'sys-process/htop'})


def test_config_and_receipt_reads_are_bounded(config, tmp_path, monkeypatch):
    monkeypatch.setattr(author, 'MAX_CONFIG_BYTES', 10)
    with pytest.raises(author.AuthoringError, match='limit'):
        author.read_config(config)
    path = receipt(tmp_path, 'apt', apt('htop'))
    monkeypatch.setattr(author, 'MAX_RECEIPT_BYTES', 10)
    with pytest.raises(author.AuthoringError, match='limit'):
        author.load_index(path, 'apt')


def test_nonregular_input_and_lock_fail_without_blocking(config, tmp_path):
    fifo = tmp_path / 'fifo'
    author.os.mkfifo(fifo)
    with pytest.raises(author.AuthoringError, match='regular file'):
        author.read_config(fifo)
    lock = config.with_name('.' + config.name + '.packages.lock')
    author.os.mkfifo(lock)
    with pytest.raises(author.AuthoringError, match='lock must be a regular file'):
        author.atomic_write(config, config.read_bytes(), b'changed')


def test_directory_fsync_failure_reports_committed_outcome(config, monkeypatch):
    source = config.read_bytes()
    result = source + b'\n# committed\n'
    actual_fsync = author.os.fsync
    calls = 0
    def fail_directory(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('injected directory sync failure')
        actual_fsync(fd)
    monkeypatch.setattr(author.os, 'fsync', fail_directory)
    with pytest.raises(author.AuthoringError, match='file replaced; durability unconfirmed'):
        author.atomic_write(config, source, result)
    assert config.read_bytes() == result
