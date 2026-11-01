"""tunaOS#3812: QEMU acquisition must not fail through the Azure archive.

Job 121823081846 built grouper but could not acquire the tools to boot it.
Falsification: behavioural — use Azure source fixtures and a stalled downloader;
assert official HTTPS in private sources and no installation after exhaustion.
"""

import hashlib
import importlib.util
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('kvm_tools', ROOT / 'scripts/setup-kvm-tools.py')
kvm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kvm)


@pytest.mark.parametrize('archive_uri', [kvm.OFFICIAL_ARCHIVE, kvm.NOBLE_ARCHIVE])
@pytest.mark.parametrize('source', [
    'deb [arch=amd64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://azure.archive.ubuntu.com/ubuntu noble main universe\n',
    'Types: deb\nURIs: http://azure.archive.ubuntu.com/ubuntu/\nSuites: noble noble-updates noble-backports\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n',
    'deb https://azure.archive.ubuntu.com/ubuntu resolute main\n',
])
def test_only_official_uri_changes(source, archive_uri):
    expected = source.replace('http://azure.archive.ubuntu.com/ubuntu/', archive_uri)
    expected = expected.replace('http://azure.archive.ubuntu.com/ubuntu', archive_uri)
    expected = expected.replace('https://azure.archive.ubuntu.com/ubuntu', archive_uri)
    assert kvm.source_text(source, archive_uri=archive_uri) == expected


@pytest.mark.parametrize('uri', ['http://azure.archive.ubuntu.com.evil/ubuntu',
                                'http://evil@azure.archive.ubuntu.com/ubuntu',
                                'http://azure.archive.ubuntu.com/ubuntu-other',
                                'https://packages.microsoft.com/ubuntu/24.04/prod',
                                'http://security.ubuntu.com/ubuntu'])
def test_other_sources_are_unchanged(uri):
    source = f'deb {uri} noble main\n'
    assert kvm.source_text(source) == source


def test_snapshot_keeps_trust_and_components_for_security_and_mirror_sources(tmp_path):
    write_mirrors(tmp_path)
    source = (
        RUNNER_SOURCES[0]
        + '\nTypes: deb\nURIs: https://security.ubuntu.com/ubuntu/\n'
        + 'Suites: noble-security\nComponents: main restricted universe multiverse\n'
        + 'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n'
    )
    actual = kvm.source_text(source, tmp_path, archive_uri=kvm.NOBLE_ARCHIVE)
    assert actual == source.replace(kvm.RUNNER_MIRROR, kvm.NOBLE_ARCHIVE).replace(
        'https://security.ubuntu.com/ubuntu/', kvm.NOBLE_ARCHIVE)
    assert 'Check-Valid-Until' not in actual
    assert 'trusted=' not in actual


@pytest.mark.parametrize('uri', [
    'http://snapshot.ubuntu.com/ubuntu/20261026T000000Z',
    'https://snapshot.ubuntu.com.evil/ubuntu/20261026T000000Z',
    'https://archive.ubuntu.com/ubuntu?trusted=yes',
])
def test_unapproved_snapshot_target_is_refused(uri):
    with pytest.raises(ValueError, match='Unsupported KVM tool archive'):
        kvm.source_text('deb https://archive.ubuntu.com/ubuntu noble main\n', archive_uri=uri)


