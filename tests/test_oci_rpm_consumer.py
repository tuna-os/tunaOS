"""Offline consumer contract; fake native tools, no registry or image claims."""
import hashlib
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('consumer', ROOT / 'scripts/install-oci-rpm-repository.py')
consumer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(consumer)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    tool, key, packages, repos = [tmp_path / n for n in ('transport.py', 'key', 'packages', 'repos')]
    tool.write_text('# fixture')
    key.write_text('fixture public key')
    packages.write_text('gnome-shell\ngdm\n')
    repos.mkdir()
    (repos / 'distro.repo').write_text('[distro]\nbaseurl=https://distro.example/repo\nenabled=1\ngpgcheck=1\nrepo_gpgcheck=1\ngpgkey=' + key.as_uri() + '\n')
    monkeypatch.setattr(consumer, 'TRANSPORT_SHA256', hashlib.sha256(tool.read_bytes()).hexdigest())
    runtime = tmp_path / 'etc'
    runtime.mkdir()
    args = SimpleNamespace(runtime_config_root=runtime, transport=tool, key=key, packages=packages, upstream_repos=repos,
                           key_sha256=hashlib.sha256(key.read_bytes()).hexdigest(),
                           reference='ghcr.io/example/repository@sha256:' + 'a' * 64,
                           identity='https://github.com/example/repository/.github/workflows/publish.yml@refs/heads/main',
                           target='el10-x86_64', architecture='x86_64', priority=1)
    calls, workdirs = [], []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == 'dnf' and '--version' in command:
            return SimpleNamespace(stdout='4.24.0\n')
        if 'pull' in command:
            repo = Path(command[command.index('--destination') + 1])
            workdirs.append(repo.parent)
            (repo / 'repodata').mkdir(parents=True)
            (repo / 'repodata/repomd.xml').write_text('<repomd/>')
            (repo / 'repodata/repomd.xml.asc').write_text('signature')
            (repo / 'fixture.rpm').write_text('rpm')
        elif command[0] == 'dnf':
            root = workdirs[-1]
            config = (root / 'repos/tunaos-oci.repo').read_text()
            for required in ('gpgcheck=1\n', 'repo_gpgcheck=1\n', 'gpgkey=file://', 'baseurl=file://'):
                assert required in config
            assert not consumer.CONTROLLED.search(config)
            assert 'priority=1\n' in config
            assert '--noplugins' in command and '--config' in command
            assert command[-3:] == ['install', 'gnome-shell', 'gdm']
            assert (root / 'repos/distro.repo').is_file()
        if '--checksig' in command:
            return SimpleNamespace(stdout='fixture: digests signatures OK\n')
        if '-qp' in command:
            return SimpleNamespace(stdout='x86_64')
        return SimpleNamespace(stdout='gdm\t51.0-1\tx86_64\ngnome-shell\t51.0-1\tx86_64\n')

    monkeypatch.setattr(consumer.subprocess, 'run', run)
    return args, calls, workdirs, run


def test_pull_solver_inventory_order_and_cleanup(fixture):
    args, calls, workdirs, _ = fixture
    receipt = consumer.install(args)
    assert calls[0][0] == 'dnf' and '--version' in calls[0]
    assert 'pull' in calls[1]
    for flag in ('identity', 'target', 'reference', 'architecture'):
        assert calls[1][calls[1].index('--' + flag) + 1] == getattr(args, flag)
    dnf_index = next(i for i, c in enumerate(calls) if c[0] == 'dnf' and '--version' not in c)
    assert any('--verify' in c for c in calls[:dnf_index])
    assert any('--checksig' in c for c in calls[:dnf_index])
    assert calls[-1][0] == 'rpm' and '-qa' in calls[-1]
    assert receipt['priority'] == 1
    assert receipt['requested_packages'] == ['gnome-shell', 'gdm']
    assert len(receipt['installed_rpms']) == 2
    assert all(not p.exists() for p in workdirs)
    assert args.key.exists() and args.upstream_repos.exists()


@pytest.mark.parametrize('field,value', [
    ('reference', 'ghcr.io/example/repository:latest'), ('identity', 'https://github.com/example/.*'),
    ('priority', 0), ('priority', 100), ('target', '../escape'), ('architecture', 'ppc64le'), ('key_sha256', 'b' * 64),
])
def test_invalid_input_before_commands(fixture, field, value):
    args, calls, _, _ = fixture
    setattr(args, field, value)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('name', ['transport', 'key'])
