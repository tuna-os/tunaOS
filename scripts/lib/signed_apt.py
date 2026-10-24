"""Bounded, signed APT repository search for reviewed configured targets.

GnuPG is an explicit existing native dependency, never installed by this module.
No keys are installed, imported, fetched or added to the user's trust database.
"""
import hashlib
import zlib
import lzma
from pathlib import Path
import re
import shutil
import selectors
import os
import subprocess
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit
from .package_catalogs import (CatalogError, validate, check_authenticated_dates,
                               index_specs, signed_timestamp)

MAX_RELEASE = 1024 * 1024
MAX_INDEX = 128 * 1024 * 1024


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = urlsplit(req.full_url), urlsplit(newurl)
        if after.scheme != 'https' or after.netloc != before.netloc or after.username or after.password:
            raise CatalogError('cross-host or insecure metadata redirect refused')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_https(url, limit, timeout=30):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc not in {
            'deb.debian.org', 'pkgs.tailscale.com'} or parsed.query or parsed.fragment):
        raise CatalogError('unsupported metadata URL')
    request = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
    started = time.monotonic()
    with urllib.request.build_opener(SameHostRedirect()).open(request, timeout=timeout) as response:
        if response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
            raise CatalogError('unexpected metadata HTTP response')
        length = response.headers.get('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > limit):
            raise CatalogError('metadata exceeds size bound')
        data = bytearray()
        while True:
            chunk = response.read(min(65536, limit + 1 - len(data)))
            data.extend(chunk)
            if len(data) > limit or time.monotonic() - started > timeout:
                raise CatalogError('metadata exceeds byte/time bound')
            if not chunk:
                break
        if length is not None and len(data) != int(length):
            raise CatalogError('truncated metadata response')
        return bytes(data)


def valid_signers(status, allowed):
    accepted = set()
    fatal = {'BADSIG', 'ERRSIG', 'EXPSIG', 'EXPKEYSIG', 'REVKEYSIG', 'NO_PUBKEY',
             'NODATA', 'FAILURE', 'ERROR', 'KEYEXPIRED', 'SIGEXPIRED'}
    for line in status.splitlines():
        parts = line.split()
        if not parts or parts[0] != '[GNUPG:]':
            raise CatalogError('unexpected signature-verifier status')
        if len(parts) < 2 or parts[1] in fatal:
            raise CatalogError('invalid, unavailable or expired signature')
        if parts[1] == 'VALIDSIG':
            if len(parts) != 12 or parts[8] not in {'1', '22'} or parts[9] not in {'8', '9', '10', '11'}:
                raise CatalogError('unsupported signature status or public-key/digest algorithm')
            primary = parts[11]
            if not re.fullmatch(r'[0-9A-F]{40}', primary):
                raise CatalogError('invalid primary fingerprint')
            if primary in allowed:
                accepted.add(primary)
    if not accepted:
        raise CatalogError('no signature from a declared primary key')
    return sorted(accepted)


def verify_inrelease(envelope, keyring, source, verifier=None):
    if len(envelope) > MAX_RELEASE or not envelope.startswith(b'-----BEGIN PGP SIGNED MESSAGE-----\n'):
        raise CatalogError('expected bounded clear-signed InRelease')
    if len(keyring) > MAX_RELEASE or hashlib.sha256(keyring).hexdigest() != source['keyring_sha256']:
        raise CatalogError('keyring bytes do not match reviewed trust pin')
    executable = verifier or shutil.which('gpg')
    if not executable:
        raise CatalogError('GnuPG is required for signed acquisition; install it explicitly')
    with tempfile.TemporaryDirectory(prefix='tuna-apt-verify-') as directory:
        root = Path(directory)
        (root/'InRelease').write_bytes(envelope)
        (root/'keys.pgp').write_bytes(keyring)
        command = [executable, '--no-options', '--batch', '--no-tty', '--homedir', str(root),
                   '--no-default-keyring', '--keyring', str(root/'keys.pgp'),
                   '--no-auto-key-retrieve', '--no-auto-key-import', '--status-fd', '1',
                   '--output', str(root/'Release'), '--decrypt', str(root/'InRelease')]
        status = bytearray()
        diagnostic_bytes = 0
        try:
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ, True)
                    selector.register(process.stderr, selectors.EVENT_READ, False)
                    deadline = time.monotonic() + 30
                    try:
                        while selector.get_map():
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise CatalogError('native signature verification timed out')
                            for key, _ in selector.select(remaining):
                                chunk = os.read(key.fileobj.fileno(), 65536)
                                if not chunk:
                                    selector.unregister(key.fileobj)
                                elif key.data:
                                    status.extend(chunk)
                                else:
                                    diagnostic_bytes += len(chunk)
                                if len(status) + diagnostic_bytes > 4 * MAX_RELEASE:
                                    raise CatalogError('signature diagnostics exceed size bound')
                        process.wait(timeout=max(0.01, deadline-time.monotonic()))
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                if process.returncode != 0:
                    raise CatalogError('native signature verification failed')
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CatalogError('native signature verification unavailable or timed out') from exc
        signers = valid_signers(
            status.decode('utf-8', errors='replace'), source['primary_fingerprints'])
        payload_path = root/'Release'
        if not payload_path.is_file() or payload_path.stat().st_size > MAX_RELEASE:
            raise CatalogError('authenticated payload exceeds size bound')
        return payload_path.read_bytes(), signers