@pytest.fixture
def fake_runner(tmp_path, monkeypatch):
    (tmp_path / 'usr/lib').mkdir(parents=True)
    (tmp_path / 'usr/lib/os-release').write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
    sources = tmp_path / 'etc/apt/sources.list.d'
    sources.mkdir(parents=True)
    original = 'deb http://azure.archive.ubuntu.com/ubuntu noble main universe\n'
    (sources / 'ubuntu.list').write_text(original)
    (tmp_path / 'etc/apt/sources.list').write_text(original)
    cache = tmp_path / 'var/cache/apt/archives'
    cache.mkdir(parents=True)
    calls = []
    state = {'failures': 0, 'signature_error': False, 'install_error': False,
             'corrupt': False, 'arch': 'amd64', 'version': '1.0', 'empty_manifest': False}
    payload = b'authenticated qemu fixture'
    digest = hashlib.sha256(payload).hexdigest()

    def run(args, timeout=None):
        calls.append((args, timeout))
        if args[0] == 'dpkg':
            return state['arch']
        if args[0] == 'dpkg-query':
            return 'installed' if 'Status' in args[2] else state['version']
        source_dir = Path(next(a.split('=', 1)[1] for a in args if a.startswith('Dir::Etc::sourceparts=')))
        state['temporary'] = source_dir.parent
        for path in (source_dir / 'ubuntu.list', source_dir.parent / 'sources.list'):
            fields = path.read_text().split()
            assert fields[0] == 'deb' and fields[2:] == ['noble', 'main', 'universe']
            assert re.fullmatch(r'https://snapshot\.ubuntu\.com/ubuntu/[0-9]{8}T[0-9]{6}Z',
                                fields[1])
        assert (sources / 'ubuntu.list').read_text() == original
        assert 'Acquire::ForceHash=SHA256' in args
        assert 'APT::Update::Error-Mode=any' in args
        assert not any(x in args for x in ('--allow-unauthenticated', '--fix-missing', '--allow-downgrades'))
        if 'update' in args:
            if state['signature_error']:
                raise subprocess.CalledProcessError(100, args, 'invalid signature')
            return ''
        assert all(p in args for p in ('qemu-system-x86', 'qemu-utils', 'ovmf', 'ffmpeg'))
        assert not any('/resolute' in a for a in args)
        if '--simulate' in args:
            return 'Inst qemu-system-x86 (1.0 Ubuntu:24.04/noble [amd64])\n'
        if '--print-uris' in args:
            if state['empty_manifest']:
                return ''
            return f"'https://archive.ubuntu.com/ubuntu/pool/q.deb' q.deb {len(payload)} SHA256:{digest}\n"
        if '--download-only' in args:
            assert 0 < timeout <= 200
            if state['failures']:
                state['failures'] -= 1
                raise subprocess.TimeoutExpired(args, timeout)
            (cache / 'q.deb').write_bytes(b'corrupt' if state['corrupt'] else payload)
            return ''
        assert '--no-download' in args and timeout is None
        assert (cache / 'q.deb').read_bytes() == payload
        assert len(list((tmp_path / 'etc/needrestart/conf.d').glob('99-tunaos-*.conf'))) == 1
        if state['install_error']:
            raise subprocess.CalledProcessError(100, args)
        return ''

    monkeypatch.setattr(kvm.apt, 'run', run)
    return tmp_path, calls, state


@pytest.mark.parametrize('cached', [None, b'authenticated qemu fixture', b'corrupt'])
def test_cache_and_offline_install(fake_runner, cached):
    root, calls, state = fake_runner
    if cached is not None:
        (root / 'var/cache/apt/archives/q.deb').write_bytes(cached)
    kvm.install(root)
    assert sum('--no-download' in args for args, _ in calls) == 1
    assert not state['temporary'].exists()
    assert not list((root / 'etc/needrestart/conf.d').glob('99-tunaos-*.conf'))


@pytest.mark.parametrize('key,error', [('signature_error', subprocess.CalledProcessError),
                                     ('corrupt', RuntimeError), ('empty_manifest', RuntimeError)])
def test_invalid_acquisition_never_installs(fake_runner, key, error):
    root, calls, state = fake_runner
    state[key] = True
    with pytest.raises(error):
        kvm.install(root)
    assert not any('--no-download' in args for args, _ in calls)
    assert not state['temporary'].exists()


def test_download_retry_limit(fake_runner):
    root, calls, state = fake_runner
    state['failures'] = 3
    with pytest.raises(subprocess.TimeoutExpired):
        kvm.install(root)
    assert sum('--download-only' in args and '--print-uris' not in args for args, _ in calls) == 3
    assert not any('--no-download' in args for args, _ in calls)


def test_retry_then_success(fake_runner):
    root, _, state = fake_runner
    state['failures'] = 2
    kvm.install(root)


def test_global_deadline(fake_runner, monkeypatch):
    root, calls, _ = fake_runner
    monkeypatch.setattr(kvm.time, 'monotonic', iter([0, 601, 602]).__next__)
    with pytest.raises(TimeoutError):
        kvm.install(root)
    assert len(calls) == 1


