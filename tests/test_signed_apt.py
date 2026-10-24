"""Offline adversarial acquisition tests, with explicit fake transport/verifier."""
from datetime import datetime, timezone
import gzip
import hashlib
import io
import lzma
import urllib.request
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import signed_apt as acquire
from lib.package_catalogs import CatalogError
from tests.test_package_catalogs import fixture


def status(primary='A' * 40, digest='8'):
    return '[GNUPG:] VALIDSIG '+ 'B'*40 + ' 2026-10-20 1792454400 0 4 0 1 '+digest+' 01 '+primary+'\n'


def test_full_primary_fingerprint_from_subkey():
    assert acquire.valid_signers(status(), ['A'*40]) == ['A'*40]


@pytest.mark.parametrize('data', [status('C'*40), status(digest='2'), '[GNUPG:] GOODSIG A somebody\n',
    status()+'[GNUPG:] BADSIG A somebody\n', status()+'[GNUPG:] EXPKEYSIG A somebody\n',
    status()+'[GNUPG:] REVKEYSIG A somebody\n', status()+'[GNUPG:] NO_PUBKEY A\n',
    status()+'unexpected stdout\n', '[GNUPG:] VALIDSIG bad\n'])
def test_signature_fail_closed(data):
    with pytest.raises(CatalogError):
        acquire.valid_signers(data, ['A'*40])


def test_bad_pin_and_missing_verifier(monkeypatch):
    source = fixture()['sources'][0]
    envelope = b'-----BEGIN PGP SIGNED MESSAGE-----\n'
    with pytest.raises(CatalogError, match='trust pin'):
        acquire.verify_inrelease(envelope, b'key', source)
    source['keyring_sha256'] = hashlib.sha256(b'key').hexdigest()
    monkeypatch.setattr(acquire.shutil, 'which', lambda _: None)
    with pytest.raises(CatalogError, match='install it explicitly'):
        acquire.verify_inrelease(envelope, b'key', source)


@pytest.mark.parametrize('payload', [b'Origin: Debian\nOrigin: Debian\n',
    b'SHA256:\n bad 1 main/Packages.xz\n',
    ('SHA256:\n '+'a'*64+' 1 ../Packages.xz\n').encode(),
    ('SHA256:\n '+('a'*64+' 1 main/Packages.xz\n ')*2).strip().encode(),
    b'Origin Debian\n', b'Origin: Debian\n'])
def test_release_malformed_or_duplicate(payload):
    with pytest.raises(CatalogError):
        acquire.parse_release(payload)


class Response(io.BytesIO):
    status = 200
    def __init__(self, data, headers):
        super().__init__(data)
        self.headers = headers


def transport(monkeypatch, data, headers):
    class Opener:
        def open(self, request, timeout):
            assert request.get_header('Accept-encoding') == 'identity'
            return Response(data, headers)
    monkeypatch.setattr(acquire.urllib.request, 'build_opener', lambda *_: Opener())


def test_bounded_fetch(monkeypatch):
    transport(monkeypatch,b'abc',{'Content-Length':'3'})
    assert acquire.fetch_https('https://deb.debian.org/debian/dists/trixie/InRelease',3)==b'abc'


@pytest.mark.parametrize('data,headers', [(b'abcd',{}), (b'a',{'Content-Length':'3'}),
    (b'a',{'Content-Length':'4'}), (b'a',{'Content-Length':'bad'}),
    (b'a',{'Content-Encoding':'gzip'})])
def test_transport_failure(monkeypatch,data,headers):
    transport(monkeypatch,data,headers)
    with pytest.raises(CatalogError):
        acquire.fetch_https('https://deb.debian.org/debian/dists/trixie/InRelease',3)


@pytest.mark.parametrize('url', ['http://deb.debian.org/x','https://evil.test/x',
    'https://user@deb.debian.org/x','https://deb.debian.org/x?q=y'])