def parse_release(payload):
    if len(payload) > MAX_RELEASE:
        raise CatalogError('Release exceeds size bound')
    fields, checksums, current = {}, {}, None
    try:
        text = payload.decode('utf-8')
    except UnicodeError as exc:
        raise CatalogError('Release has invalid UTF-8 encoding') from exc
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith(' '):
            if current != 'SHA256':
                continue  # Other native checksum tables are not trusted for acquisition.
            parts = line.split()
            if len(parts) != 3:
                raise CatalogError('malformed SHA256 entry')
            sha, size, path = parts
            if not re.fullmatch(r'[0-9a-f]{64}', sha) or not size.isdecimal() or path in checksums:
                raise CatalogError('invalid or duplicate SHA256 entry')
            if path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/')) or '\\' in path:
                raise CatalogError('unsafe checksum path')
            checksums[path] = (sha, int(size))
        else:
            key, sep, value = line.partition(':')
            if not sep or key in fields or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*', key):
                raise CatalogError('malformed or duplicate Release field')
            current = key
            fields[key] = value.strip()
    if not checksums:
        raise CatalogError('Release has no SHA256 index table')
    return fields, checksums


def index_names(data, compression='xz'):
    if len(data) > MAX_INDEX:
        raise CatalogError('compressed index too large')
    try:
        if compression == 'xz':
            decoder = lzma.LZMADecompressor(memlimit=MAX_INDEX)
            decoded = decoder.decompress(data, max_length=MAX_INDEX + 1)
        elif compression == 'gzip':
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            decoded = decoder.decompress(data, MAX_INDEX + 1)
        else:
            raise CatalogError('unsupported index compression')
    except (lzma.LZMAError, zlib.error) as exc:
        raise CatalogError('invalid compressed index') from exc
    if len(decoded) > MAX_INDEX or not decoder.eof or decoder.unused_data:
        raise CatalogError('expanded, incomplete or trailing index data')
    names = set()
    for paragraph in decoded.decode('utf-8').split('\n\n'):
        fields = {}
        for line in paragraph.splitlines():
            if line.startswith((' ', '\t')):
                continue
            key, sep, value = line.partition(': ')
            if not sep or key in fields:
                raise CatalogError('malformed or duplicate package field')
            fields[key] = value
        if not fields:
            continue
        if 'Package' not in fields or 'Architecture' not in fields:
            raise CatalogError('package record lacks identity')
        name = fields['Package']
        if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', name):
            raise CatalogError('invalid native package name')
        if fields['Architecture'] in ('amd64', 'all'):
            names.add(name)
    return names


def acquire_catalog(catalog, keyring_for, now, fetch=fetch_https, verify=verify_inrelease):
    """Authenticate every configured source before returning any target result."""
    validate(catalog)
    complete = []
    for source in catalog['sources']:
        root = source['uri'] + 'dists/' + source['suite'] + '/'
        metadata_url = root + 'InRelease'
        envelope = fetch(metadata_url, MAX_RELEASE)
        payload, signers = verify(envelope, keyring_for(source), source)
        fields, checksums = parse_release(payload)
        envelope_hash = hashlib.sha256(envelope).hexdigest()
        expiry = check_authenticated_dates(source, fields, now, envelope_hash)
        specs = index_specs(source, fields, architecture='amd64', component='main')
        if any(spec['by_hash'] for spec in specs) and fields.get('Acquire-By-Hash') != 'yes':
            raise CatalogError('required by-hash index is unavailable')
        names = set()
        indexes = []
        for spec in specs:
            path = spec['path']
            if path not in checksums:
                raise CatalogError('required signed package index is unavailable')
            sha, size = checksums[path]
            if not 0 < size <= MAX_INDEX:
                raise CatalogError('index size outside bound')
            if spec['by_hash']:
                directory = path.rsplit('/', 1)[0]
                url = root + directory + '/by-hash/SHA256/' + sha
            else:
                url = root + path
            data = fetch(url, size)
            if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
                raise CatalogError('index hash or size differs from signed Release')
            names.update(index_names(data, spec['compression']))
            indexes.append({'url': url, 'sha256': sha, 'size': size})
        complete.append({
            'source': source['id'],
            'role': source['role'],
            'source_url': metadata_url,
            'release': fields['Codename'],
            'architecture': 'amd64',
            'signed_at': signed_timestamp(fields).isoformat(),
            'retrieved_at': now.isoformat(),
            'inrelease_sha256': envelope_hash,
            'keyring_sha256': source['keyring_sha256'],
            'indexes': indexes,
            'names': names,
            'signers': signers,
            'freshness': {
                'mode': source['freshness']['mode'],
                'expires': expiry.isoformat() if expiry else None,
            },
        })
    return complete
