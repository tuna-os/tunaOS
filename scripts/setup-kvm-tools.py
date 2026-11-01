#!/usr/bin/env python3
"""Install only the PR verification tools; stacked on #3998's APT primitives."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

SPEC = importlib.util.spec_from_file_location('runner_apt', Path(__file__).with_name('setup-runner-podman.py'))
apt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apt)
PACKAGES = ('qemu-system-x86', 'qemu-utils', 'ovmf', 'ffmpeg')


RUNNER_MIRROR = 'mirror+file:/etc/apt/apt-mirrors.txt'
OFFICIAL_ARCHIVE = apt.official_uri('https://archive.ubuntu.com/ubuntu')
# KVM-tool fixture archive, adjacent to hosted ubuntu24/20261025.353.
# The shipped image and its native package/compiler qualification are separate.
NOBLE_ARCHIVE = 'https://snapshot.ubuntu.com/ubuntu/20261026T000000Z'


def runner_archive(root):
    # runner-images/configure-apt-sources.sh creates this local list. Refuse
    # unknown content instead of treating an arbitrary mirror as Ubuntu.
    path = root / 'etc/apt/apt-mirrors.txt'
    if (path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
            or path.stat().st_size > 16384):
        raise ValueError('Expected a regular runner Ubuntu mirror list')
    allowed = {'http://azure.archive.ubuntu.com/ubuntu',
               'https://archive.ubuntu.com/ubuntu',
               'https://security.ubuntu.com/ubuntu'}
    entries = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        fields = line.split()
        if (fields[0].removesuffix('/') not in allowed or len(fields) > 2
                or (len(fields) == 2 and not re.fullmatch(r'priority:[0-9]+', fields[1]))):
            raise ValueError('Unsupported runner Ubuntu mirror entry')
        entries += 1
    if not entries:
        raise ValueError('Empty runner Ubuntu mirror list')
    return OFFICIAL_ARCHIVE


def source_text(text, root=Path('/'), *, archive_uri=OFFICIAL_ARCHIVE):
    if archive_uri not in (OFFICIAL_ARCHIVE, NOBLE_ARCHIVE):
        raise ValueError('Unsupported KVM tool archive')
    def mirror(match):
        if match[0] != RUNNER_MIRROR:
            raise ValueError(f'Unsupported APT mirror source: {match[0]}')
        runner_archive(root)
        return archive_uri

    result = []
    for line in text.splitlines(keepends=True):
        # Leave comments intact in both one-line and deb822 source files.
        parts = re.split(r'(?<!\S)(?=#)', line, maxsplit=1)
        active = re.sub(r'(?<!\S)mirror(?:\+[^:\s]+)?:\S*', mirror, parts[0])
        active = re.sub(r'(?<!\S)https?://(?:azure\.)?archive\.ubuntu\.com/ubuntu/?(?=\s|$)',
                        archive_uri, active)
        if archive_uri == NOBLE_ARCHIVE:
            active = re.sub(r'(?<!\S)https?://security\.ubuntu\.com/ubuntu/?(?=\s|$)',
                            archive_uri, active)
        result.append(active + ''.join(parts[1:]))
    return ''.join(result)


def retain_metadata(lists, evidence):
    """Retain real APT cache identities and signed metadata, not a pass flag."""
    evidence.mkdir(parents=True)
    prefix = NOBLE_ARCHIVE.removeprefix('https://').replace('/', '_') + '_'
    indices = []
    for path in sorted(lists.glob(prefix + '*')):
        if not path.is_file():
            continue
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        indices.append({'name': path.name, 'size': path.stat().st_size, 'sha256': digest})
        if path.name.endswith('_InRelease'):
            shutil.copyfile(path, evidence / path.name)
    (evidence / 'index-closure.json').write_text(json.dumps({
        'schema': 1, 'scope': 'KVM-tool metadata, not shipped image qualification',
        'archive_uri': NOBLE_ARCHIVE, 'indices': indices,
    }, indent=2, sort_keys=True) + '\n')


def install(root=Path('/'), budget=apt.BUDGET, evidence=None):
    release = dict(line.split('=', 1) for line in (root / 'usr/lib/os-release').read_text().splitlines() if '=' in line)
    version = (release.get('ID', '').strip('"'), release.get('VERSION_ID', '').strip('"'))
    if version not in (('ubuntu', '24.04'), ('ubuntu', '26.04')):
        raise ValueError(f'Unsupported runner: {version}')
    if apt.run(['dpkg', '--print-architecture']).strip() != 'amd64':
        raise ValueError('The PR KVM tool caller requires amd64')
    archive_uri = NOBLE_ARCHIVE if version == ('ubuntu', '24.04') else OFFICIAL_ARCHIVE
    if archive_uri != NOBLE_ARCHIVE:
        evidence = None
    print(f'KVM tool Ubuntu archive: {archive_uri}', flush=True)
    print(f'KVM tool host kernel: {os.uname().release}', flush=True)
    started = time.monotonic()
    deadline = started + budget
    with tempfile.TemporaryDirectory(prefix='tunaos-kvm-apt-') as directory:
        work = Path(directory)
        work.chmod(0o755)
        sources = work / 'sources.list.d'
        shutil.copytree(root / 'etc/apt/sources.list.d', sources)
        for path in sources.iterdir():
            if path.suffix in ('.list', '.sources'):
                # Replace symlinks in the private copy, never follow a link when writing.
                text = source_text(path.read_text(), root, archive_uri=archive_uri)
                path.unlink()
                path.write_text(text)
        main = work / 'sources.list'
        original = root / 'etc/apt/sources.list'
        main.write_text(source_text(original.read_text(), root, archive_uri=archive_uri)
                        if original.exists() else '')
        lists = work / 'lists'
        lists.mkdir()
        empty = work / 'empty'
        empty.mkdir()
        cache = root / 'var/cache/apt/archives'
        cache.mkdir(parents=True, exist_ok=True)
        command = ['apt-get', '-o', f'Dir::Etc::sourcelist={main}',
                   '-o', f'Dir::Etc::sourceparts={sources}', '-o', f'Dir::State::lists={lists}',
                   '-o', f'Dir::Cache::archives={cache}', '-o', 'APT::Update::Error-Mode=any',
                   '-o', 'Acquire::Retries=2', '-o', 'Acquire::http::Timeout=30',
                   '-o', 'Acquire::https::Timeout=30', '-o', 'Acquire::ForceHash=SHA256']
        try:
            apt.run([*command, 'update'], timeout=apt.remaining(deadline))
            if evidence is not None:
                retain_metadata(lists, evidence)
            transaction = [*command, 'install', '-y', *PACKAGES]
            plan = apt.run([*transaction, '--simulate'], timeout=apt.remaining(deadline))
            expected = dict(re.findall(r'^Inst (\S+)(?: \[[^\]]+\])? \((\S+)', plan, re.MULTILINE))
            entries = apt.manifest(apt.run([*transaction, '--download-only', '--print-uris',
                                           '-o', f'Dir::Cache::archives={empty}'], timeout=apt.remaining(deadline)))
            if expected and not entries:
                raise RuntimeError('APT planned changes without a package hash manifest')
            if evidence is not None:
                (evidence / 'archive-closure.json').write_text(json.dumps({
                    'schema': 1, 'scope': 'KVM-tool acquisition, not shipped image qualification',
                    'archive_uri': archive_uri, 'planned_versions': expected,
                    'archives': [{'name': name, 'size': size, 'sha256': digest}
                                 for name, size, digest in entries],
                }, indent=2, sort_keys=True) + '\n')
            for attempt in range(apt.ATTEMPTS):
                apt.verify_cache(cache, entries)
                try:
                    apt.run([*transaction, '--download-only'], timeout=min(200, apt.remaining(deadline)))
                    if apt.verify_cache(cache, entries):
                        apt.remaining(deadline)
                        break
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    if attempt == apt.ATTEMPTS - 1:
                        raise
            else:
                raise RuntimeError('APT cache verification failed')
        finally:
            print(f'KVM tools acquisition duration: {time.monotonic() - started:.1f}s', flush=True)
        started = time.monotonic()
        try:
            with apt.defer_termination(), apt.suppress_restarts(root / 'etc/needrestart/conf.d'):
                apt.run([*transaction, '--no-download'])
            for package, expected_version in expected.items():
                actual = apt.run(['dpkg-query', '-W', '-f=${Version}', package]).strip()
                if actual != expected_version:
                    raise RuntimeError(f'{package}: expected {expected_version}, installed {actual}')
            for package in PACKAGES:
                if apt.run(['dpkg-query', '-W', '-f=${db:Status-Status}', package]).strip() != 'installed':
                    raise RuntimeError(f'{package} is not installed')
        finally:
            print(f'KVM tools installation duration: {time.monotonic() - started:.1f}s', flush=True)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, apt.terminate)
    install(evidence=Path('verify-out/kvm-tools'))
