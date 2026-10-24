#!/usr/bin/env python3
"""Opt-in build-only DNF consumer; no production feed or image pin defaults.

Requires the explicitly supplied, checksum-pinned producer transport tool.
Run inside a disposable image build RUN, never on an installed workstation.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

# tuna-os/tunaos-packages merged source 8f57b6376c0e7ec330a9bf1b08b5179c7288a299.
# Supply the reviewed file explicitly; no implicit checkout or download.
# The producer pins ORAS 1.3.4 and verifies cosign
# identity before pulling/extracting the immutable, scope-labelled repository.
TRANSPORT_SHA256 = '7e37d1ff61153d5419cdfca54ea6f9a0256c65cb53972da9f6235c2081ccfb32'
REF = re.compile(r'ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}\Z')
IDENTITY = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/'
                      r'\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml@refs/heads/[A-Za-z0-9_./-]+\Z')
CONTROLLED = re.compile(r'(?:repo|download)\.tunaos\.org|(?:[a-z0-9-]+\.)?r2\.cloudflarestorage\.com|[a-z0-9-]+\.r2\.dev', re.IGNORECASE)


def checked_file(path: Path, expected: str) -> bytes:
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('expected a reviewed SHA-256 checksum')
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'required regular local file is absent: {path}')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'local file checksum mismatch: {path}')
    return data


def reject_r2(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'repository config must be a regular file: {path}')
    data = path.read_bytes()
    if CONTROLLED.search(data.decode('utf-8')):
        raise ValueError(f'controlled R2 URL remains in repository config: {path}')
    return data


def config_text(path: Path) -> str:
    text = reject_r2(path).decode('utf-8')
    if '$' in text or '%' in text or re.search(r'^\s*(?:include|reposdir|varsdir)\s*=', text, re.MULTILINE | re.IGNORECASE):
        raise ValueError(f'variable or alternate config source is not admitted: {path}')
    return text


def check_runtime_configs(root: Path) -> None:
    """Reject literal R2 and indirect RPM configuration sources, fail closed."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError('runtime config root must exist and not be a symlink')
    paths = [root / 'dnf/dnf.conf', root / 'yum.conf']
    for relative in ('yum.repos.d', 'dnf/repos.d', 'dnf/vars', 'yum/vars'):
        directory = root / relative
        if directory.is_symlink():
            raise ValueError(f'runtime repository directory is a symlink: {directory}')
        paths.extend(directory.glob('*'))
    for path in paths:
        if path.exists() or path.is_symlink():
            config_text(path)


def upstream_configs(directory: Path) -> list[tuple[str, bytes, dict[str, bytes]]]:
    allowed = {'name', 'baseurl', 'enabled', 'gpgcheck', 'repo_gpgcheck', 'gpgkey',
               'priority', 'metadata_expire', 'sslverify', 'skip_if_unavailable'}
    seen = {'main', 'tunaos-oci', 'DEFAULT'}
    result = []
    for path in sorted(directory.glob('*.repo')):
        text = config_text(path)
        keys = {}
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_string(text)
        if parser.defaults() or not parser.sections():
            raise ValueError('upstream config needs explicit repository sections, not defaults')
        for name in parser.sections():
            values = parser[name]
            if name in seen or not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
                raise ValueError('duplicate, reserved or invalid upstream repository ID')
            seen.add(name)
            if set(values) - allowed:
                raise ValueError('unsupported upstream repository setting')
            if any(values.get(k) != '1' for k in ('enabled', 'gpgcheck', 'repo_gpgcheck')):
                raise ValueError('upstream repositories must enable package and metadata signatures')
            if values.get('sslverify', '1') != '1':
                raise ValueError('upstream TLS verification cannot be disabled')
            for key in ('baseurl', 'gpgkey'):
                url = values.get(key, '')
                parsed = urlsplit(url)
                if ('%' in url or any(c.isspace() for c in url) or parsed.username or parsed.password
                        or parsed.query or parsed.fragment):
                    raise ValueError('upstream URL must be static and credential-free')
                if key == 'gpgkey':
                    if parsed.scheme != 'file' or parsed.netloc or not parsed.path.startswith('/'):
                        raise ValueError('upstream signing key must be an absolute local file')
                    keys[url] = reject_r2(Path(parsed.path))
                elif (parsed.scheme != 'https' or not parsed.hostname
                      or not re.fullmatch(r'[a-zA-Z0-9.-]+', parsed.hostname)
                      or parsed.netloc != parsed.hostname):
                    raise ValueError('upstream baseurl must be one explicit HTTPS URL')
        result.append((path.name, text.encode(), keys))
    return result


