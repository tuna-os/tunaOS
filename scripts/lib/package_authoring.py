"""Offline, native-index-backed edits of explicit desktop package policies.

Indexes are operator-supplied evidence, not a substitute for repository signature
verification or an install transaction. No code or package manager is executed.
"""
from __future__ import annotations

import bz2
from datetime import datetime, timezone
import difflib
import fcntl
from fnmatch import fnmatchcase
import gzip
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile
import xml.etree.ElementTree as ET

from . import tunaos_config

MAX_BYTES = 128 * 1024 * 1024
MAX_CONFIG_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
FORMATS = {
    'apt': 'apt-packages', 'pacman': 'pacman-db', 'cachyos': 'pacman-db',
    'emerge': 'gentoo-tree', **dict.fromkeys(
        ('fedora', 'rawhide', 'hummingbird', 'eln', 'el10', 'zypper'), 'rpm-primary'),
}
DNF_FAMILIES = {'fedora', 'rawhide', 'hummingbird', 'eln', 'el10'}
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9+_.-]*\Z')
ATOM = re.compile(r'[a-z0-9][a-z0-9+_.-]*/[A-Za-z0-9][A-Za-z0-9+_.-]*\Z')


class AuthoringError(ValueError):
    pass


def checked_name(name, gentoo=False):
    if not isinstance(name, str) or not (ATOM if gentoo else NAME).fullmatch(name):
        raise AuthoringError(f'invalid native package name: {name!r}')
    return name


def read_limited(stream, limit=None):
    limit = MAX_BYTES if limit is None else limit
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise AuthoringError(f'input exceeds {limit} byte limit')
    return data



