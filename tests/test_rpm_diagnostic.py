"""Offline diagnostic boundary tests: no Docker, DNS, or native transactions."""
import errno
import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'scripts/diagnostics'


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load diagnostic module {name!r} from {HERE}")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


proxy = module('rpm_proxy')
runner = module('run_rpm_rehearsal')
workload = module('rpm_workload')


@pytest.mark.parametrize('authority', ['repo.tunaos.org:443', 'ghcr.io:80', 'GHCR.IO:443',
    'ghcr.io.:443', 'user:SECRET@ghcr.io:443', '127.0.0.1:443', 'ghcr%2eio:443',
    'mirrors.fedoraproject.org:443', 'download.fedoraproject.org:443', 'fedoraproject.org:443',
    'dl.fedoraproject.org.evil.example:443', 'dl.fedoraproject.org:80'])
def test_exact_proxy_allowlist(authority):
    with pytest.raises(ValueError):
        proxy.authority(authority)


@pytest.mark.parametrize('address', ['127.0.0.1', '10.1.2.3', '169.254.169.254', '224.0.0.1', 'ff02::1', '0.0.0.0'])
def test_nonpublic_addresses(address):
    assert not proxy.public_address(address)


def test_credentials_not_logged(capsys):
    handler = object.__new__(proxy.Handler)
    handler.path = 'user:SYNTHETIC_SECRET@repo.tunaos.org:443'
    statuses = []
    handler.reply = statuses.append
    handler.do_CONNECT()
    assert statuses == [403]
    output = capsys.readouterr().out
    assert 'SYNTHETIC_SECRET' not in output
    assert json.loads(output)['host'] == '<invalid-authority>'


def test_dns_requires_all_public_ipv4(monkeypatch):
    def lookup(*_args, **kwargs):
        assert kwargs['family'] == socket.AF_INET
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('10.1.2.3', 443))]
    monkeypatch.setattr(proxy.socket, 'getaddrinfo', lookup)
    with pytest.raises(ValueError, match='non-public'):
        proxy.addresses('ghcr.io')


@pytest.mark.parametrize('url', ['http://github.com/a', 'https://github.com.evil/a',
    'https://user:SECRET@github.com/a', 'https://repo.tunaos.org/a', 'https://github.com:443/a'])
def test_prefetch_redirect_failclosed(url):
    with pytest.raises(ValueError):
        runner.check_download_url(url)


def test_plan_actual_scope():
    value = runner.plan()
    assert len(value['packages']) == 29
    assert 'gnome50-el10-compat' in value['packages']
    assert value['production_eligible'] is False
    assert '0734d0e81a7aac30' in value['reference']
    assert 'publish-oci-candidate.yml@refs/heads/main' in value['identity']


def test_internal_requires_host_isolated_gateway():
    network = {'Internal': True, 'EnableIPv6': False, 'Driver': 'bridge',
               'IPAM': {'Config': [{'Subnet': runner.INTERNAL_SUBNET}]}, 'Options': {}}
    with pytest.raises(ValueError):
        runner.internal_address(network)
    network['Options']['com.docker.network.bridge.gateway_mode_ipv4'] = 'isolated'
    assert runner.internal_address(network) == '172.30.0.2'
    network['EnableIPv6'] = True
    with pytest.raises(ValueError):
        runner.internal_address(network)
    network['EnableIPv6'] = False
    network['IPAM']['Config'][0]['Subnet'] = '172.30.0.0/24'  # auto-allocated, --ip would fail
    with pytest.raises(ValueError, match='configured subnet'):
        runner.internal_address(network)