def verify_native(repository: Path, root: Path, key: Path, architecture: str) -> None:
    """Do not trust keys already imported into the image's RPM or GPG databases."""
    gpg, rpm = root / 'gpg', root / 'rpmdb'
    gpg.mkdir(mode=0o700)
    rpm.mkdir(mode=0o700)
    run = lambda command: subprocess.run(command, check=True, capture_output=True, text=True,
                                         env={**os.environ, 'LC_ALL': 'C'})
    metadata = repository / 'repodata/repomd.xml'
    signature = repository / 'repodata/repomd.xml.asc'
    if not signature.is_file() or not signature.stat().st_size:
        raise ValueError('native repository metadata signature is missing')
    run(['gpg', '--batch', '--homedir', str(gpg), '--import', str(key)])
    run(['gpg', '--batch', '--homedir', str(gpg), '--verify', str(signature), str(metadata)])
    run(['rpm', '--dbpath', str(rpm), '--initdb'])
    run(['rpm', '--dbpath', str(rpm), '--import', str(key)])
    packages = list(repository.rglob('*.rpm'))
    if not packages:
        raise ValueError('native repository contains no RPMs')
    for package in packages:
        signature = run(['rpm', '--dbpath', str(rpm), '--checksig', str(package)]).stdout
        if not signature.rstrip().endswith('signatures OK'):
            raise ValueError('RPM does not have a valid reviewed-key signature')
        arch = run(['rpm', '--dbpath', str(rpm), '-qp', '--nosignature',
                    '--qf', '%{ARCH}', str(package)]).stdout
        if arch not in (architecture, 'noarch'):
            raise ValueError('native RPM architecture mismatch')


