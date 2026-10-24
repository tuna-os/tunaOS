#!/usr/bin/env python3
"""Explicit diagnostic only: plan is read-only; run creates disposable Docker resources."""
from __future__ import annotations

import argparse
import hashlib
import io
import ipaddress
import json
import os
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import tomllib
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def run(*args, timeout=120, check=True, output_path: Path | None = None):
    if args and args[0] == 'docker':
        args = ('docker', '--host', 'unix:///var/run/docker.sock', *args[1:])
    if output_path is not None:
        with output_path.open('xb') as stream:
            return subprocess.run(
                args, check=check, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout
            )
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=timeout)


def plan(root=ROOT) -> dict:
    config = json.loads((root / 'scripts/diagnostics/rpm_rehearsal.json').read_text())
    source = tomllib.loads((root / 'tunaos.toml').read_text())
    policy = source['desktops']['gnome']['packages']['el10']
    if hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != config['policy_sha256']:
        raise ValueError('EL10 desktop policy changed; review this diagnostic inventory again')
    base = source['variants']['skipjack']['base_image']
    if base.split('@')[1] != config['base'].split('@')[1]:
        raise ValueError('configured Skipjack base changed; review the immutable test cell')
    required = policy['required']
    if len(required) != 28 or len(set(required)) != 28:
        raise ValueError('expected the reviewed 28-name required inventory')
    return {**config, 'packages': [*required, 'gnome50-el10-compat'],
            'untested_full_desktop_policy': policy, 'production_eligible': False}


FETCH_HOSTS = frozenset({'raw.githubusercontent.com', 'www.centos.org', 'github.com',
                         'release-assets.githubusercontent.com', 'objects.githubusercontent.com'})


def check_download_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc not in FETCH_HOSTS:
        raise ValueError('public input URL or redirect host is not admitted')


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        check_download_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch(url: str, expected: str) -> bytes:
    check_download_url(url)
    started = time.monotonic()
    chunks, size = [], 0
    with urllib.request.build_opener(CheckedRedirect()).open(url, timeout=30) as response:
        check_download_url(response.url)
        while data := response.read(1024 * 1024):
            size += len(data)
            if size > 192 * 1024**2 or time.monotonic() - started > 180:
                raise ValueError('public input exceeds download bound')
            chunks.append(data)
    result = b''.join(chunks)
    if hashlib.sha256(result).hexdigest() != expected:
        raise ValueError(f'public input checksum mismatch: {url}')
    return result


def inputs(destination: Path, config: dict) -> None:
    destination.mkdir()
    (destination / 'bin').mkdir()
    raw = f'https://raw.githubusercontent.com/tuna-os/tunaos-packages/{config["producer_commit"]}'
    sources = {
        'transport.py': (f'{raw}/scripts/oras_distribution.py', config['transport_sha256']),
        'public.gpg': (f'{raw}/public.gpg', config['key_sha256']),
        'centos.gpg': ('https://www.centos.org/keys/RPM-GPG-KEY-CentOS-Official-SHA256', config['centos_key_sha256']),
        'bin/cosign': (f'https://github.com/sigstore/cosign/releases/download/v{config["cosign_version"]}/cosign-linux-amd64', config['cosign_sha256']),
    }
    for name, (url, checksum) in sources.items():
        (destination / name).write_bytes(fetch(url, checksum))
    archive = fetch(f'https://github.com/oras-project/oras/releases/download/v{config["oras_version"]}/oras_{config["oras_version"]}_linux_amd64.tar.gz', config['oras_archive_sha256'])
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        member = tar.getmember('oras')
        if not member.isfile() or member.size > 64 * 1024**2:
            raise ValueError('verified ORAS archive lacks a regular bounded binary')
        (destination / 'bin/oras').write_bytes(tar.extractfile(member).read())
    for path in (destination / 'bin').iterdir():
        path.chmod(0o755)
    shutil.copyfile(ROOT / 'scripts/install-oci-rpm-repository.py', destination / 'consumer.py')
    shutil.copyfile(HERE / 'rpm_workload.py', destination / 'workload.py')
    shutil.copyfile(HERE / 'rpm_proxy.py', destination / 'proxy.py')
    (destination / 'config.json').write_text(json.dumps(config, sort_keys=True))
    (destination / 'packages.txt').write_text('\n'.join(config['packages']) + '\n')
    hashes = {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in destination.rglob('*') if p.is_file()}
    (destination / 'hashes.json').write_text(json.dumps(hashes, sort_keys=True))