@pytest.mark.parametrize('failure', ['missing', 'changed', 'symlink'])
def test_required_reviewed_local_inputs(fixture, tmp_path, name, failure):
    args, calls, _, _ = fixture
    path = getattr(args, name)
    if failure == 'missing':
        path.unlink()
    elif failure == 'changed':
        path.write_text('changed')
    else:
        link = tmp_path / 'link'
        link.symlink_to(path)
        setattr(args, name, link)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('url', ['https://repo.tunaos.org/public.gpg', 'https://download.tunaos.org/repo',
                                  'https://bucket.r2.cloudflarestorage.com/repo', 'https://public.r2.dev/key'])
def test_no_r2_in_upstream_keys_or_baseurls(fixture, url):
    args, calls, _, _ = fixture
    (args.upstream_repos / 'distro.repo').write_text('[distro]\ngpgkey=' + url)
    with pytest.raises(ValueError, match='R2 URL remains'):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('packages', ['', '--nogpgcheck\n', 'gnome-shell\n\n', 'https://host/rpm\n'])
def test_inventory_cannot_inject_flags(fixture, packages):
    args, calls, _, _ = fixture
    args.packages.write_text(packages)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('stage', ['pull', 'dnf', 'rpm'])
def test_failures_clean_staging_and_no_fallback(fixture, monkeypatch, stage):
    args, calls, workdirs, run = fixture

    def fail(command, **kwargs):
        result = run(command, **kwargs)
        if stage in command and '--version' not in command:
            raise subprocess.CalledProcessError(1, command)
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        consumer.install(args)
    assert all(not p.exists() for p in workdirs)
    assert not any('curl' in c or 'wget' in c for c in calls)
    if stage == 'pull':
        assert len(calls) == 2


def test_missing_metadata_blocks_solver(fixture, monkeypatch):
    args, calls, workdirs, run = fixture

    def missing(command, **kwargs):
        result = run(command, **kwargs)
        if 'pull' in command:
            (workdirs[-1] / 'repository/repodata/repomd.xml').unlink()
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', missing)
    with pytest.raises(ValueError, match='metadata'):
        consumer.install(args)
    assert len(calls) == 2
    assert all(not p.exists() for p in workdirs)


@pytest.mark.parametrize('when', ['before', 'after'])
def test_persistent_r2_configs_block_even_if_disabled(fixture, monkeypatch, when):
    args, calls, workdirs, run = fixture
    target = args.runtime_config_root / 'yum.repos.d/legacy.repo'
    target.parent.mkdir()

    def write():
        target.write_text('[old]\nenabled=0\ngpgkey=https://repo.tunaos.org/public.gpg\n')

    if when == 'before':
        write()
    else:
        def generated(command, **kwargs):
            result = run(command, **kwargs)
            if command[0] == 'dnf' and '--version' not in command:
                write()
            return result
        monkeypatch.setattr(consumer.subprocess, 'run', generated)
    with pytest.raises(ValueError, match='R2 URL remains'):
        consumer.install(args)
    assert all(not p.exists() for p in workdirs)
    if when == 'before':
        assert calls == []


@pytest.mark.parametrize('content', [
    '[distro]\ngpgcheck=0\n', '[main]\nplugins=1\n',
    '[tunaos-oci]\nbaseurl=https://example.org\n',
    '[distro]\nbaseurl=https://${host}/repo\n',
    '[distro]\nmirrorlist=https://example.org\n',
    '[DEFAULT]\ngpgcheck=1\n',
])
def test_unsafe_upstream_config_rejected_before_transport(fixture, content):
    args, calls, _, _ = fixture
    (args.upstream_repos / 'distro.repo').write_text(content)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('content', ['[main]\nreposdir=/etc/other\n',
                                     '[main]\nvarsdir=/tmp/vars\n',
                                     '[old]\nbaseurl=https://${host}/repo\n'])
def test_indirect_runtime_configs_fail_closed(fixture, content):
    args, calls, _, _ = fixture
    (args.runtime_config_root / 'yum.conf').write_text(content)
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