def test_transport_rejects_other_origins(url):
    with pytest.raises(CatalogError):
        acquire.fetch_https(url,3)


def test_redirect_rejects_cross_origin():
    handler=acquire.SameHostRedirect()
    request=urllib.request.Request('https://deb.debian.org/debian/x')
    with pytest.raises(CatalogError):
        handler.redirect_request(request,None,302,'',{},'https://evil.test/x')


def test_index_architecture_empty_and_bounds(monkeypatch):
    data = b'Package: htop\nArchitecture: amd64\n\nPackage: foreign\nArchitecture: arm64\n\n'
    assert acquire.index_names(lzma.compress(data)) == {'htop'}
    assert acquire.index_names(lzma.compress(b'')) == set()
    assert acquire.index_names(gzip.compress(data), 'gzip') == {'htop'}
    with pytest.raises(CatalogError):
        acquire.index_names(lzma.compress(data) + b'trailing')
    with pytest.raises(CatalogError):
        acquire.index_names(gzip.compress(data) + b'trailing', 'gzip')
    with pytest.raises(CatalogError):
        acquire.index_names(gzip.compress(data)[:-4], 'gzip')
    monkeypatch.setattr(acquire, 'MAX_INDEX', 200)
    with pytest.raises(CatalogError):
        acquire.index_names(lzma.compress(b'x' * 201))
    with pytest.raises(CatalogError):
        acquire.index_names(gzip.compress(b'x' * 201), 'gzip')


@pytest.mark.parametrize('record',[b'Package: htop\nPackage: bad\nArchitecture: amd64\n',
    b'Package: htop\n',b'Package: bad/name\nArchitecture: amd64\n'])
def test_malformed_package_record(record):
    with pytest.raises(CatalogError):
        acquire.index_names(lzma.compress(record))


def fake_catalog():
    catalog = fixture()
    envelopes, payloads, responses = {}, {}, {}
    for source in catalog['sources']:
        name = source['id']
        root = source['uri'] + 'dists/' + source['suite'] + '/'
        envelope = ('signed fixture ' + name).encode()
        fields = {
            'Origin': source['origin'], 'Label': source['label'],
            'Codename': source['codename'],
            'Date': 'Tue, 20 Oct 2026 00:00:00 UTC',
            'Architectures': 'amd64 all',
            'Components': 'updates/main' if name == 'trixie-security' else 'main',
        }
        if source['role'] == 'base':
            fields['Acquire-By-Hash'] = 'yes'
        if source['freshness']['mode'] == 'signed-valid-until':
            fields['Valid-Until'] = 'Tue, 27 Oct 2026 00:00:00 UTC'
        if name == 'trixie':
            source['freshness']['inrelease_sha256'] = hashlib.sha256(envelope).hexdigest()
        records = (b'Package: tailscale\nArchitecture: amd64\n\n'
                   if name == 'tailscale'
                   else b'Package: htop\nArchitecture: amd64\n\n'
                   if name == 'trixie' else b'')
        specs = ([('main/binary-amd64/Packages.gz', gzip.compress(records)),
                  ('main/binary-all/Packages.gz',
                   gzip.compress(b'Package: tailscale-archive-keyring\nArchitecture: all\n\n'))]
                 if name == 'tailscale'
                 else [('main/binary-amd64/Packages.xz', lzma.compress(records))])
        checksum_lines = []
        for path, data in specs:
            sha = hashlib.sha256(data).hexdigest()
            checksum_lines.append(f' {sha} {len(data)} {path}\n')
            url = (root + path if name == 'tailscale'
                   else root + path.rsplit('/', 1)[0] + '/by-hash/SHA256/' + sha)
            responses[url] = data
        payload = (''.join(k + ': ' + v + '\n' for k, v in fields.items())
                   + 'SHA256:\n' + ''.join(checksum_lines)).encode()
        envelopes[name] = envelope
        payloads[envelope] = payload
        responses[root + 'InRelease'] = envelope
    requested = []
    def fetch(url, limit):
        requested.append(url)
        return responses[url]
    def verify(envelope, keyring, source):
        return payloads[envelope], ['A' * 40]
    return catalog, fetch, verify, envelopes, payloads, responses, requested