def internal_address(network: dict) -> str:
    if (not network['Internal'] or network.get('EnableIPv6') or network['Driver'] != 'bridge'
            or network.get('Options', {}).get('com.docker.network.bridge.gateway_mode_ipv4') != 'isolated'):
        raise ValueError('Docker did not create an IPv4-only internal bridge')
    subnets = network['IPAM']['Config']
    if len(subnets) != 1:
        raise ValueError('unexpected network IPAM layout')
    subnet = ipaddress.IPv4Network(subnets[0]['Subnet'])
    if not subnet.is_private or subnet.num_addresses < 8:
        raise ValueError('expected a private Docker network')
    address = subnet.network_address + 2
    if str(address) == subnets[0].get('Gateway'):
        raise ValueError('proxy address collides with gateway')
    return str(address)


def verify_workload_inspect(details: dict, internal: str) -> None:
    host = details['HostConfig']
    if (set(details['NetworkSettings']['Networks']) != {internal}
            or host['Privileged'] or host.get('PublishAllPorts') or host.get('PortBindings')
            or host.get('NetworkMode') != internal
            or host.get('Dns') != ['127.0.0.1']
            or 'no-new-privileges:true' not in host.get('SecurityOpt', [])
            or host.get('PidMode') == 'host' or host.get('IpcMode') == 'host'
            or set(host.get('CapAdd') or [])
            or not {'NET_ADMIN', 'NET_RAW'}.issubset(set(host.get('CapDrop') or []))):
        raise ValueError('workload Docker isolation does not match the reviewed boundary')
    mounts = details.get('Mounts', [])
    if ({m['Destination'] for m in mounts if m['Type'] == 'bind'} != {'/input', '/output'}
            or any(m['RW'] for m in mounts if m['Destination'] == '/input')
            or any(m['Type'] != 'bind' and not (m['Type'] == 'tmpfs' and m['Destination'] == '/run') for m in mounts)):
        raise ValueError('unexpected workload bind mounts')


def verify_proxy_inspect(details: dict, internal: str, egress: str) -> None:
    host = details['HostConfig']
    mounts = details.get('Mounts', [])
    if (set(details['NetworkSettings']['Networks']) != {internal, egress}
            or host['Privileged'] or host.get('PublishAllPorts') or host.get('PortBindings')
            or not host.get('ReadonlyRootfs') or host.get('CapAdd')
            or set(host.get('CapDrop') or []) != {'ALL'}
            or 'no-new-privileges:true' not in host.get('SecurityOpt', [])
            or details['Config'].get('User') != '65534:65534'
            or len(mounts) != 1 or mounts[0]['Destination'] != '/input'
            or mounts[0]['Type'] != 'bind' or mounts[0]['RW']):
        raise ValueError('proxy Docker isolation does not match the reviewed boundary')


def cleanup(output: Path, containers: list[str], networks: list[str]) -> bool:
    events = []
    for kind, names in (('container', containers), ('network', networks)):
        for name in reversed(names):
            commands = ([['docker', 'logs', name], ['docker', 'rm', '--force', name]]
                        if kind == 'container' else [['docker', 'network', 'rm', name]])
            for command in commands:
                event = {'command': command, 'ok': False}
                destination = output / (name + '-' + command[1] + '.txt')
                try:
                    if command[1] == 'logs':
                        result = run(
                            *command, timeout=30, check=False, output_path=destination
                        )
                    else:
                        result = run(*command, timeout=30, check=False)
                        destination.write_text(result.stdout + result.stderr)
                    event.update(ok=result.returncode == 0, returncode=result.returncode)
                except (OSError, subprocess.SubprocessError) as error:
                    event['error'] = type(error).__name__
                events.append(event)
                (output / 'cleanup.json').write_text(json.dumps(events, indent=2))
    return all(event['ok'] for event in events)


