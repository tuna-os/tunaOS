#!/usr/bin/env python3
"""Disposable-container workload: controls precede every native transaction."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

INPUT = Path('/input')
OUTPUT = Path('/output')
WORK = Path('/run/rpm-diagnostic')


def tunnel(proxy: str, target: str) -> tuple[int, dict[str, str]]:
    with socket.create_connection((proxy, 3128), timeout=15) as connection:
        connection.sendall(f'CONNECT {target}:443 HTTP/1.1\r\nHost: {target}:443\r\n\r\n'.encode())
        response = connection.makefile('rb')
        status = response.readline(4096).decode('ascii').split()
        if len(status) < 2:
            raise ValueError('proxy did not return a status')
        headers = {}
        for _ in range(30):
            line = response.readline(4096).decode('ascii')
            if line == '\r\n':
                return int(status[1]), headers
            key, value = line.split(':', 1)
            headers[key.lower()] = value.strip()
    raise ValueError('invalid proxy response')


def controls(proxy: str, config: dict, record=lambda _event: None) -> dict:
    results = {'proxy_denials': [], 'direct_denials': [], 'positive_hosts': []}
    for host in config['denied_controls']:
        status, _ = tunnel(proxy, host)
        record({'control': 'proxy-deny', 'target': host, 'status': status})
        if status != 403:
            raise ValueError(f'negative control did not receive policy denial: {host} ({status})')
        results['proxy_denials'].append(host)
    for host in ('mirror.stream.centos.org', 'ghcr.io'):
        status, headers = tunnel(proxy, host)
        address = headers.get('x-diagnostic-upstream-ip', '')
        record({'control': 'proxy-positive', 'target': host, 'status': status, 'address': address})
        if status != 200 or not ipaddress.ip_address(address).is_global:
            raise ValueError(f'positive proxy control failed: {host}')
        # Probe the same public IP just proven reachable through the proxy. A
        # blocked unrelated address would not demonstrate proxy-only connectivity.
        started = time.monotonic()
        try:
            connection = socket.create_connection((address, 443), timeout=5)
        except OSError as error:
            record({'control': 'direct-deny', 'address': address, 'blocked': True,
                    'error': type(error).__name__, 'errno': error.errno,
                    'seconds': round(time.monotonic() - started, 3)})
        else:
            connection.close()
            record({'control': 'direct-deny', 'address': address, 'blocked': False})
            raise ValueError('direct egress bypassed the internal network')
        denied, _ = tunnel(proxy, address)
        record({'control': 'proxy-ip-deny', 'address': address, 'status': denied})
        if denied != 403:
            raise ValueError('proxy accepted a direct IP CONNECT')
        results['direct_denials'].append(address)
        results['positive_hosts'].append(host)
    handler = urllib.request.ProxyHandler({'https': f'http://{proxy}:3128'})
    with urllib.request.build_opener(handler).open(
            'https://mirror.stream.centos.org/10-stream/BaseOS/x86_64/os/repodata/repomd.xml',
            timeout=30) as response:
        if response.status != 200:
            raise ValueError('official metadata positive control failed')
        data = response.read(1024 * 1024)
        if not data or b'<repomd' not in data:
            raise ValueError('official metadata control returned no repository')
        results['positive_repomd_sha256'] = hashlib.sha256(data).hexdigest()
    results['passed'] = True
    return results


def prepare_fixture(config: dict) -> list[str]:
    # Only the disposable container's stock config is changed. Record it before
    # removing it; a published/deployed image is never an input to this script.
    saved = OUTPUT / 'stock-rpm-config'
    saved.mkdir()
    for directory in (Path('/etc/yum.repos.d'), Path('/etc/dnf/repos.d')):
        if directory.is_symlink():
            raise ValueError('unexpected symlinked stock repository directory')
        for path in directory.glob('*.repo'):
            if path.is_symlink():
                raise ValueError('unexpected symlinked stock repository config')
            shutil.copyfile(path, saved / (directory.name + '-' + path.name))
            path.unlink()
    for path in (Path('/etc/yum.conf'), Path('/etc/dnf/dnf.conf')):
        if path.exists():
            shutil.copyfile(path, saved / (path.parent.name + '-' + path.name))
        if path.exists() or path.is_symlink():
            path.unlink()
    Path('/etc/dnf').mkdir(exist_ok=True)
    Path('/etc/dnf/dnf.conf').write_text('[main]\ngpgcheck=1\nplugins=0\n')
    repos = WORK / 'repos'
    repos.mkdir()
    for name in config['official_repos']:
        (repos / f'{name}.repo').write_text(
            f'[{name.lower()}]\nname=Official CentOS {name}\n'
            f'baseurl=https://mirror.stream.centos.org/10-stream/{name}/x86_64/os/\n'
            'gpgkey=file:///input/centos.gpg\nenabled=1\ngpgcheck=1\nrepo_gpgcheck=1\n'
            'sslverify=1\nskip_if_unavailable=False\n')
    (WORK / 'vars').mkdir()
    settings = WORK / 'dnf.conf'
    settings.write_text('[main]\ngpgcheck=1\nplugins=0\n')
    return ['dnf', '--config', str(settings), '--noplugins',
            f'--setopt=reposdir={repos}', f'--setopt=varsdir={WORK / "vars"}',
            f'--setopt=cachedir={WORK / "cache"}', f'--setopt=persistdir={WORK / "persist"}',
            f'--setopt=logdir={WORK / "log"}']


def execute(proxy: str) -> None:
    config = json.loads((INPUT / 'config.json').read_text())
    for name, expected in json.loads((INPUT / 'hashes.json').read_text()).items():
        if hashlib.sha256((INPUT / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'input changed: {name}')
    if any(name in os.environ for name in ('GITHUB_TOKEN', 'GH_TOKEN', 'GPG_PRIVATE_KEY')):
        raise ValueError('credentials must not be passed into this diagnostic')
    WORK.mkdir()
    (WORK / 'home').mkdir()
    os.environ.clear()
    os.environ.update(PATH='/input/bin:/usr/sbin:/usr/bin:/sbin:/bin', HOME=str(WORK / 'home'),
                      LC_ALL='C', HTTPS_PROXY=f'http://{proxy}:3128', HTTP_PROXY=f'http://{proxy}:3128',
                      https_proxy=f'http://{proxy}:3128', http_proxy=f'http://{proxy}:3128',
                      NO_PROXY='', no_proxy='')
    (OUTPUT / 'network-before.txt').write_text(Path('/proc/net/dev').read_text())
    def record(event):
        with (OUTPUT / 'control-events.jsonl').open('a') as log:
            log.write(json.dumps(event, sort_keys=True) + '\n')
    try:
        result = controls(proxy, config, record)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        record({'control': 'failed', 'error': type(error).__name__})
        raise
    (OUTPUT / 'network-controls.json').write_text(json.dumps(result, sort_keys=True))
    # Nothing above this point executes RPM/DNF or changes repository settings.
    dnf = prepare_fixture(config)
    version = subprocess.run([*dnf, '--version'], check=True, capture_output=True, text=True).stdout
    if not version.startswith('4.'):
        raise ValueError('immutable base does not provide DNF4')
    arch = subprocess.run(['rpm', '--eval', '%{_arch}'], check=True,
                          capture_output=True, text=True).stdout.strip()
    if arch != 'x86_64':
        raise ValueError('immutable base is not native x86_64')
    with (OUTPUT / 'bootstrap.log').open('w') as log:
        subprocess.run([*dnf, '-y', 'install', 'python3', 'gnupg2'], check=True,
                       stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    (OUTPUT / 'baseline-rpms.txt').write_text(subprocess.run(
        ['rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n'],
        check=True, capture_output=True, text=True).stdout)
    with (OUTPUT / 'native-install.log').open('w') as log:
        completed = subprocess.run([
            sys.executable, '-I', '/input/consumer.py', '--transport', '/input/transport.py',
            '--reference', config['reference'], '--identity', config['identity'],
            '--target', config['target'], '--architecture', config['architecture'],
            '--key', '/input/public.gpg', '--key-sha256', config['key_sha256'],
            '--packages', '/input/packages.txt', '--upstream-repos', str(WORK / 'repos'),
            '--priority', str(config['priority'])], check=True, stdout=subprocess.PIPE,
            stderr=log, text=True, timeout=3600)
    receipt = json.loads(completed.stdout)
    if receipt['requested_packages'] != (INPUT / 'packages.txt').read_text().splitlines():
        raise ValueError('native request inventory changed')
    (OUTPUT / 'consumer-receipt.json').write_text(json.dumps(receipt, indent=2))
    # A tool success is not full desktop/boot qualification or permission to
    # publish. The parent runner also requires proxy logs and isolation controls.
    shutil.rmtree(WORK)
    if list(Path('/tmp').glob('tunaos-oci-rpm-*')):
        raise ValueError('consumer left a staged repository behind')
    (OUTPUT / 'network-after.txt').write_text(Path('/proc/net/dev').read_text())
    (OUTPUT / 'scope.json').write_text(json.dumps({
        'scope': config['scope'], 'production_eligible': False,
        'full_desktop_tested': False, 'boot_tested': False, 'native_install_passed': True,
    }, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', required=True)
    args = parser.parse_args()
    ipaddress.IPv4Address(args.proxy)
    try:
        execute(args.proxy)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Diagnostic refused: {type(error).__name__}: {error}', file=sys.stderr)
        sys.exit(1)
    finally:
        if OUTPUT.is_dir():
            (OUTPUT / 'network-after.txt').write_text(Path('/proc/net/dev').read_text())