def test_complete_configured_target_with_authenticated_empty_updates():
    catalog, fetch, verify, envelopes, payloads, responses, requested = fake_catalog()
    results = acquire.acquire_catalog(
        catalog, lambda _: b'key', datetime(2026, 10, 21, tzinfo=timezone.utc),
        fetch, verify)
    assert len(results) == 4
    assert results[0]['names'] == {'htop'}
    assert results[3]['names'] == {'tailscale', 'tailscale-archive-keyring'}
    assert results[3]['role'] == 'build'
    assert results[3]['source_url'].startswith('https://pkgs.tailscale.com/')
    assert len(results[3]['indexes']) == 2
    assert results[3]['keyring_sha256'] == 'e' * 64
    assert len(requested) == 9
    assert all(url.startswith(('https://deb.debian.org/', 'https://pkgs.tailscale.com/'))
               for url in requested)
    assert not any(url.endswith(('.gpg', '.list')) for url in requested)


def test_acquisition_runs_no_package_tool_and_claims_no_installability(monkeypatch):
    catalog, fetch, verify, *_ = fake_catalog()
    def forbidden(*args, **kwargs):
        raise AssertionError(f'unexpected process: {args!r}')
    for name in ('Popen', 'run', 'call', 'check_call', 'check_output'):
        monkeypatch.setattr(acquire.subprocess, name, forbidden)
    monkeypatch.setattr(acquire.os, 'system', forbidden)
    results = acquire.acquire_catalog(
        catalog, lambda _: b'key', datetime(2026, 10, 21, tzinfo=timezone.utc),
        fetch, verify)
    claims = {'installable', 'installed', 'solvable', 'transaction', 'add_supported'}
    assert all(not claims & set(result) for result in results)


def test_signature_verifier_is_the_only_native_process(monkeypatch):
    source = fixture()['sources'][0]
    source['keyring_sha256'] = hashlib.sha256(b'key').hexdigest()
    commands = []
    def popen(command, **kwargs):
        commands.append(command)
        raise OSError('stop before execution')
    monkeypatch.setattr(acquire.subprocess, 'Popen', popen)
    with pytest.raises(CatalogError, match='unavailable'):
        acquire.verify_inrelease(
            b'-----BEGIN PGP SIGNED MESSAGE-----\n', b'key', source, verifier='/opt/gpg')
    [command] = commands
    assert command[0] == '/opt/gpg' and '--decrypt' in command
    assert {'--no-auto-key-retrieve', '--no-auto-key-import', '--no-default-keyring'} <= set(command)
    assert not {'--import', '--recv-keys', '--fetch-keys'} & set(command)


@pytest.mark.parametrize(
    'failure',
    ['missing-security', 'missing-tailscale', 'bad-index-hash',
     'expired-security', 'wrong-identity', 'wrong-base-pin'])
def test_no_partial_catalog_result(failure):
    catalog, fetch, verify, envelopes, payloads, responses, requested = fake_catalog()
    if failure in {'missing-security', 'missing-tailscale'}:
        blocked = 'trixie-security' if failure == 'missing-security' else 'pkgs.tailscale.com'
        old = fetch
        def fetch(url, limit):
            if blocked in url:
                raise CatalogError('source unavailable')
            return old(url, limit)
    elif failure == 'bad-index-hash':
        for url in list(responses):
            if not url.endswith('/InRelease'):
                responses[url] = b'bad'
    elif failure == 'expired-security':
        key = envelopes['trixie-security']
        payloads[key] = payloads[key].replace(b'27 Oct', b'20 Oct')
    elif failure == 'wrong-identity':
        key = envelopes['tailscale']
        payloads[key] = payloads[key].replace(b'Origin: Tailscale', b'Origin: Forged')
    else:
        catalog['sources'][0]['freshness']['inrelease_sha256'] = '0' * 64
    with pytest.raises(CatalogError):
        acquire.acquire_catalog(
            catalog, lambda _: b'key',
            datetime(2026, 10, 21, tzinfo=timezone.utc), fetch, verify)
    assert requested


