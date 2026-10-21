"""Synthetic schema/freshness tests; no signature or live-image proof is claimed."""
from copy import deepcopy
from datetime import datetime, timezone
import pytest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.package_catalogs import CatalogError, check_authenticated_dates, index_path, validate
from lib import package_catalogs


def fixture():
    sources = []
    for suite in ('trixie', 'trixie-updates', 'trixie-security'):
        sources.append(dict(id=suite, uri='https://deb.debian.org/' + (
            'debian-security/' if suite == 'trixie-security' else 'debian/'),
            suite=suite, origin='Debian', codename=suite, components=['main'],
            keyring='keys/fixture.pgp', keyring_sha256='a' * 64,
            primary_fingerprints=['A' * 40], freshness=(dict(mode='pinned-release', inrelease_sha256='d' * 64) if suite == 'trixie' else dict(mode='signed-valid-until', max_age_seconds=604800)), clock_skew_seconds=10))
    return dict(schema_version=1, coverage='base-image-only', variant='flounder', family='apt', os_id='debian', release='trixie',
                platforms=['linux/amd64'], observed_base_image=
                'docker.io/library/debian:trixie@sha256:' + 'b' * 64,
                source_observation='observations/fixture.json',
                source_observation_sha256='c' * 64, sources=sources)


def test_complete_fixture():
    data = fixture()
    assert validate(data) == data


@pytest.mark.parametrize('key,value', [
    ('coverage', 'full-cell'), ('variant', '../bad'), ('schema_version', True), ('schema_version', 2), ('family', 'fedora'),
    ('release', 'sid'), ('os_id', 'ubuntu'), ('platforms', ['linux/arm64']),
    ('observed_base_image', 'docker.io/library/debian:trixie'),
    ('source_observation', '../secret'), ('source_observation', '/etc/key'),
    ('source_observation_sha256', 'c' * 63), ('sources', []),
])
def test_catalog_rejects(key, value):
    data = fixture()
    data[key] = value
    with pytest.raises(CatalogError):
        validate(data)


@pytest.mark.parametrize('key,value', [
    ('uri', 'http://deb.debian.org/debian/'), ('uri', 'https://user@deb.debian.org/debian/'),
    ('uri', 'https://deb.debian.org/debian/?key=x'), ('uri', 'https://evil.test/debian/'),
    ('suite', 'stable'), ('origin', 'Ubuntu'), ('codename', 'sid'),
    ('components', ['main', 'non-free']), ('keyring', '../fixture'),
    ('keyring_sha256', 'bad'), ('primary_fingerprints', ['A' * 16]),
    ('primary_fingerprints', ['A' * 40, 'A' * 40]),
    ('freshness', {'mode': 'unbounded'}),
    ('clock_skew_seconds', 11), ('freshness', {'mode': 'pinned-release', 'inrelease_sha256': 'bad'}),
])
def test_source_rejects(key, value):
    data = fixture()
    data['sources'][0][key] = value
    with pytest.raises(CatalogError):
        validate(data)


@pytest.mark.parametrize('change', ['unknown', 'missing', 'duplicate', 'absent-security', 'weaken-security'])
def test_complete_set_and_known_schema(change):
    data = fixture()
    if change == 'unknown':
        data['fallback'] = True
    elif change == 'missing':
        del data['release']
    elif change == 'duplicate':
        data['sources'].append(deepcopy(data['sources'][0]))
    elif change == 'absent-security':
        data['sources'].pop()
    else:
        data['sources'][2]['freshness'] = {'mode': 'pinned-release', 'inrelease_sha256': 'd' * 64}
    with pytest.raises(CatalogError):
        validate(data)


NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


def test_pinned_base_without_validity_is_explicitly_not_freshness_proof():
    source = fixture()['sources'][0]
    assert check_authenticated_dates(source, {'Date': 'Sat, 12 Sep 2026 07:55:41 UTC'}, NOW, 'd' * 64) is None
    with pytest.raises(CatalogError, match='refresh'):
        check_authenticated_dates(source, {'Date': 'Tue, 20 Oct 2026 00:00:00 UTC'}, NOW, 'e' * 64)