def read_file(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AuthoringError(f'{path}: input must be a regular file')
        return read_limited(stream, limit)


def read_config(path):
    return read_file(path, MAX_CONFIG_BYTES)


def unpack(data):
    if data.startswith(b'\x1f\x8b'):
        return read_limited(gzip.GzipFile(fileobj=io.BytesIO(data)))
    if data.startswith(b'\xfd7zXZ'):
        return read_limited(lzma.LZMAFile(io.BytesIO(data)))
    if data.startswith(b'BZh'):
        return read_limited(bz2.BZ2File(io.BytesIO(data)))
    return data


def native_names(data, kind, architecture):
    """Read native identities only. Never infer aliases from descriptions."""
    data = unpack(data)
    names = set()
    if kind == 'apt-packages':
        for record in re.split(r'\n\s*\n', data.decode('utf-8')):
            fields = {}
            for line in record.splitlines():
                if not line or line[0].isspace():
                    continue
                key, separator, value = line.partition(':')
                value = value.lstrip()
                if not separator or key in fields:
                    raise AuthoringError('malformed apt Packages record')
                fields[key] = value
            if fields:
                if not {'Package', 'Version', 'Architecture'} <= fields.keys():
                    raise AuthoringError('apt record lacks Package/Version/Architecture')
                name = checked_name(fields['Package'])
                if fields['Architecture'] in {architecture, 'all'}:
                    names.add(name)
    elif kind == 'rpm-primary':
        # Reject entity declarations before XML parsing; metadata needs no DTD.
        xml = data.decode('utf-8')
        if '<!DOCTYPE' in xml or '<!ENTITY' in xml:
            raise AuthoringError('RPM metadata must not contain DTD/entities')
        root = ET.fromstring(xml)
        ns = '{http://linux.duke.edu/metadata/common}'
        if root.tag != ns + 'metadata':
            raise AuthoringError('expected RPM primary metadata root')
        for package in root.findall(ns + 'package'):
            if package.get('type') != 'rpm':
                raise AuthoringError('expected RPM package record')
            name = checked_name(package.findtext(ns + 'name'))
            arch = package.findtext(ns + 'arch')
            if not arch:
                raise AuthoringError('RPM package lacks architecture')
            if arch in {architecture, 'noarch'}:
                names.add(name)
    elif kind in {'pacman-db', 'gentoo-tree'}:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
            for member in archive:
                if not member.isfile():
                    continue
                parts = member.name.split('/')
                if kind == 'pacman-db' and parts[-1] == 'desc':
                    if member.size > 1024 * 1024:
                        raise AuthoringError('pacman desc exceeds 1 MiB')
                    lines = archive.extractfile(member).read().decode('utf-8').splitlines()
                    if lines.count('%NAME%') != 1:
                        raise AuthoringError('pacman desc requires one %NAME%')
                    offset = lines.index('%NAME%') + 1
                    if offset >= len(lines):
                        raise AuthoringError('pacman desc has no package name')
                    name = checked_name(lines[offset])
                    if lines.count('%ARCH%') != 1 or lines.index('%ARCH%') + 1 >= len(lines):
                        raise AuthoringError('pacman desc requires one architecture')
                    if lines[lines.index('%ARCH%') + 1] in {architecture, 'any'}:
                        names.add(name)
                elif kind == 'gentoo-tree' and len(parts) >= 3 and parts[-1].endswith('.ebuild'):
                    category, package, ebuild = parts[-3:]
                    if not re.fullmatch(re.escape(package) + r'-[0-9][A-Za-z0-9+_.-]*\.ebuild', ebuild):
                        raise AuthoringError(f'invalid Gentoo ebuild path: {member.name}')
                    names.add(checked_name(category + '/' + package, gentoo=True))
    else:
        raise AuthoringError(f'unsupported native index format: {kind}')
    if not names:
        raise AuthoringError('index contains no native package records')
    return names


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuthoringError(f'duplicate receipt field: {key}')
        result[key] = value
    return result


def load_index(path, family, max_age_days=7, now=None):
    """Bind native index bytes to an explicit, versioned provenance receipt."""
    path = Path(path)
    receipt = json.loads(read_file(path, MAX_RECEIPT_BYTES).decode('utf-8'), object_pairs_hook=unique_fields)
    expected = {'schema_version', 'family', 'format', 'repository', 'release',
                'architecture', 'retrieved_at', 'path', 'sha256'}
    if not isinstance(receipt, dict) or set(receipt) != expected:
        raise AuthoringError(f'{path}: expected index receipt fields {sorted(expected)}')
    if type(receipt['schema_version']) is not int or receipt['schema_version'] != 1:
        raise AuthoringError(f'{path}: unsupported index receipt schema_version')
    for key in expected - {'schema_version'}:
        if not isinstance(receipt[key], str) or not receipt[key].strip() or any(ord(c) < 32 for c in receipt[key]):
            raise AuthoringError(f'{path}: invalid {key}')
    if receipt['family'] != family or receipt['format'] != FORMATS[family]:
        raise AuthoringError(f'{path}: index family/format does not match target {family}')
    allowed_arches = {'amd64', 'arm64'} if family == 'apt' else {'source'} if family == 'emerge' else {'x86_64', 'aarch64'}
    if receipt['architecture'] not in allowed_arches:
        raise AuthoringError(f'{path}: unsupported native architecture for {family}')
    if not re.fullmatch(r'https://[^\s]+', receipt['repository']):
        raise AuthoringError(f'{path}: repository must identify an HTTPS source')
    if not re.fullmatch(r'[a-f0-9]{64}', receipt['sha256']):
        raise AuthoringError(f'{path}: invalid sha256')
    retrieved = datetime.fromisoformat(receipt['retrieved_at'].replace('Z', '+00:00'))
    if retrieved.tzinfo is None:
        raise AuthoringError(f'{path}: retrieved_at requires a timezone')
    age = ((now or datetime.now(timezone.utc)) - retrieved).total_seconds()
    if age < 0 or age > max_age_days * 86400:
        raise AuthoringError(f'{path}: index is future-dated or older than {max_age_days} days; refresh it')
    data = read_file(path.parent / receipt['path'], MAX_BYTES)
    if hashlib.sha256(data).hexdigest() != receipt['sha256']:
        raise AuthoringError(f'{path}: index sha256 mismatch; refresh receipt and index together')
    return native_names(data, receipt['format'], receipt['architecture']), receipt


def targets(document, selected):
    if not selected or len(set(selected)) != len(selected):
        raise AuthoringError('supply distinct explicit --target DESKTOP:FAMILY values')
    result = {}
    for target in selected:
        parts = target.split(':')
        if len(parts) != 2:
            raise AuthoringError(f'{target}: expected DESKTOP:FAMILY')
        desktop, family = parts
        if family not in FORMATS or family not in document.get('desktops', {}).get(desktop, {}).get('packages', {}):
            raise AuthoringError(f'{target}: no existing native package policy; select a declared desktop/family')
        result[target] = (desktop, family)
    return result


def resolve(query, names, family):
    checked_name(query, gentoo='/' in query and family == 'emerge')
    matches = {query} & names
    if family == 'emerge' and '/' not in query:
        matches = {name for name in names if name.split('/')[1] == query}
    if len(matches) != 1:
        reason = 'unavailable' if not matches else 'ambiguous: ' + ', '.join(sorted(matches))
        raise AuthoringError(f'{query}: {reason}; search the index and pass an exact native name')
    return matches.pop()


def plan(source, selected, indexes, query, native=None, max_age_days=7, *, source_path='<package config>'):
    """Resolve every target before touching a TOML object or the original file."""
    document = tunaos_config.validate(tunaos_config.parse(source, source_path))
    scope = targets(document, selected)
    if set(indexes) != set(scope):
        raise AuthoringError('--index TARGET=RECEIPT is required exactly once for every selected target')
    native = native or {}
    if set(native) - set(scope):
        raise AuthoringError('--native overrides must name selected targets')
    resolved, evidence = {}, {}
    for target, (_, family) in scope.items():
        names, receipt = load_index(indexes[target], family, max_age_days)
        resolved[target] = resolve(native.get(target, query), names, family)
        evidence[target] = receipt
    return document, scope, resolved, evidence



def name_excluded(name, family, exclusions):
    """Match DNF name globs only; other policy families retain literal names.

    install-desktop.sh forwards DNF exclusions as -x arguments. DNF supports
    both ! and ^ bracket negation, unlike Python's !-only fnmatch syntax:
    https://dnf5.readthedocs.io/en/latest/misc/specs.7.html#globs
    This is not NEVRA/version/dependency transaction resolution.
    """
    if family not in DNF_FAMILIES:
        return name in exclusions
    for exclusion in exclusions:
        for pattern in exclusion.split(','):
            pattern = pattern.strip()
            if any(token in pattern for token in ('\\', '[[:', '[[.', '[[=')) or any(c.isspace() for c in pattern):
                raise AuthoringError('DNF exclusion syntax needs native transaction review; no write performed')
            if fnmatchcase(name, pattern.replace('[^', '[!')):
                return True
    return False


def edit(source, document, scope, resolved):
    try:
        import tomlkit
    except ModuleNotFoundError as exc:
        raise AuthoringError('Editing requires: python3 -m pip install -r requirements-package-authoring.txt') from exc
    import copy
    expected = copy.deepcopy(document)
    edited = tomlkit.parse(source.decode('utf-8'))
    for target, (desktop, family) in scope.items():
        policy = document['desktops'][desktop]['packages'][family]
        expanded = tunaos_config.package_policy().expand(document['package_groups'], policy)
        name = resolved[target]
        if name_excluded(name, family, expanded.get('exclude', [])):
            raise AuthoringError(f'{target}: {name} is excluded; reconcile policy manually')
        if name in expanded.get('required', []):
            continue
        target_policy = edited['desktops'][desktop]['packages'][family]
        if 'required' not in target_policy:
            target_policy['required'] = tomlkit.array()
        target_policy['required'].append(name)
        expected['desktops'][desktop]['packages'][family].setdefault('required', []).append(name)
    result = tomlkit.dumps(edited).encode('utf-8')
    if len(result) > MAX_CONFIG_BYTES:
        raise AuthoringError('edited config exceeds 8 MiB limit; no write performed')
    actual = tunaos_config.validate(tunaos_config.parse(result, '<edited package config>'))
    if actual != expected:
        raise AuthoringError('lossless edit changed unrelated configuration; no write performed')
    return result


def diff(source, result, path):
    return ''.join(difflib.unified_diff(source.decode().splitlines(keepends=True),
                                       result.decode().splitlines(keepends=True),
                                       fromfile=str(path), tofile=str(path)))


def atomic_write(path, source, result):
    """Serialize cooperating authors; detect intervening edits before replacement."""
    path = Path(path)
    if len(result) > MAX_CONFIG_BYTES:
        raise AuthoringError('edited config exceeds 8 MiB limit; no write performed')
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise AuthoringError('config must be a regular, non-symlink, single-link file')
    lock = path.with_name('.' + path.name + '.packages.lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise AuthoringError('lock must be a regular file')
        fcntl.flock(stream, fcntl.LOCK_EX)
        previous = path.lstat()
        if not stat.S_ISREG(previous.st_mode) or previous.st_nlink != 1 or read_config(path) != source:
            raise AuthoringError('config changed during resolution; rerun and review the new diff')
        if result == source:
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', delete=False) as output:
                temporary = Path(output.name)
                os.fchmod(output.fileno(), stat.S_IMODE(previous.st_mode))
                output.write(result)
                output.flush()
                os.fsync(output.fileno())
            current = path.lstat()
            signature = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            if signature(current) != signature(previous) or read_config(path) != source:
                raise AuthoringError('config changed before commit; rerun and review the new diff')
            os.replace(temporary, path)
            temporary = None
            try:
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except OSError as exc:
                raise AuthoringError(f'file replaced; durability unconfirmed: {exc}. Inspect the config before retrying.') from exc
        finally:
            if temporary is not None:
                temporary.unlink()
