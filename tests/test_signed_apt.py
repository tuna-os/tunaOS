"""Offline adversarial acquisition tests, with explicit fake transport/verifier."""
from datetime import datetime, timezone
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
    data=b'Package: htop\nArchitecture: amd64\n\nPackage: foreign\nArchitecture: arm64\n\n'
    assert acquire.index_names(lzma.compress(data))=={'htop'}
    assert acquire.index_names(lzma.compress(b''))==set()
    with pytest.raises(CatalogError):
        acquire.index_names(lzma.compress(data)+b'trailing')
    monkeypatch.setattr(acquire,'MAX_INDEX',200)
    with pytest.raises(CatalogError):
        acquire.index_names(lzma.compress(b'x'*201))


@pytest.mark.parametrize('record',[b'Package: htop\nPackage: bad\nArchitecture: amd64\n',
    b'Package: htop\n',b'Package: bad/name\nArchitecture: amd64\n'])
def test_malformed_package_record(record):
    with pytest.raises(CatalogError):
        acquire.index_names(lzma.compress(record))


def fake_catalog():
    catalog=fixture();envelopes={};payloads={};indexes={}
    for source in catalog['sources']:
        suite=source['suite'];envelope=('signed fixture '+suite).encode()
        data=lzma.compress(b'Package: htop\nArchitecture: amd64\n\n' if suite=='trixie' else b'')
        sha=hashlib.sha256(data).hexdigest()
        fields={'Origin':'Debian','Label':'Debian-Security' if suite=='trixie-security' else 'Debian',
                'Codename':suite,'Date':'Tue, 20 Oct 2026 00:00:00 UTC',
                'Architectures':'amd64 all','Components':'updates/main' if suite=='trixie-security' else 'main',
                'Acquire-By-Hash':'yes'}
        if suite!='trixie':fields['Valid-Until']='Tue, 27 Oct 2026 00:00:00 UTC'
        else:source['freshness']['inrelease_sha256']=hashlib.sha256(envelope).hexdigest()
        payload=(''.join(k+': '+v+'\n' for k,v in fields.items())+'SHA256:\n '+sha+' '+str(len(data))+' main/binary-amd64/Packages.xz\n').encode()
        envelopes[suite]=envelope;payloads[envelope]=payload;indexes[sha]=data
    def fetch(url,limit):
        if url.endswith('/InRelease'):return envelopes[url.split('/')[-2]]
        return indexes[url.split('/')[-1]]
    def verify(envelope,keyring,source):return payloads[envelope],['A'*40]
    return catalog,fetch,verify,envelopes,payloads,indexes


def test_all_three_sources_complete_with_authenticated_empty_updates():
    catalog,fetch,verify,*_=fake_catalog()
    results=acquire.acquire_catalog(catalog,lambda _:b'key',datetime(2026,10,21,tzinfo=timezone.utc),fetch,verify)
    assert len(results)==3 and results[0]['names']=={'htop'} and results[1]['names']==set()


@pytest.mark.parametrize('failure',['missing-security','bad-index-hash','expired-security','wrong-identity','wrong-base-pin'])
def test_no_partial_catalog_result(failure):
    catalog,fetch,verify,envelopes,payloads,indexes=fake_catalog()
    if failure=='missing-security':
        old=fetch
        def fetch(url,limit):
            if '/trixie-security/' in url:raise CatalogError('source unavailable')
            return old(url,limit)
    elif failure=='bad-index-hash':
        for sha in indexes:indexes[sha]=b'bad'
    elif failure=='expired-security':
        key=envelopes['trixie-security'];payloads[key]=payloads[key].replace(b'27 Oct',b'20 Oct')
    elif failure=='wrong-identity':
        key=envelopes['trixie-security'];payloads[key]=payloads[key].replace(b'Origin: Debian',b'Origin: Ubuntu')
    else:catalog['sources'][0]['freshness']['inrelease_sha256']='0'*64
    with pytest.raises(CatalogError):
        acquire.acquire_catalog(catalog,lambda _:b'key',datetime(2026,10,21,tzinfo=timezone.utc),fetch,verify)


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


def test_xz_dictionary_memory_bound():
    # An xz header can request far more decoder memory than the output size.
    data = lzma.compress(b'Package: htop\nArchitecture: amd64\n\n',
                         filters=[{'id': lzma.FILTER_LZMA2, 'dict_size': 256 * 1024 * 1024}])
    with pytest.raises(CatalogError, match='invalid xz'):
        acquire.index_names(data)


@pytest.mark.parametrize('algorithm', ['2', '17', '19', '999'])
def test_unreviewed_signature_public_key_algorithm(algorithm):
    data = status().replace(' 4 0 1 8 ', ' 4 0 ' + algorithm + ' 8 ')
    with pytest.raises(CatalogError, match='algorithm'):
        acquire.valid_signers(data, ['A' * 40])


def test_observed_eddsa_signature_algorithm():
    assert acquire.valid_signers(status().replace(' 4 0 1 8 ', ' 4 0 22 8 '), ['A' * 40]) == ['A' * 40]