def test_proxy_inspection():
    details = {'NetworkSettings': {'Networks': {'internal': {}, 'egress': {}}},
               'Config': {'User': '65534:65534'}, 'HostConfig': {'Privileged': False,
               'ReadonlyRootfs': True, 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true']},
               'Mounts': [{'Destination': '/input', 'Type': 'bind', 'RW': False}]}
    runner.verify_proxy_inspect(details, 'internal', 'egress')
    details['HostConfig']['PortBindings'] = {'3128/tcp': [{}]}
    with pytest.raises(ValueError):
        runner.verify_proxy_inspect(details, 'internal', 'egress')


def test_workload_mounts_require_readonly_input_and_writable_output():
    details = {'NetworkSettings': {'Networks': {'internal': {}}},
               'HostConfig': {'Privileged': False, 'NetworkMode': 'internal', 'Dns': ['127.0.0.1'],
               'SecurityOpt': ['no-new-privileges:true'], 'CapDrop': ['NET_ADMIN', 'NET_RAW']},
               'Mounts': [{'Destination': '/output', 'Type': 'bind', 'RW': True},
                          {'Destination': '/input', 'Type': 'bind', 'RW': False},
                          {'Destination': '/run', 'Type': 'tmpfs', 'RW': True}]}
    runner.verify_workload_inspect(details, 'internal')
    details['Mounts'].append({'Destination': '/host', 'Type': 'bind', 'RW': True})
    with pytest.raises(ValueError, match='unexpected workload bind mounts'):
        runner.verify_workload_inspect(details, 'internal')
    details['Mounts'][-1] = {'Destination': '/var/cache', 'Type': 'volume', 'RW': True}
    with pytest.raises(ValueError, match='unexpected volume mount'):
        runner.verify_workload_inspect(details, 'internal')


def test_workload_accepts_docker_normalized_capability_names():
    details = {'NetworkSettings': {'Networks': {'internal': {}}},
               'HostConfig': {'Privileged': False, 'NetworkMode': 'internal', 'Dns': ['127.0.0.1'],
               'SecurityOpt': ['no-new-privileges:true'], 'CapDrop': ['CAP_NET_ADMIN', 'CAP_NET_RAW']},
               'Mounts': [{'Destination': '/output', 'Type': 'bind', 'RW': True},
                          {'Destination': '/input', 'Type': 'bind', 'RW': False},
                          {'Destination': '/run', 'Type': 'tmpfs', 'RW': True}]}
    runner.verify_workload_inspect(details, 'internal')
    for drop in (['CAP_NET_RAW'], ['CAP_NET_ADMIN'], []):
        details['HostConfig']['CapDrop'] = drop
        with pytest.raises(ValueError, match='reviewed boundary'):
            runner.verify_workload_inspect(details, 'internal')
    details['HostConfig']['CapDrop'] = ['CAP_NET_ADMIN', 'CAP_NET_RAW']
    details['HostConfig']['CapAdd'] = ['CAP_NET_ADMIN']
    with pytest.raises(ValueError, match='reviewed boundary'):
        runner.verify_workload_inspect(details, 'internal')


def test_cleanup_continues_after_timeout(monkeypatch, tmp_path):
    calls = []
    def run(*args, **_kwargs):
        calls.append(args)
        if args[1] == 'logs':
            raise subprocess.TimeoutExpired(args, 30)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(runner, 'run', run)
    assert runner.cleanup(tmp_path, ['proxy', 'workload'], ['internal', 'egress']) is False
    assert ('docker', 'rm', '--force', 'workload') in calls
    assert ('docker', 'network', 'rm', 'internal') in calls
    assert len(json.loads((tmp_path / 'cleanup.json').read_text())) == 6


def test_evidence_write_failure_does_not_stop_removals(monkeypatch, tmp_path):
    calls = []
    def run(*args, output_path=None, **_kwargs):
        calls.append(args)
        if output_path is not None:
            output_path.write_text('log')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    real_write = Path.write_text
    def full_disk(self, *args, **kwargs):
        if self.name == 'cleanup.json':
            raise OSError(errno.ENOSPC, 'No space left on device')
        return real_write(self, *args, **kwargs)
    monkeypatch.setattr(runner, 'run', run)
    monkeypatch.setattr(Path, 'write_text', full_disk)
    assert runner.cleanup(tmp_path, ['proxy', 'workload'], ['internal', 'egress']) is False
    for removal in (('docker', 'rm', '--force', 'workload'), ('docker', 'rm', '--force', 'proxy'),
                    ('docker', 'network', 'rm', 'egress'), ('docker', 'network', 'rm', 'internal')):
        assert removal in calls


def test_log_and_removal_output_write_failures_do_not_stop_removals(monkeypatch, tmp_path):
    calls = []
    def run(*args, **_kwargs):
        calls.append(args)
        raise OSError(errno.ENOSPC, 'No space left on device')
    monkeypatch.setattr(runner, 'run', run)
    assert runner.cleanup(tmp_path, ['proxy', 'workload'], ['internal']) is False
    assert len(calls) == 5


def test_controls_fail_on_generic_proxy_error(monkeypatch):
    monkeypatch.setattr(workload, 'tunnel', lambda *_: (502, {}))
    with pytest.raises(ValueError, match='policy denial'):
        workload.controls('172.30.0.2', {'denied_controls': ['repo.tunaos.org']})


def test_controls_fail_on_direct_connection(monkeypatch):
    def tunnel(_proxy, host):
        return (403, {}) if host == 'repo.tunaos.org' else (200, {'x-diagnostic-upstream-ip': '1.1.1.1'})
    monkeypatch.setattr(workload, 'tunnel', tunnel)
    monkeypatch.setattr(workload.socket, 'create_connection', lambda *_a, **_k: SimpleNamespace(close=lambda: None))
    events = []
    with pytest.raises(ValueError, match='direct egress bypassed'):
        workload.controls('172.30.0.2', {'denied_controls': ['repo.tunaos.org']}, events.append)
    assert events[-1]['blocked'] is False


def test_proxy_evidence_requires_denials(monkeypatch):
    monkeypatch.setitem(sys.modules, 'rpm_proxy', proxy)
    log = json.dumps({'decision': 'allow', 'host': 'ghcr.io'})
    with pytest.raises(ValueError, match='corroborate'):
        runner.summarize_proxy(log, {'proxy_denials': ['repo.tunaos.org'], 'direct_denials': []})



def strings(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from strings(key)
            yield from strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from strings(item)
    elif isinstance(node, str):
        yield node


def test_workflow_manual_readonly_bounded():
    document = yaml.safe_load((ROOT / '.github/workflows/diagnostic-oci-rpm-consumer.yml').read_text())
    assert set(document.get(True) or document['on']) == {'workflow_dispatch'}  # PyYAML reads 'on' as True
    assert document['permissions'] == {'contents': 'read', 'packages': 'read'}
    job = document['jobs']['diagnostic']
    assert job['timeout-minutes'] == 120
    checkout = [s for s in job['steps'] if str(s.get('uses', '')).startswith('actions/checkout@')]
    assert [s['with']['persist-credentials'] for s in checkout] == [False]
    assert not [text for text in strings(document) if 'secrets.' in text]


def test_every_docker_command_pins_local_socket(monkeypatch):
    calls = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda args, **kwargs: calls.append((args, kwargs)))
    runner.run('docker', 'info')
    assert calls[0][0] == ('docker', '--host', 'unix:///var/run/docker.sock', 'info')


def test_long_command_output_streams_to_evidence_file(tmp_path):
    evidence = tmp_path / 'command.log'
    result = runner.run(
        sys.executable,
        '-c',
        "import sys; sys.stdout.write('out'); sys.stderr.write('err')",
        output_path=evidence,
    )
    assert result.returncode == 0
    assert result.stdout is None
    assert evidence.read_text() == 'outerr'


def test_successful_controls_keep_concrete_failure_evidence(monkeypatch):
    def tunnel(_proxy, host):
        if host in {'repo.tunaos.org', '1.1.1.1'}:
            return 403, {}
        return 200, {'x-diagnostic-upstream-ip': '1.1.1.1'}
    def blocked(*_args, **_kwargs):
        raise OSError(101, 'network unreachable')
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def read(self, _size):
            return b'<repomd/>'
    monkeypatch.setattr(workload, 'tunnel', tunnel)
    monkeypatch.setattr(workload.socket, 'create_connection', blocked)
    monkeypatch.setattr(workload.urllib.request, 'build_opener', lambda *_args: SimpleNamespace(open=lambda *_a, **_k: Response()))
    events = []
    result = workload.controls('172.30.0.2', {'denied_controls': ['repo.tunaos.org']}, events.append)
    assert result['passed']
    assert result['positive_hosts'] == ['mirror.stream.centos.org', 'dl.fedoraproject.org', 'ghcr.io']
    assert all(event['errno'] == 101 and 'seconds' in event for event in events if event['control'] == 'direct-deny')


def test_control_failure_precedes_native_mutation(monkeypatch, tmp_path):
    input_dir, output, work = tmp_path / 'input', tmp_path / 'output', tmp_path / 'work'
    input_dir.mkdir()
    output.mkdir()
    (input_dir / 'config.json').write_text('{}')
    (input_dir / 'hashes.json').write_text('{}')
    monkeypatch.setattr(workload, 'INPUT', input_dir)
    monkeypatch.setattr(workload, 'OUTPUT', output)
    monkeypatch.setattr(workload, 'WORK', work)
    monkeypatch.setattr(workload.os, 'environ', {})
    def deny(*_args):
        raise ValueError('preflight denied')
    monkeypatch.setattr(workload, 'controls', deny)
    monkeypatch.setattr(workload, 'prepare_fixture', lambda *_: pytest.fail('native config mutation before controls'))
    monkeypatch.setattr(workload.subprocess, 'run', lambda *_a, **_k: pytest.fail('native command before controls'))
    with pytest.raises(ValueError, match='preflight denied'):
        workload.execute('172.30.0.2')
    assert (output / 'control-events.jsonl').exists()


def fake_dnf(tmp_path, log_dir):
    """Reproduces the measured centos-bootc behaviour: version on stdout, but
    exit 1 with the hawkey.log warning when /var/log is absent."""
    script = tmp_path / 'dnf'
    script.write_text(f'#!/bin/sh\necho 4.20.0\n[ -d "{log_dir}" ] || {{ echo "Failed to open log file: {log_dir}/hawkey.log" >&2; exit 1; }}\n')
    script.chmod(0o755)
    return str(script)


def test_checked_fails_closed_and_keeps_bounded_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(workload, 'OUTPUT', tmp_path)
    command = fake_dnf(tmp_path, tmp_path / 'absent')
    with pytest.raises(ValueError, match='hawkey.log'):
        workload.checked([command, '--version'])
    record = json.loads((tmp_path / 'command-failures.log').read_text())
    assert record['returncode'] == 1 and 'hawkey.log' in record['stderr_tail']
    assert len(record['stderr_tail']) <= 2000
    present = tmp_path / 'present'
    present.mkdir()
    assert workload.checked([fake_dnf(tmp_path, present), '--version']).stdout.startswith('4.')


def test_missing_system_log_is_created_so_dnf_exits_zero(tmp_path, monkeypatch):
    log_dir = tmp_path / 'var-log'
    monkeypatch.setattr(workload, 'OUTPUT', tmp_path)
    monkeypatch.setattr(workload, 'SYSTEM_LOG', log_dir)
    command = fake_dnf(tmp_path, log_dir)
    with pytest.raises(ValueError):
        workload.checked([command, '--version'])
    workload.ensure_system_log()
    assert workload.checked([command, '--version']).stdout.startswith('4.')


def test_proxy_admits_exactly_the_epel_host():
    assert proxy.authority('dl.fedoraproject.org:443') == 'dl.fedoraproject.org'


def test_sibling_fedora_host_is_a_committed_negative_control():
    config = json.loads((ROOT / 'scripts/diagnostics/rpm_rehearsal.json').read_text())
    assert 'mirrors.fedoraproject.org' in config['denied_controls']
    assert 'mirrors.fedoraproject.org' not in proxy.ALLOWED


def test_committed_epel_entry_is_admitted_by_plan():
    value = runner.plan()
    assert value['epel']['key_sha256'] == 'de390fc168eae5ab2852e9e93d34a0b9ddf05cf9ce90ee28d97de26a4b1f6b93'
    assert value['epel']['priority'] > value['priority']


def epel_config(**changes):
    config = json.loads((ROOT / 'scripts/diagnostics/rpm_rehearsal.json').read_text())
    config['epel'].update(changes)
    return config


@pytest.mark.parametrize('changes', [
    {'baseurl': 'http://dl.fedoraproject.org/pub/epel/10/Everything/x86_64/'},
    {'baseurl': 'https://mirrors.fedoraproject.org/pub/epel/10/Everything/x86_64/'},
    {'baseurl': 'https://dl.fedoraproject.org.evil.example/pub/epel/10/Everything/x86_64/'},
    {'baseurl': 'https://dl.fedoraproject.org/pub/epel/10/Everything/x86_64/?x=1'},
    {'baseurl': 'https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/'},
    {'baseurl': 'https://user:SECRET@dl.fedoraproject.org/pub/epel/10/Everything/x86_64/'},
    {'key_url': 'http://dl.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-10'},
    {'key_url': 'https://github.com/pub/epel/RPM-GPG-KEY-EPEL-10'},
    {'key_sha256': 'de390fc1'},
    {'key_sha256': 'DE390FC168EAE5AB2852E9E93D34A0B9DDF05CF9CE90EE28D97DE26A4B1F6B93'},
    {'host': 'mirrors.fedoraproject.org'},
    {'id': 'epel-other'},
    {'priority': 1},
    {'priority': 0},
    {'priority': 100},
    {'extra': 'x'},
])
def test_epel_entry_rejects_unreviewed_values(changes):
    with pytest.raises(ValueError, match='EPEL entry'):
        runner.check_epel(epel_config(**changes))


def test_epel_key_is_fetched_by_hash_from_the_exact_host():
    runner.check_download_url('https://dl.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-10')
    for url in ('http://dl.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-10',
                'https://mirrors.fedoraproject.org/x', 'https://fedoraproject.org/x'):
        with pytest.raises(ValueError):
            runner.check_download_url(url)


def test_epel_repo_is_added_after_bootstrap_and_passes_the_consumer_check(tmp_path):
    consumer = importlib.util.spec_from_file_location('consumer', ROOT / 'scripts/install-oci-rpm-repository.py')
    consumer_module = importlib.util.module_from_spec(consumer)
    consumer.loader.exec_module(consumer_module)
    config = json.loads((ROOT / 'scripts/diagnostics/rpm_rehearsal.json').read_text())
    workload.add_epel(config, tmp_path)
    text = (tmp_path / 'epel.repo').read_text()
    assert 'gpgcheck=1\n' in text and 'repo_gpgcheck=0\n' in text and 'priority=99\n' in text
    key = tmp_path / 'epel.gpg'  # the workload mounts the hashed key at /input/epel.gpg
    key.write_text('key')
    (tmp_path / 'epel.repo').write_text(text.replace('file:///input/epel.gpg', key.as_uri()))
    ((name, _, keys),) = consumer_module.upstream_configs(tmp_path)
    assert name == 'epel.repo' and list(keys) == [key.as_uri()]
    assert 'file:///input/epel.gpg' in text
    assert 'epel.gpg' in (HERE / 'run_rpm_rehearsal.py').read_text()  # key is part of hashed inputs