@pytest.mark.parametrize('fields', [
    {}, {'Date': 'invalid'}, {'Date': 'Tue, 20 Oct 2026 00:00:00'},
    {'Date': 'Wed, 21 Oct 2026 00:00:11 UTC'},
    {'Date': 'Tue, 20 Oct 2026 00:00:00 UTC', 'Valid-Until': 'Wed, 21 Oct 2026 00:00:00 UTC'},
    {'Date': 'Tue, 20 Oct 2026 00:00:00 UTC', 'Valid-Until': 'Mon, 19 Oct 2026 00:00:00 UTC'},
])
def test_signed_date_failures(fields):
    with pytest.raises(CatalogError):
        check_authenticated_dates(fixture()['sources'][0], fields, NOW, 'd' * 64)


def test_security_requires_valid_until():
    with pytest.raises(CatalogError):
        check_authenticated_dates(fixture()['sources'][2], {'Date': 'Tue, 20 Oct 2026 00:00:00 UTC'}, NOW, 'd' * 64)


def test_earlier_of_validity_and_age_cap():
    source = fixture()['sources'][1]
    fields = {'Date': 'Tue, 20 Oct 2026 00:00:00 UTC', 'Valid-Until': 'Wed, 28 Oct 2026 00:00:00 UTC'}
    assert check_authenticated_dates(source, fields, NOW, 'd' * 64) == datetime(2026, 10, 27, tzinfo=timezone.utc)
    fields['Valid-Until'] = 'Thu, 22 Oct 2026 00:00:00 UTC'
    assert check_authenticated_dates(source, fields, NOW, 'd' * 64) == datetime(2026, 10, 22, tzinfo=timezone.utc)


@pytest.mark.parametrize('mode,age', [('signed-valid-until', True), ('signed-valid-until', 604801), ('ignore', 604800)])
def test_no_expiry_downgrade(mode, age):
    data = fixture()
    data['sources'][1]['freshness'] = dict(mode=mode, max_age_seconds=age)
    with pytest.raises(CatalogError):
        validate(data)


def test_native_security_component_path():
    source = fixture()['sources'][2]
    fields = dict(Origin='Debian', Label='Debian-Security', Codename='trixie-security', Architectures='amd64 arm64', Components='updates/main updates/contrib')
    assert index_path(source, fields, architecture='amd64', component='main') == 'main/binary-amd64/Packages.xz'
    for key, value in [('Origin','Ubuntu'), ('Codename','trixie'), ('Architectures','arm64'), ('Components','other/main'), ('Label','Debian')]:
        with pytest.raises(CatalogError):
            index_path(source, dict(fields, **{key: value}), architecture='amd64', component='main')


def observed_catalog(root=ROOT):
    import hashlib,json
    catalog=fixture()
    observation_path='config/package-observations/flounder-amd64.json'
    raw=(root/observation_path).read_bytes();observation=json.loads(raw)
    catalog.update(observed_base_image=observation['base_image'], source_observation=observation_path,
                   source_observation_sha256=hashlib.sha256(raw).hexdigest())
    for source in catalog['sources']:
        source['keyring']='config/package-keys/debian-trixie.pgp'
        source['keyring_sha256']=observation['files']['usr/share/keyrings/debian-archive-keyring.pgp']['sha256']
        if source['suite']=='trixie':source['freshness']['inrelease_sha256']=observation['base_inrelease_sha256']
    return catalog


def test_actual_observation_binding():
    observation,keys=package_catalogs.bind_observation(observed_catalog(),ROOT)
    assert observation['platform']=='linux/amd64' and len(keys)==3


