"""Offline diagnostic boundary tests: no Docker, DNS, or native transactions."""
import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'scripts/diagnostics'


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


proxy = module('rpm_proxy')
runner = module('run_rpm_rehearsal')
workload = module('rpm_workload')


@pytest.mark.parametrize('authority', ['repo.tunaos.org:443', 'ghcr.io:80', 'GHCR.IO:443',
    'ghcr.io.:443', 'user:SECRET@ghcr.io:443', '127.0.0.1:443', 'ghcr%2eio:443'])
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
               'IPAM': {'Config': [{'Subnet': '172.30.0.0/24'}]}, 'Options': {}}
    with pytest.raises(ValueError):
        runner.internal_address(network)
    network['Options']['com.docker.network.bridge.gateway_mode_ipv4'] = 'isolated'
    assert runner.internal_address(network) == '172.30.0.2'
    network['EnableIPv6'] = True
    with pytest.raises(ValueError):
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


def test_workflow_manual_readonly_bounded():
    data = (ROOT / '.github/workflows/diagnostic-oci-rpm-consumer.yml').read_text()
    assert 'workflow_dispatch:' in data and 'timeout-minutes: 120' in data
    assert 'persist-credentials: false' in data
    assert 'write' not in data and 'secrets.' not in data
    assert 'pull_request:' not in data and 'push:' not in data


def test_every_docker_command_pins_local_socket(monkeypatch):
    calls = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda args, **kwargs: calls.append((args, kwargs)))
    runner.run('docker', 'info')
    assert calls[0][0] == ('docker', '--host', 'unix:///var/run/docker.sock', 'info')


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
    assert result['positive_hosts'] == ['mirror.stream.centos.org', 'ghcr.io']
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