@pytest.mark.parametrize('bad', ['unsigned', 'wrong-arch', 'missing-signature', 'bad-key'])
def test_native_trust_rejection_precedes_dnf(fixture, monkeypatch, bad):
    args, calls, workdirs, run = fixture

    def reject(command, **kwargs):
        result = run(command, **kwargs)
        if 'pull' in command and bad == 'missing-signature':
            (workdirs[-1] / 'repository/repodata/repomd.xml.asc').unlink()
        if '--checksig' in command and bad == 'unsigned':
            return SimpleNamespace(stdout='fixture: digests OK\n')
        if '-qp' in command and bad == 'wrong-arch':
            return SimpleNamespace(stdout='aarch64')
        if '--verify' in command and bad == 'bad-key':
            raise subprocess.CalledProcessError(1, command)
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', reject)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        consumer.install(args)
    assert not any(c[0] == 'dnf' and '--version' not in c for c in calls)
    assert all(not p.exists() for p in workdirs)


@pytest.mark.parametrize('url', ['https://repo%2Etunaos.org/repo', 'https://repo\\.tunaos.org/repo'])
def test_noncanonical_url_rejected(fixture, url):
    args, calls, _, _ = fixture
    path = args.upstream_repos / 'distro.repo'
    path.write_text(path.read_text().replace('https://distro.example/repo', url))
    with pytest.raises(ValueError):
        consumer.install(args)
    assert calls == []


def test_dnf5_refused_before_transport(fixture, monkeypatch):
    args, calls, _, run = fixture

    def version(command, **kwargs):
        result = run(command, **kwargs)
        if command[0] == 'dnf' and '--version' in command:
            return SimpleNamespace(stdout='dnf5 version 5.2.0\n')
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', version)
    with pytest.raises(ValueError, match='only DNF4'):
        consumer.install(args)
    assert len(calls) == 1


def test_upstream_key_snapshotted_and_receipted(fixture, monkeypatch):
    args, _calls, workdirs, run = fixture
    original = args.key.read_bytes()

    def replaced(command, **kwargs):
        if 'pull' in command:
            args.key.write_text('changed after validation')
        result = run(command, **kwargs)
        if command[0] == 'dnf' and '--version' not in command:
            root = workdirs[-1]
            config = (root / 'repos/distro.repo').read_text()
            assert args.key.as_uri() not in config
            assert (root / ('upstream-key-' + hashlib.sha256(original).hexdigest())).read_bytes() == original
            assert kwargs['stdout'] is consumer.sys.stderr
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', replaced)
    receipt = consumer.install(args)
    assert receipt['upstream_keys'][args.key.as_uri()] == hashlib.sha256(original).hexdigest()



def test_transport_isolated_and_dnf_vars_filtered(fixture, monkeypatch):
    args, _calls, _workdirs, run = fixture
    monkeypatch.setenv('DNF_VAR_HOST', 'repo.tunaos.org')

    def isolated(command, **kwargs):
        if 'pull' in command:
            assert command[1] == '-I'
            assert kwargs['stdout'] is consumer.sys.stderr
        if command[0] == 'dnf':
            assert '--noplugins' in command and '--config' in command
            assert 'DNF_VAR_HOST' not in kwargs['env']
            assert any(c.startswith('--setopt=varsdir=') for c in command)
        return run(command, **kwargs)

    monkeypatch.setattr(consumer.subprocess, 'run', isolated)
    consumer.install(args)



def test_overlapping_key_paths_rewritten_per_section(fixture, monkeypatch):
    args, _calls, workdirs, run = fixture
    extra = args.key.with_name(args.key.name + '-extra')
    extra.write_text('other reviewed public key')
    path = args.upstream_repos / 'distro.repo'
    path.write_text(path.read_text() + path.read_text().replace('[distro]', '[extra]').replace(args.key.as_uri(), extra.as_uri()))

    def check(command, **kwargs):
        result = run(command, **kwargs)
        if command[0] == 'dnf' and '--version' not in command:
            parser = consumer.configparser.ConfigParser()
            parser.read(workdirs[-1] / 'repos/distro.repo')
            for section, original in [('distro', args.key), ('extra', extra)]:
                path = Path(consumer.urlsplit(parser[section]['gpgkey']).path)
                assert path.read_bytes() == original.read_bytes()
        return result

    monkeypatch.setattr(consumer.subprocess, 'run', check)
    consumer.install(args)