def summarize_proxy(log: str, controls: dict) -> dict:
    events = [json.loads(line) for line in log.splitlines() if line.strip()]
    allowed = [e for e in events if e.get('decision') == 'allow']
    denied = [e for e in events if e.get('decision') == 'deny']
    # Import a repository-local policy module, never a downloaded helper.
    import rpm_proxy
    if not allowed or any(e['host'] not in rpm_proxy.ALLOWED for e in allowed):
        raise ValueError('proxy evidence has an unadmitted allowed endpoint')
    required_denials = {*controls['proxy_denials'], *controls['direct_denials']}
    if not {host + ':443' for host in required_denials}.issubset({e['host'] for e in denied}):
        raise ValueError('proxy logs do not corroborate every negative control')
    return {'allowed_connections': len(allowed), 'denied_connections': len(denied),
            'tunnel_bytes': sum(e.get('bytes', 0) for e in events if e.get('decision') == 'closed'),
            'hosts': sorted({e['host'] for e in allowed})}


def execute(output: Path) -> None:
    config = plan()
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise ValueError('diagnostic requires the local runner Docker daemon')
    engine = json.loads(run('docker', 'info', '--format', '{{json .}}').stdout)
    major = re.match(r'([0-9]+)\.', engine.get('ServerVersion', ''))
    if (not major or int(major[1]) < 28 or engine.get('OSType') != 'linux'
            or any('rootless' in item for item in engine.get('SecurityOptions', []))):
        raise ValueError('diagnostic requires rootful Linux Docker28+ isolated bridge mode')
    # An actual run must use reviewed committed source, not this local draft.
    if run('git', '-C', str(ROOT), 'status', '--porcelain').stdout.strip():
        raise ValueError('run requires a clean reviewed consumer checkout')
    if output.exists() or output.is_symlink():
        raise ValueError('diagnostic output directory must be new')
    if shutil.disk_usage(output.parent).free < 16 * 1024**3:
        raise ValueError('diagnostic requires at least 16 GiB free scratch')
    output.mkdir()
    (output / 'docker-engine.json').write_text(json.dumps(engine, indent=2))
    (output / 'plan.json').write_text(json.dumps(config, indent=2))
    (output / 'consumer-source.txt').write_text(run('git', '-C', str(ROOT), 'rev-parse', 'HEAD').stdout)
    suffix = uuid.uuid4().hex[:12]
    internal, egress = f'rpm-diag-{suffix}-internal', f'rpm-diag-{suffix}-egress'
    proxy, workload = f'rpm-diag-{suffix}-proxy', f'rpm-diag-{suffix}-workload'
    networks, containers = [], []
    with tempfile.TemporaryDirectory(prefix='rpm-diagnostic-inputs-') as scratch:
        source = Path(scratch) / 'input'
        inputs(source, config)
        shutil.copyfile(source / 'hashes.json', output / 'input-hashes.json')
        run('docker', 'pull', '--platform', 'linux/amd64', config['base'], timeout=900)
        try:
            for name, flags in ((internal, ['--internal', '--opt', 'com.docker.network.bridge.gateway_mode_ipv4=isolated']), (egress, [])):
                networks.append(name)  # Reconcile uncertain create outcomes too.
                run('docker', 'network', 'create', '--driver', 'bridge', *flags, name)
            network = json.loads(run('docker', 'network', 'inspect', internal).stdout)[0]
            address = internal_address(network)
            (output / 'internal-network.json').write_text(json.dumps(network, indent=2))
            containers.append(proxy)
            run('docker', 'create', '--name', proxy, '--network', internal, '--ip', address,
                '--platform', 'linux/amd64', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--user', '65534:65534',
                '--memory', '128m', '--cpus', '0.5', '--pids-limit', '64',
                '--mount', f'type=bind,src={source},dst=/input,readonly',
                '--entrypoint', '/usr/bin/python3', config['base'], '-I', '/input/proxy.py', '--listen', address)
            run('docker', 'network', 'connect', egress, proxy)
            proxy_details = json.loads(run('docker', 'inspect', proxy).stdout)[0]
            verify_proxy_inspect(proxy_details, internal, egress)
            (output / 'proxy-inspection.json').write_text(json.dumps(proxy_details, indent=2))
            run('docker', 'start', proxy)
            for _attempt in range(30):
                log = run('docker', 'logs', proxy).stdout
                if any(json.loads(line).get('decision') == 'ready' for line in log.splitlines()):
                    break
                time.sleep(1)
            else:
                raise ValueError('proxy failed its bounded readiness check')
            containers.append(workload)
            run('docker', 'create', '--name', workload, '--network', internal,
                '--platform', 'linux/amd64', '--dns', '127.0.0.1',
                '--cap-drop', 'NET_ADMIN', '--cap-drop', 'NET_RAW',
                '--security-opt', 'no-new-privileges:true', '--memory', '5g', '--cpus', '2',
                '--pids-limit', '512', '--tmpfs', '/run:rw,size=1g',
                '--mount', f'type=bind,src={source},dst=/input,readonly',
                '--mount', f'type=bind,src={output.resolve()},dst=/output',
                '--entrypoint', '/usr/bin/python3', config['base'], '-I', '/input/workload.py', '--proxy', address)
            inspection = json.loads(run('docker', 'inspect', workload).stdout)[0]
            verify_workload_inspect(inspection, internal)
            (output / 'workload-inspection.json').write_text(json.dumps(inspection, indent=2))
            result = run(
                'docker', 'start', '--attach', workload, timeout=5400, check=False,
                output_path=output / 'workload-console.log',
            )
            terminal = json.loads(run('docker', 'inspect', workload).stdout)[0]
            if terminal['State']['Running'] or terminal['State']['ExitCode'] != 0:
                raise ValueError('native diagnostic did not complete successfully')
            control = json.loads((output / 'network-controls.json').read_text())
            if not control.get('passed'):
                raise ValueError('network controls did not pass')
            proxy_log = run('docker', 'logs', proxy).stdout
            summary = summarize_proxy(proxy_log, control)
            scope = json.loads((output / 'scope.json').read_text())
            if scope.get('production_eligible') is not False or not scope.get('native_install_passed'):
                raise ValueError('missing diagnostic-only scope receipt')
            (output / 'diagnostic-result.json').write_text(json.dumps({
                'state': 'native-passed-cleanup-pending', 'scope': config['scope'], 'production_eligible': False,
                'proxy': summary, 'reference': config['reference'],
            }, indent=2))
        finally:
            # Remove only UUID-named resources created by this invocation; never
            # prune images, change host firewall rules or clean unrelated networks.
            if not cleanup(output, containers, networks):
                (output / 'cleanup-failed.txt').write_text('Review cleanup.json; resource removal not confirmed.\n')
                (output / 'diagnostic-result.json').write_text(json.dumps({
                    'state': 'failed', 'reason': 'cleanup-unconfirmed', 'production_eligible': False,
                }, indent=2))
                raise RuntimeError('diagnostic cleanup was not fully confirmed')
            receipt = output / 'diagnostic-result.json'
            if receipt.exists():
                result = json.loads(receipt.read_text())
                result.update(state='passed', cleanup_complete=True)
                receipt.write_text(json.dumps(result, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'run'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'plan':
        print(json.dumps(plan(), indent=2))
        return 0
    if args.output is None:
        parser.error('run requires a new --output directory')
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda number, _frame: (_ for _ in ()).throw(SystemExit(128 + number)))
    execute(args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
