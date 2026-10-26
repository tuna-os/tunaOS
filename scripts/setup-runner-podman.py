#!/usr/bin/env python3
"""Bound only APT acquisition for the pinned setup-runner caller (#3812)."""

import contextlib
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

PACKAGES = ('crun', 'buildah', 'podman', 'skopeo')
SELECTORS = tuple(f'{name}/resolute' for name in PACKAGES)
BUDGET = 600
ATTEMPTS = 3


def official_uri(uri):
    parsed = urlsplit(uri)
    allowed = {'archive.ubuntu.com': '/ubuntu', 'ports.ubuntu.com': '/ubuntu-ports'}
    if (parsed.scheme != 'https' or parsed.hostname not in allowed
            or parsed.netloc != parsed.hostname or parsed.query or parsed.fragment
            or parsed.path != allowed[parsed.hostname]):
        raise ValueError(f'Not an official Ubuntu archive URI: {uri}')
    return uri


def archive(arch):
    if arch == 'amd64':
        return official_uri('https://archive.ubuntu.com/ubuntu')
    if arch in ('arm64', 'armhf', 'ppc64el', 'riscv64', 's390x'):
        return official_uri('https://ports.ubuntu.com/ubuntu-ports')
    raise ValueError(f'Unsupported Ubuntu architecture: {arch}')


def run(args, timeout=None):
    # Only acquisition receives a timeout. Never terminate an active dpkg.
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, start_new_session=True,
                          env={**os.environ, 'LC_ALL': 'C', 'DEBIAN_FRONTEND': 'noninteractive'}) as proc:
        try:
            output, _ = proc.communicate(timeout=timeout)
        except BaseException:
            if timeout is not None:
                os.killpg(proc.pid, signal.SIGKILL)
            output, _ = proc.communicate()
            print(output, flush=True)
            raise
        print(output, end='', flush=True)
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, args, output)
        return output


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError('APT acquisition deadline exhausted')
    return seconds


def manifest(output):
    result = []
    for line in output.splitlines():
        if not line.startswith("'"):
            continue
        uri, filename, size, digest = shlex.split(line)
        # Dependencies may come from existing runner sources. APT authenticates
        # those too; resolute's source itself is fixed by archive(), not input.
        if (filename in ('.', '..') or '/' in filename
                or not re.fullmatch(r'SHA256:[0-9a-fA-F]{64}', digest)):
            raise ValueError('Expected a basename and authenticated SHA256')
        result.append((filename, int(size), digest.removeprefix('SHA256:')))
    return result


def verify_cache(cache, entries):
    valid = True
    for name, size, digest in entries:
        path = cache / name
        if not path.is_file():
            valid = False
        elif path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            path.unlink()
            valid = False
    return valid


@contextlib.contextmanager
def defer_termination():
    # Let dpkg finish, then clean up and honour cancellation. SIGKILL cannot
    # be caught; the runner's outer job timeout still applies.
    pending = []
    previous = {}
    for number in (signal.SIGINT, signal.SIGTERM):
        previous[number] = signal.signal(number, lambda signum, frame: pending.append(signum))
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    if pending:
        raise SystemExit(128 + pending[0])


@contextlib.contextmanager
def suppress_restarts(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix='99-tunaos-', suffix='.conf', delete=False) as config:
        path = Path(config.name)
        config.write(b'$nrconf{restart} = "l";\n')
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def upgrade(root=Path('/'), budget=BUDGET):
    release = dict(line.split('=', 1) for line in (root / 'usr/lib/os-release').read_text().splitlines() if '=' in line)
    version = (release.get('ID', '').strip('"'), release.get('VERSION_ID', '').strip('"'))
    if version == ('ubuntu', '26.04'):
        check_podman()
        return
    if version != ('ubuntu', '24.04'):
        raise ValueError(f'Unsupported runner: {version}')
    mirror = archive(run(['dpkg', '--print-architecture']).strip())
    started = time.monotonic()
    deadline = started + budget
    with tempfile.TemporaryDirectory(prefix='tunaos-apt-') as work:
        work = Path(work)
        work.chmod(0o755)
        sources = work / 'sources.list.d'
        shutil.copytree(root / 'etc/apt/sources.list.d', sources)
        (sources / 'resolute.list').write_text(f'deb {mirror} resolute universe main\n')
        lists = work / 'lists'
        lists.mkdir()
        empty = work / 'empty'
        empty.mkdir()
        cache = root / 'var/cache/apt/archives'
        cache.mkdir(parents=True, exist_ok=True)
        apt = ['apt-get', '-o', f'Dir::Etc::sourceparts={sources}',
               '-o', f'Dir::State::lists={lists}', '-o', f'Dir::Cache::archives={cache}',
               '-o', 'APT::Update::Error-Mode=any', '-o', 'Acquire::Retries=2',
               '-o', 'Acquire::http::Timeout=30', '-o', 'Acquire::https::Timeout=30',
               '-o', 'Acquire::ForceHash=SHA256']
        try:
            run([*apt, 'update'], timeout=remaining(deadline))
            install = [*apt, 'install', '-y', '--allow-downgrades', *SELECTORS]
            plan = run([*install, '--simulate'], timeout=remaining(deadline))
            expected = dict(re.findall(r'^Inst (\S+)(?: \[[^\]]+\])? \((\S+)', plan, re.MULTILINE))
            entries = manifest(run([*install, '--download-only', '--print-uris',
                                    '-o', f'Dir::Cache::archives={empty}'], timeout=remaining(deadline)))
            for attempt in range(ATTEMPTS):
                verify_cache(cache, entries)  # Evict corrupt cache hits before APT.
                try:
                    run([*install, '--download-only'], timeout=min(200, remaining(deadline)))
                    if verify_cache(cache, entries):
                        break
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    if attempt == ATTEMPTS - 1:
                        raise
            else:
                raise RuntimeError('APT cache verification failed')
        finally:
            print(f'APT acquisition duration: {time.monotonic() - started:.1f}s', flush=True)
        started = time.monotonic()
        try:
            with defer_termination(), suppress_restarts(root / 'etc/needrestart/conf.d'):
                run([*install, '--no-download'])
            for package, expected_version in expected.items():
                actual = run(['dpkg-query', '-W', '-f=${Version}', package]).strip()
                if actual != expected_version:
                    raise RuntimeError(f'{package}: expected {expected_version}, installed {actual}')
            for package in PACKAGES:
                status = run(['dpkg-query', '-W', '-f=${db:Status-Status}', package]).strip()
                if status != 'installed':
                    raise RuntimeError(f'{package}: {status}')
            check_podman()
        finally:
            print(f'APT installation duration: {time.monotonic() - started:.1f}s', flush=True)


def check_podman():
    output = run(['podman', '--version'])
    match = re.search(r'\b(\d+)\.', output)
    if not match or int(match[1]) < 5:
        raise RuntimeError(f'Podman 5 or newer required: {output}')


def terminate(signum, frame):
    raise SystemExit(128 + signum)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, terminate)
    upgrade()