@pytest.mark.skipif(not acquire.shutil.which('gpg'), reason='native GnuPG verifier not installed')
def test_real_debian_signature_and_tamper(tmp_path,monkeypatch):
    # Public frozen metadata from the reviewed Debian source observation.
    root=Path(__file__).resolve().parents[1]
    envelope=(root/'tests/fixtures/package-catalog/debian-trixie.InRelease').read_bytes()
    keyring=(root/'config/package-keys/debian-trixie.pgp').read_bytes()
    source=fixture()['sources'][0]
    source['keyring_sha256']=hashlib.sha256(keyring).hexdigest()
    source['primary_fingerprints']=['04B54C3CDCA79751B16BC6B5225629DF75B188BD']
    monkeypatch.setattr(acquire.tempfile,'tempdir',str(tmp_path))
    payload,signers=acquire.verify_inrelease(envelope,keyring,source)
    assert '04B54C3CDCA79751B16BC6B5225629DF75B188BD' in signers
    assert acquire.parse_release(payload)[0]['Codename']=='trixie'
    with pytest.raises(CatalogError,match='verification failed'):
        acquire.verify_inrelease(envelope.replace(b'Origin: Debian',b'Origin: Forged'),keyring,source)
    source['primary_fingerprints']=['F'*40]
    with pytest.raises(CatalogError,match='declared primary'):
        acquire.verify_inrelease(envelope,keyring,source)


@pytest.mark.skipif(not acquire.shutil.which('gpg'), reason='native GnuPG verifier not installed')
def test_real_tailscale_signature_and_trust_pin(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    envelope = (root / 'tests/fixtures/package-catalog/tailscale-trixie.InRelease').read_bytes()
    keyring = (root / 'config/package-keys/tailscale-trixie.gpg').read_bytes()
    source = fixture()['sources'][3]
    source['keyring_sha256'] = hashlib.sha256(keyring).hexdigest()
    source['primary_fingerprints'] = ['2596A99EAAB33821893C0A79458CA832957F5868']
    monkeypatch.setattr(acquire.tempfile, 'tempdir', str(tmp_path))
    payload, signers = acquire.verify_inrelease(envelope, keyring, source)
    fields, checksums = acquire.parse_release(payload)
    assert signers == source['primary_fingerprints']
    assert fields['Origin'] == 'Tailscale'
    assert 'main/binary-amd64/Packages.gz' in checksums


def test_xz_dictionary_memory_bound():
    # An xz header can request far more decoder memory than the output size.
    data = lzma.compress(b'Package: htop\nArchitecture: amd64\n\n',
                         filters=[{'id': lzma.FILTER_LZMA2, 'dict_size': 256 * 1024 * 1024}])
    with pytest.raises(CatalogError, match='invalid compressed index'):
        acquire.index_names(data)


@pytest.mark.parametrize('algorithm', ['2', '17', '19', '999'])
def test_unreviewed_signature_public_key_algorithm(algorithm):
    data = status().replace(' 4 0 1 8 ', ' 4 0 ' + algorithm + ' 8 ')
    with pytest.raises(CatalogError, match='algorithm'):
        acquire.valid_signers(data, ['A' * 40])


def test_observed_eddsa_signature_algorithm():
    assert acquire.valid_signers(status().replace(' 4 0 1 8 ', ' 4 0 22 8 '), ['A' * 40]) == ['A' * 40]
