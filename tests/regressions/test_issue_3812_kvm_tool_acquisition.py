"""tunaOS#3812: QEMU acquisition must not fail through the Azure archive.

Job 121823081846 built grouper but could not acquire the tools to boot it.
Falsification: behavioural — use Azure source fixtures and a stalled downloader;
assert official HTTPS in private sources and no installation after exhaustion.
"""

import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('kvm_tools', ROOT / 'scripts/setup-kvm-tools.py')
kvm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kvm)


@pytest.mark.parametrize('source', [
    'deb [arch=amd64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://azure.archive.ubuntu.com/ubuntu noble main universe\n',
    'Types: deb\nURIs: http://azure.archive.ubuntu.com/ubuntu/\nSuites: noble noble-updates noble-backports\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n',
    'deb https://azure.archive.ubuntu.com/ubuntu resolute main\n',
])
def test_only_official_uri_changes(source):
    expected = source.replace('http://azure.archive.ubuntu.com/ubuntu/', 'https://archive.ubuntu.com/ubuntu')
    expected = expected.replace('http://azure.archive.ubuntu.com/ubuntu', 'https://archive.ubuntu.com/ubuntu')
    expected = expected.replace('https://azure.archive.ubuntu.com/ubuntu', 'https://archive.ubuntu.com/ubuntu')
    assert kvm.source_text(source) == expected


@pytest.mark.parametrize('uri', ['http://azure.archive.ubuntu.com.evil/ubuntu',
                                'http://evil@azure.archive.ubuntu.com/ubuntu',
                                'http://azure.archive.ubuntu.com/ubuntu-other',
                                'https://packages.microsoft.com/ubuntu/24.04/prod',
                                'http://security.ubuntu.com/ubuntu'])
def test_other_sources_are_unchanged(uri):
    source = f'deb {uri} noble main\n'
    assert kvm.source_text(source) == source


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
        assert (source_dir / 'ubuntu.list').read_text() == 'deb https://archive.ubuntu.com/ubuntu noble main universe\n'
        assert (source_dir.parent / 'sources.list').read_text() == 'deb https://archive.ubuntu.com/ubuntu noble main universe\n'
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


def test_only_pr_tool_command_changes():
    path = '.github/workflows/reusable-build-image.yml'
    candidate = (ROOT / path).read_text()
    workflow = yaml.safe_load(candidate)
    steps = next(job['steps'] for job in workflow['jobs'].values()
                 if any(s.get('name') == 'Enable KVM for verification' for s in job.get('steps', [])))
    step = next(s for s in steps if s.get('name') == 'Enable KVM for verification')
    assert step['if'] == "github.event_name == 'pull_request' && contains(matrix.platform, 'amd64')"
    assert 'sudo python3 scripts/setup-kvm-tools.py' in step['run']
    assert 'MODE="0666"' in step['run']
    assert 'sudo udevadm control --reload-rules' in step['run']
    assert 'sudo udevadm trigger --name-match=kvm || true' in step['run']
    assert 'sudo apt-get install' not in step['run']