def install(args) -> dict:
    # All validation precedes transport/network or package-manager execution.
    check_runtime_configs(args.runtime_config_root)
    tool = checked_file(args.transport, TRANSPORT_SHA256)
    key = checked_file(args.key, args.key_sha256)
    if not REF.fullmatch(args.reference) or not IDENTITY.fullmatch(args.identity):
        raise ValueError('immutable GHCR reference and exact workflow signer identity required')
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,95}', args.target):
        raise ValueError('invalid native repository target')
    if args.architecture not in ('x86_64', 'aarch64'):
        raise ValueError('unsupported native architecture')
    if not 1 <= args.priority <= 99:
        raise ValueError('repository priority must be between 1 and 99')
    if (args.packages.is_symlink() or not args.packages.is_file()
            or args.packages.stat().st_size > 64 * 1024):
        raise ValueError('package inventory must be a bounded regular, non-symlink file')
    packages = args.packages.read_text().splitlines()
    if not packages or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.:~-]*', p) for p in packages):
        raise ValueError('package inventory must contain one explicit package name per line')
    if args.upstream_repos.is_symlink() or not args.upstream_repos.is_dir():
        raise ValueError('upstream repository directory must exist and not be a symlink')
    upstream = upstream_configs(args.upstream_repos)
    if any(name == 'tunaos-oci.repo' for name, _, _ in upstream):
        raise ValueError('reserved repository config name: tunaos-oci.repo')
    # DNF must not load a plugin or a persistent config that quietly reintroduces
    # HTTP feeds. Upstream distro repositories are explicit local config inputs.
    with tempfile.TemporaryDirectory(prefix='tunaos-oci-rpm-') as work:
        root = Path(work)
        repos = root / 'repos'
        repos.mkdir()
        (root / 'vars').mkdir()
        config = root / 'dnf.conf'
        config.write_text('[main]\ngpgcheck=1\nplugins=0\n')
        dnf = ['dnf', '--config', str(config), '--noplugins',
               f'--setopt=reposdir={repos}', f'--setopt=varsdir={root / "vars"}',
               f'--setopt=cachedir={root / "cache"}', f'--setopt=persistdir={root / "persist"}',
               f'--setopt=logdir={root / "log"}']
        environment = {k: v for k, v in os.environ.items() if not k.startswith('DNF_VAR_')}
        version = subprocess.run([*dnf, '--version'], check=True, capture_output=True,
                                 text=True, env=environment).stdout
        if not re.match(r'^4\.[0-9]+(?:\.|\s)', version):
            raise ValueError('only DNF4 is admitted; DNF5 override isolation is not qualified')
        transport = root / 'transport.py'
        transport.write_bytes(tool)
        repository = root / 'repository'
        subprocess.run([sys.executable, '-I', str(transport), 'pull', '--format', 'rpm',
                        '--target', args.target, '--architecture', args.architecture,
                        '--reference', args.reference, '--identity', args.identity,
                        '--destination', str(repository)], check=True, stdout=sys.stderr)
        if not (repository / 'repodata/repomd.xml').is_file():
            raise ValueError('verified snapshot has no native RPM repository metadata')
        public_key = root / 'public.gpg'
        public_key.write_bytes(key)
        verify_native(repository, root, public_key, args.architecture)
        for name, data, keys in upstream:
            parser = configparser.ConfigParser(interpolation=None, strict=True)
            parser.read_string(data.decode('utf-8'))
            for section in parser.sections():
                key_data = keys[parser[section]['gpgkey']]
                snapshot = root / ('upstream-key-' + hashlib.sha256(key_data).hexdigest())
                snapshot.write_bytes(key_data)
                parser[section]['gpgkey'] = snapshot.as_uri()
            output = io.StringIO()
            parser.write(output)
            (repos / name).write_text(output.getvalue())
        (repos / 'tunaos-oci.repo').write_text(
            '[tunaos-oci]\nname=Verified build-only OCI repository\n'
            f'baseurl={repository.as_uri()}\ngpgkey={public_key.as_uri()}\n'
            'enabled=1\ngpgcheck=1\nrepo_gpgcheck=1\nskip_if_unavailable=False\n'
            f'priority={args.priority}\n')
        subprocess.run([*dnf, '-y', 'install', *packages], check=True,
                       stdout=sys.stderr, env=environment)
        inventory = subprocess.run(['rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n'],
                                   check=True, capture_output=True, text=True).stdout
    check_runtime_configs(args.runtime_config_root)
    # Context cleanup runs on success, download rejection and DNF failure. RPM DB
    # (including the imported public key) and native package inventory are kept.
    return {'reference': args.reference, 'target': args.target, 'architecture': args.architecture,
            'signer': args.identity, 'key_sha256': args.key_sha256, 'priority': args.priority,
            'transport_sha256': TRANSPORT_SHA256,
            'upstream_configs': {name: hashlib.sha256(data).hexdigest() for name, data, _ in upstream},
            'upstream_keys': {uri: hashlib.sha256(data).hexdigest()
                              for _, _, keys in upstream for uri, data in keys.items()},
            'requested_packages': packages, 'installed_rpms': sorted(inventory.splitlines())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('transport', 'key', 'packages', 'upstream-repos'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('key-sha256', 'reference', 'identity', 'target', 'architecture'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--priority', type=int, default=99)
    args = parser.parse_args()
    args.runtime_config_root = Path('/etc')
    try:
        print(json.dumps(install(args), sort_keys=True))
    except (ValueError, OSError, configparser.Error, subprocess.CalledProcessError) as error:
        print(f'OCI repository install refused: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