def test_install_failure_cleans_suppression(fake_runner):
    root, calls, state = fake_runner
    state['install_error'] = True
    with pytest.raises(subprocess.CalledProcessError):
        kvm.install(root)
    assert not list((root / 'etc/needrestart/conf.d').glob('99-tunaos-*.conf'))
    assert not state['temporary'].exists()
    assert sum('--no-download' in args for args, _ in calls) == 1


def test_installed_version_must_match_plan(fake_runner):
    root, _, state = fake_runner
    state['version'] = 'wrong'
    with pytest.raises(RuntimeError, match='expected 1.0'):
        kvm.install(root)


def test_unsupported_architecture_has_no_apt(fake_runner):
    root, calls, state = fake_runner
    state['arch'] = 'arm64'
    with pytest.raises(ValueError, match='amd64'):
        kvm.install(root)
    assert len(calls) == 1


@pytest.mark.parametrize('finished_at', [599.0, 600.0, 601.0])
def test_final_cache_verification_obeys_deadline(fake_runner, monkeypatch, finished_at):
    root, calls, state = fake_runner
    clock = [0.0]
    checks = [0]
    original_verify = kvm.apt.verify_cache

    def slow_verify(cache, entries):
        valid = original_verify(cache, entries)
        checks[0] += 1
        if checks[0] == 2:
            clock[0] = finished_at
        return valid

    monkeypatch.setattr(kvm.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(kvm.apt, 'verify_cache', slow_verify)
    if finished_at >= 600:
        with pytest.raises(TimeoutError, match='deadline exhausted'):
            kvm.install(root)
        assert not any('--no-download' in args for args, _ in calls)
        assert not (root / 'etc/needrestart/conf.d').exists()
    else:
        kvm.install(root)
        assert sum('--no-download' in args for args, _ in calls) == 1
    assert checks[0] == 2
    assert not state['temporary'].exists()


RUNNER_MIRRORS = (
    'http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\n'
    'https://archive.ubuntu.com/ubuntu/\tpriority:2\n'
    'https://security.ubuntu.com/ubuntu/\tpriority:3\n'
)
RUNNER_SOURCES = [
    'Types: deb\nURIs: mirror+file:/etc/apt/apt-mirrors.txt\n'
    'Suites: noble noble-updates noble-backports\n'
    'Components: main restricted universe multiverse\n'
    'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n',
    'deb [arch=amd64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] '
    'mirror+file:/etc/apt/apt-mirrors.txt noble main restricted universe multiverse\n',
    'Types: deb deb-src\nURIs:\n mirror+file:/etc/apt/apt-mirrors.txt\n'
    'Suites: resolute resolute-security\nComponents: main universe\n'
    'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n',
]


def write_mirrors(root, text=RUNNER_MIRRORS):
    path = root / 'etc/apt/apt-mirrors.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.mark.parametrize('source', RUNNER_SOURCES)
def test_runner_mirror_sources_keep_suite_components_and_trust(tmp_path, source):
    path = write_mirrors(tmp_path)
    assert kvm.source_text(source, tmp_path) == source.replace(
        'mirror+file:/etc/apt/apt-mirrors.txt', 'https://archive.ubuntu.com/ubuntu')
    assert path.read_text() == RUNNER_MIRRORS


@pytest.mark.parametrize('uri', [
    'mirror:', 'mirror+file:', 'mirror+https:',
    'mirror+file:/tmp/apt-mirrors.txt', 'mirror+file:/etc/apt/../apt/apt-mirrors.txt',
    'mirror+file:///etc/apt/apt-mirrors.txt', 'mirror+file:/etc/apt/apt-mirrors.txt?x=1',
    'mirror+file:/etc/apt/apt-mirrors.txt/extra', 'mirror+https://example.com/mirrors',
    'mirror://example.com/mirrors', 'mirror+file:/etc/apt/apt-mirrors.txt#fragment',
])
def test_unknown_mirror_forms_refused(tmp_path, uri):
    write_mirrors(tmp_path)
    with pytest.raises(ValueError, match='Unsupported APT mirror source'):
        kvm.source_text(f'deb {uri} noble main\n', tmp_path)


@pytest.mark.parametrize('contents', [
    '', '# empty\n', 'https://evil.example/ubuntu\n',
    RUNNER_MIRRORS + 'https://archive.ubuntu.com.evil/ubuntu\n',
    'https://user@archive.ubuntu.com/ubuntu\n',
    'https://archive.ubuntu.com/ubuntu-other\n',
    'https://archive.ubuntu.com/ubuntu\tpriority:1 arch:arm64\n',
    'https://archive.ubuntu.com/ubuntu\ttrusted:yes\n',
    'file:/srv/ubuntu\n', 'mirror+file:/etc/apt/other.txt\n',
    'https://archive.ubuntu.com/ubuntu\tpriority:bad\n',
])
def test_unknown_or_empty_mirror_list_refused(tmp_path, contents):
    write_mirrors(tmp_path, contents)
    with pytest.raises(ValueError):
        kvm.source_text(RUNNER_SOURCES[0], tmp_path)


def test_missing_symlinked_and_oversized_mirror_list_refused(tmp_path):
    with pytest.raises(ValueError):
        kvm.source_text(RUNNER_SOURCES[0], tmp_path)
    path = write_mirrors(tmp_path)
    other = tmp_path / 'other'
    other.write_text(RUNNER_MIRRORS)
    path.unlink()
    path.symlink_to(other)
    with pytest.raises(ValueError):
        kvm.source_text(RUNNER_SOURCES[0], tmp_path)
    path.unlink()
    path.write_text('#' * 16385)
    with pytest.raises(ValueError):
        kvm.source_text(RUNNER_SOURCES[0], tmp_path)


def test_comments_and_unrelated_sources_are_unchanged(tmp_path):
    text = ('# deb mirror+file:/unrelated noble main\n'
            'deb https://packages.microsoft.com/ubuntu/24.04/prod noble main '
            '# mirror+https://unrelated\n')
    assert kvm.source_text(text, tmp_path) == text


def test_install_normalizes_private_mirror_sources_only(fake_runner, monkeypatch):
    root, _, _ = fake_runner
    mirrors = write_mirrors(root)
    source_dir = root / 'etc/apt/sources.list.d'
    source = source_dir / 'ubuntu.sources'
    source.write_text(RUNNER_SOURCES[0])
    main = root / 'etc/apt/sources.list'
    main.write_text(RUNNER_SOURCES[1])
    snapshots = {p: p.read_bytes() for p in (mirrors, source, main)}
    original_run = kvm.apt.run
    observed = []

    def inspect(args, timeout=None):
        if args[0] == 'apt-get':
            parts = Path(next(a.split('=', 1)[1] for a in args if a.startswith('Dir::Etc::sourceparts=')))
            observed.append(parts.parent)
            assert (parts / 'ubuntu.sources').read_text() == RUNNER_SOURCES[0].replace(
                kvm.RUNNER_MIRROR, kvm.NOBLE_ARCHIVE)
            assert (parts.parent / 'sources.list').read_text() == RUNNER_SOURCES[1].replace(
                kvm.RUNNER_MIRROR, kvm.NOBLE_ARCHIVE)
            assert all(p.read_bytes() == data for p, data in snapshots.items())
            # Stop before acquisition; the source plumbing is the subject here.
            raise subprocess.CalledProcessError(100, args, 'signature refusal fixture')
        return original_run(args, timeout)

    monkeypatch.setattr(kvm.apt, 'run', inspect)
    with pytest.raises(subprocess.CalledProcessError):
        kvm.install(root)
    assert observed and not observed[0].exists()
    assert all(p.read_bytes() == data for p, data in snapshots.items())


def test_unknown_mirror_fails_before_apt(fake_runner):
    root, calls, _ = fake_runner
    write_mirrors(root, RUNNER_MIRRORS + 'https://evil.example/ubuntu\n')
    (root / 'etc/apt/sources.list.d/ubuntu.sources').write_text(RUNNER_SOURCES[0])
    with pytest.raises(ValueError):
        kvm.install(root)
    assert calls == [(['dpkg', '--print-architecture'], None)]