@pytest.mark.parametrize('change',['image','platform','sources','key','manifest','inventory','base-metadata'])
def test_observation_binding_rejects_tampering(tmp_path,change):
    import json,hashlib,shutil
    shutil.copytree(ROOT/'config',tmp_path/'config')
    catalog=observed_catalog(tmp_path)
    path=tmp_path/catalog['source_observation'];observation=json.loads(path.read_text())
    if change=='image':observation['base_image']='wrong'
    elif change=='platform':observation['platform']='linux/arm64'
    elif change=='sources':observation['source_text']=observation['source_text'].replace('Suites: trixie trixie-updates','Suites: trixie')
    elif change=='key':(tmp_path/catalog['sources'][0]['keyring']).write_bytes(b'wrong key')
    elif change=='manifest':observation['image_manifest']='{}'
    elif change=='inventory':observation['apt_source_members'].append(dict(path='etc/apt/sources.list',type='0',size=1,linkname=''))
    else:observation['base_inrelease_sha256']='0'*64
    raw=(json.dumps(observation)+'\n').encode();path.write_bytes(raw)
    catalog['source_observation_sha256']=hashlib.sha256(raw).hexdigest()
    with pytest.raises(CatalogError):package_catalogs.bind_observation(catalog,tmp_path)


def test_stale_observation_only_blocks_lookup():
    catalog=observed_catalog()
    document=dict(package_catalogs={'debian':catalog},variants={'flounder':dict(
        base_image='docker.io/library/debian:trixie@sha256:'+'f'*64,
        platforms=['linux/amd64'],flavors=[])})
    package_catalogs.validate_document(document)
    with pytest.raises(CatalogError,match='refresh'):
        package_catalogs.select(document,'debian','flounder','trixie','linux/amd64')


@pytest.mark.parametrize('relative',['../key','/etc/key','keys//key','keys/./key','keys/../key','keys\\key'])
def test_no_trust_path_escape(relative):
    with pytest.raises(CatalogError):package_catalogs._public_file(ROOT,relative)


def test_no_symlink_or_fifo_trust_inputs(tmp_path):
    import os
    (tmp_path/'key').write_text('public fixture')
    (tmp_path/'link').symlink_to('key')
    with pytest.raises(CatalogError):package_catalogs._public_file(tmp_path,'link')
    os.mkfifo(tmp_path/'fifo')
    with pytest.raises(CatalogError):package_catalogs._public_file(tmp_path,'fifo')


@pytest.mark.parametrize('field,value', [
    ('files', []), ('files', None), ('manifest_sha256', 42),
    ('source_text', []), ('image_index', None), ('schema_version', True),
    ('apt_source_members', {}), ('os_release_text', 'ID=debian\nID=other\nVERSION_CODENAME=trixie'),
])
def test_malformed_observation_controlled(tmp_path, field, value):
    import hashlib
    import json
    import shutil
    shutil.copytree(ROOT / 'config', tmp_path / 'config')
    catalog = observed_catalog(tmp_path)
    path = tmp_path / catalog['source_observation']
    observation = json.loads(path.read_text())
    observation[field] = value
    raw = json.dumps(observation).encode()
    path.write_bytes(raw)
    catalog['source_observation_sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(CatalogError):
        package_catalogs.bind_observation(catalog, tmp_path)


def test_trust_input_byte_bound(tmp_path):
    (tmp_path / 'key').write_bytes(b'12345')
    with pytest.raises(CatalogError, match='size bound'):
        package_catalogs._public_file(tmp_path, 'key', limit=4)


def test_primary_hook_is_structural_only(monkeypatch):
    from lib import tunaos_config
    document = tunaos_config.load()
    baseline = tunaos_config.matrix(document)
    # No metadata files need to exist and no observation needs to be current
    # for a build to validate and emit its unchanged matrix.
    for catalog in document['package_catalogs'].values():
        catalog['source_observation'] = 'absent/observation.json'
        catalog['observed_base_image'] = 'docker.io/library/debian:trixie@sha256:' + 'f' * 64
    monkeypatch.setattr(tunaos_config.package_catalog_schema(), '_public_file', lambda *a: pytest.fail('build read observation'))
    assert tunaos_config.matrix(tunaos_config.validate(document)) == baseline
    document.pop('package_catalogs')
    assert tunaos_config.matrix(tunaos_config.validate(document)) == baseline


def test_primary_hook_rejects_unknown_catalog_fields():
    from lib import tunaos_config
    document = tunaos_config.load()
    document['package_catalogs']['debian-trixie']['unexpected'] = True
    with pytest.raises(tunaos_config.ConfigError, match='package_catalogs'):
        tunaos_config.validate(document)
