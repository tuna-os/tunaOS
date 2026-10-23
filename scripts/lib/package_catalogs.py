"""Authoring-only base-repository catalog schema and reviewed observation binding."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit


class CatalogError(ValueError):
    pass


def exact(value, fields, where):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise CatalogError(f'{where}: unknown or missing fields')


def unique_strings(value, where):
    if (not isinstance(value, list) or not value
            or any(not isinstance(x, str) or not x or x.strip() != x for x in value)
            or len(set(value)) != len(value)):
        raise CatalogError(f'{where}: expected distinct nonempty strings')


def relative_path(value):
    if (not isinstance(value, str) or not value or '\\' in value
            or any(ord(c) < 32 for c in value)
            or PurePosixPath(value).is_absolute()
            or any(x in ('', '.', '..') for x in value.split('/'))):
        raise CatalogError('expected safe repository-relative path')


def digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise CatalogError('expected SHA-256')


def validate(catalog):
    exact(catalog, ('schema_version', 'coverage', 'variant', 'family', 'os_id', 'release', 'platforms',
                   'observed_base_image', 'source_observation',
                   'source_observation_sha256', 'sources'), 'catalog')
    if catalog['coverage'] != 'base-image-only':
        raise CatalogError('only base-image repository coverage is supported')
    if not isinstance(catalog['variant'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', catalog['variant']):
        raise CatalogError('invalid catalog variant')
    if type(catalog['schema_version']) is not int or catalog['schema_version'] != 1:
        raise CatalogError('unsupported catalog schema version')
    if (catalog['family'], catalog['os_id'], catalog['release']) != ('apt', 'debian', 'trixie'):
        raise CatalogError('unsupported family/release; never omit this target')
    if catalog['platforms'] != ['linux/amd64']:
        raise CatalogError('initial adapter supports linux/amd64 only')
    if not isinstance(catalog['observed_base_image'], str) or not re.fullmatch(
            r'docker\.io/library/debian:trixie@sha256:[0-9a-f]{64}', catalog['observed_base_image']):
        raise CatalogError('expected immutable supported base image observation')
    relative_path(catalog['source_observation'])
    digest(catalog['source_observation_sha256'])
    sources = catalog['sources']
    if not isinstance(sources, list) or not sources:
        raise CatalogError('missing sources')
    ids = set()
    suites = set()
    for source in sources:
        exact(source, ('id', 'uri', 'suite', 'origin', 'codename', 'components',
                       'keyring', 'keyring_sha256', 'primary_fingerprints',
                       'freshness', 'clock_skew_seconds'), 'source')
        name = source['id']
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name) or name in ids:
            raise CatalogError('invalid or duplicate source id')
        ids.add(name)
        suite = source['suite']
        if suite not in ('trixie', 'trixie-updates', 'trixie-security') or suite in suites:
            raise CatalogError('unsupported or duplicate suite')
        suites.add(suite)
        uri = source['uri']
        if not isinstance(uri, str):
            raise CatalogError('expected HTTPS source')
        parsed = urlsplit(uri)
        expected_path = '/debian-security/' if suite == 'trixie-security' else '/debian/'
        if (parsed.scheme != 'https' or parsed.netloc != 'deb.debian.org'
                or parsed.path != expected_path or parsed.query or parsed.fragment):
            raise CatalogError('unsupported source URI; requires adapter review')
        if source['origin'] != 'Debian' or source['codename'] != suite or source['components'] != ['main']:
            raise CatalogError('unsupported archive identity/components')
        relative_path(source['keyring'])
        digest(source['keyring_sha256'])
        unique_strings(source['primary_fingerprints'], 'fingerprints')
        if any(not re.fullmatch(r'[0-9A-F]{40}', x) for x in source['primary_fingerprints']):
            raise CatalogError('expected full primary fingerprint')
        freshness = source['freshness']
        if suite == 'trixie':
            exact(freshness, ('mode', 'inrelease_sha256'), 'base freshness')
            if freshness['mode'] != 'pinned-release':
                raise CatalogError('base metadata requires explicit signed-envelope pin')
            digest(freshness['inrelease_sha256'])
        else:
            exact(freshness, ('mode', 'max_age_seconds'), 'update freshness')
            age = freshness['max_age_seconds']
            if (freshness['mode'] != 'signed-valid-until' or type(age) is not int
                    or not 0 < age <= 604800):
                raise CatalogError('updates/security require bounded signed validity')
        skew = source['clock_skew_seconds']
        if type(skew) is not int or not 0 <= skew <= 10:
            raise CatalogError('invalid clock-skew bound')
    if suites != {'trixie', 'trixie-updates', 'trixie-security'}:
        raise CatalogError('incomplete configured base source set')
    return catalog


def check_authenticated_dates(source, fields, now, envelope_sha256):
    """Only call after signature verification; this function does not authenticate."""
    if now.tzinfo is None:
        raise CatalogError('clock must include timezone')
    def date(name):
        try:
            value = parsedate_to_datetime(fields[name])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise CatalogError(f'invalid signed {name}') from exc
        if value.tzinfo is None:
            raise CatalogError(f'signed {name} needs timezone')
        return value.astimezone(timezone.utc)
    issued = date('Date')
    if issued > now + timedelta(seconds=source['clock_skew_seconds']):
        raise CatalogError('signed Date exceeds future clock-skew bound')
    freshness = source['freshness']
    if freshness['mode'] == 'pinned-release':
        if envelope_sha256 != freshness['inrelease_sha256']:
            raise CatalogError('base metadata changed; explicit observation refresh required')
        expiry = None
    else:
        try:
            expiry = issued + timedelta(seconds=freshness['max_age_seconds'])
        except OverflowError as exc:
            raise CatalogError('signed Date exceeds supported range') from exc
    if 'Valid-Until' in fields:
        validity = date('Valid-Until')
        if validity < issued:
            raise CatalogError('Valid-Until precedes Date')
        expiry = validity if expiry is None else min(expiry, validity)
    elif freshness['mode'] != 'pinned-release':
        raise CatalogError('missing signed Valid-Until')
    if expiry is not None and now >= expiry:
        raise CatalogError('signed metadata expired')
    return expiry


def index_path(source, release, *, architecture, component):
    """Exact Debian layout, after signature verification and before checksum lookup."""
    if architecture != 'amd64' or component != 'main':
        raise CatalogError('unsupported architecture/component')
    suite = source['suite']
    labels = {'trixie': 'Debian', 'trixie-updates': 'Debian', 'trixie-security': 'Debian-Security'}
    if suite not in labels or release.get('Origin') != source['origin'] or release.get('Codename') != suite or release.get('Label') != labels[suite]:
        raise CatalogError('signed archive identity mismatch')
    native_component = 'updates/main' if suite == 'trixie-security' else 'main'
    if architecture not in release.get('Architectures', '').split() or native_component not in release.get('Components', '').split():
        raise CatalogError('signed archive does not declare selected architecture/component')
    return 'main/binary-amd64/Packages.xz'


def validate_document(document):
    catalogs = document.get('package_catalogs', {})
    if not isinstance(catalogs, dict):
        raise CatalogError('package_catalogs: expected table')
    for name, catalog in catalogs.items():
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name):
            raise CatalogError('invalid catalog id')
        validate(catalog)
        if catalog['variant'] not in document['variants']:
            raise CatalogError('catalog refers to unknown variant')
    # No file, network, current-time or stale-observation check on the build path.


def select(document, catalog_id, variant, release, platform):
    catalogs = document.get('package_catalogs', {})
    if catalog_id not in catalogs:
        raise CatalogError('catalog unavailable; no target is silently omitted')
    catalog = validate(catalogs[catalog_id])
    if variant != catalog['variant'] or release != catalog['release'] or platform not in catalog['platforms']:
        raise CatalogError('catalog does not cover the explicit variant/release/platform')
    entry = document['variants'].get(variant)
    if entry is None or entry['base_image'] != catalog['observed_base_image']:
        raise CatalogError('base image changed; refresh the reviewed source observation before lookup')
    declared = set(entry['platforms'])
    for flavor in entry['flavors']:
        declared.update(flavor.get('platforms', []))
    if platform not in declared:
        raise CatalogError('platform is not declared for this variant')
    return catalog


def _json(data):
    import json
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CatalogError('duplicate observation JSON key')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CatalogError('invalid observation JSON') from exc


def _public_file(root, relative, limit=1024 * 1024):
    import os
    import stat
    from pathlib import Path
    relative_path(relative)
    root = Path(root).resolve()
    candidate = root
    for part in relative.split('/'):
        candidate = candidate / part
        if candidate.is_symlink():
            raise CatalogError('trust/observation paths must not contain symlinks')
    descriptor = os.open(candidate, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise CatalogError('trust/observation input must be a regular file')
        result = stream.read(limit + 1)
    if len(result) > limit:
        raise CatalogError('trust/observation input exceeds size bound')
    return result


def _native_sources(text):
    """Only the observed Debian deb822 subset; unknown syntax fails closed."""
    records = []
    for paragraph in text.strip().split('\n\n'):
        record = {}
        for line in paragraph.splitlines():
            if line.startswith('#'):
                continue
            key, separator, value = line.partition(':')
            if not separator or key in record:
                raise CatalogError('unsupported observed source syntax')
            record[key] = value.strip()
        exact(record, ('Types', 'URIs', 'Suites', 'Components', 'Signed-By'), 'observed source')
        if record['Types'] != 'deb' or record['Components'] != 'main' or record['Signed-By'] != '/usr/share/keyrings/debian-archive-keyring.pgp':
            raise CatalogError('unsupported observed source/keyring declaration')
        uri = record['URIs']
        if uri not in ('http://deb.debian.org/debian', 'http://deb.debian.org/debian-security'):
            raise CatalogError('unsupported observed URI')
        for suite in record['Suites'].split():
            item = ('https://' + uri[len('http://'):] + '/', suite, ('main',))
            if item in records:
                raise CatalogError('duplicate observed source')
            records.append(item)
    return records


def bind_observation(catalog, config_directory):
    """Verify reviewed source observation and trust pins, not a fresh OCI pull.

    The configuration/parent directory is trusted, as for the offline editor.
    Hash pins bind reviewed extracted-file claims; they are not signatures on the
    observation. Native metadata signatures are independently checked afterward.
    """
    import hashlib
    raw = _public_file(config_directory, catalog['source_observation'])
    if hashlib.sha256(raw).hexdigest() != catalog['source_observation_sha256']:
        raise CatalogError('source observation differs from reviewed pin')
    observation = _json(raw)
    required = ('schema_version', 'base_image', 'platform', 'manifest_sha256', 'layers',
                'files', 'apt_source_members', 'observed_at', 'base_inrelease_sha256',
                'upstream_artifact_commit', 'source_text', 'os_release_text',
                'image_index', 'image_manifest')
    exact(observation, required, 'observation')
    if type(observation['schema_version']) is not int or observation['schema_version'] != 1:
        raise CatalogError('unsupported observation schema')
    if observation['base_image'] != catalog['observed_base_image'] or observation['platform'] != 'linux/amd64':
        raise CatalogError('observation does not match selected image/platform')
    for key in ('source_text', 'os_release_text', 'image_index', 'image_manifest'):
        if not isinstance(observation[key], str):
            raise CatalogError('observation text field is invalid')
    index_bytes = observation['image_index'].encode()
    manifest_bytes = observation['image_manifest'].encode()
    if ('sha256:' + hashlib.sha256(index_bytes).hexdigest() != catalog['observed_base_image'].split('@')[1]
            or hashlib.sha256(manifest_bytes).hexdigest() != observation['manifest_sha256']):
        raise CatalogError('observation OCI identity mismatch')
    index, manifest = _json(index_bytes), _json(manifest_bytes)
    if not isinstance(index, dict) or not isinstance(manifest, dict) or not isinstance(index.get('manifests'), list) or any(not isinstance(x, dict) for x in index['manifests']):
        raise CatalogError('invalid observed OCI structure')
    entries = [x for x in index.get('manifests', []) if x.get('platform') == {'architecture': 'amd64', 'os': 'linux'}]
    if len(entries) != 1 or entries[0].get('digest') != 'sha256:' + observation['manifest_sha256'] or entries[0].get('size') != len(manifest_bytes) or manifest.get('layers') != observation['layers']:
        raise CatalogError('observation OCI platform/layer mismatch')
    source_path = 'etc/apt/sources.list.d/debian.sources'
    os_path = 'usr/lib/os-release'
    key_path = 'usr/share/keyrings/debian-archive-keyring.pgp'
    if observation['apt_source_members'] != [{'path': source_path, 'type': '0',
            'size': len(observation['source_text'].encode()), 'linkname': ''}]:
        raise CatalogError('observed base has unhandled apt source files')
    files = observation['files']
    exact(files, (source_path, os_path, key_path), 'observed files')
    for path, content in ((source_path, observation['source_text'].encode()), (os_path, observation['os_release_text'].encode())):
        if files[path] != {'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}:
            raise CatalogError('observed file identity mismatch')
    os_lines = observation['os_release_text'].splitlines()
    os_keys = [line.partition('=')[0] for line in os_lines if line and not line.startswith('#')]
    if len(os_keys) != len(set(os_keys)) or os_lines.count('ID=debian') != 1 or os_lines.count('VERSION_CODENAME=trixie') != 1:
        raise CatalogError('observed operating system does not match catalog')
    declared = [(s['uri'], s['suite'], tuple(s['components'])) for s in catalog['sources']]
    if sorted(_native_sources(observation['source_text'])) != sorted(declared):
        raise CatalogError('catalog does not cover the exact observed base source set')
    base = next(s for s in catalog['sources'] if s['suite'] == 'trixie')
    if observation['base_inrelease_sha256'] != base['freshness']['inrelease_sha256']:
        raise CatalogError('base metadata pin does not match reviewed observation')
    keys = {}
    for source in catalog['sources']:
        content = _public_file(config_directory, source['keyring'])
        if files[key_path] != {'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)} or files[key_path]['sha256'] != source['keyring_sha256']:
            raise CatalogError('keyring differs from observed and reviewed trust bytes')
        keys[source['id']] = content
    return observation, keys
