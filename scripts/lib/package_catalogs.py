"""Trusted configured-target package catalog schema and observation binding."""
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
    exact(catalog, ('schema_version', 'coverage', 'variant', 'family', 'os_id', 'release',
                   'platforms', 'flavors', 'observed_base_image', 'source_observation',
                   'source_observation_sha256', 'target_observation',
                   'target_observation_sha256', 'sources'), 'catalog')
    if catalog['coverage'] != 'configured-target':
        raise CatalogError('only complete configured-target repository coverage is supported')
    if not isinstance(catalog['variant'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', catalog['variant']):
        raise CatalogError('invalid catalog variant')
    if type(catalog['schema_version']) is not int or catalog['schema_version'] != 2:
        raise CatalogError('unsupported catalog schema version')
    if (catalog['family'], catalog['os_id'], catalog['release']) != ('apt', 'debian', 'trixie'):
        raise CatalogError('unsupported family/release; never omit this target')
    if catalog['platforms'] != ['linux/amd64']:
        raise CatalogError('apt collector supports linux/amd64 only')
    if catalog['flavors'] != ['base', 'kde', 'xfce']:
        raise CatalogError('catalog must name the complete reviewed flavor set')
    if not isinstance(catalog['observed_base_image'], str) or not re.fullmatch(
            r'docker\.io/library/debian:trixie@sha256:[0-9a-f]{64}', catalog['observed_base_image']):
        raise CatalogError('expected immutable supported base image observation')
    for field in ('source_observation', 'target_observation'):
        relative_path(catalog[field])
    for field in ('source_observation_sha256', 'target_observation_sha256'):
        digest(catalog[field])
    sources = catalog['sources']
    if not isinstance(sources, list) or not sources:
        raise CatalogError('missing sources')
    ids = set()
    expected = {'trixie', 'trixie-updates', 'trixie-security', 'tailscale'}
    for source in sources:
        if not isinstance(source, dict):
            raise CatalogError('source: expected table')
        common = ('id', 'role', 'uri', 'suite', 'origin', 'label', 'codename',
                  'components', 'keyring', 'keyring_sha256', 'primary_fingerprints',
                  'freshness', 'clock_skew_seconds')
        fields = common + (('declaration_url', 'declaration_sha256', 'keyring_url')
                           if source.get('id') == 'tailscale' else ())
        exact(source, fields, 'source')
        name = source['id']
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name) or name in ids:
            raise CatalogError('invalid or duplicate source id')
        ids.add(name)
        suite = source['suite']
        if name in {'trixie', 'trixie-updates', 'trixie-security'}:
            expected_path = '/debian-security/' if name == 'trixie-security' else '/debian/'
            expected_label = 'Debian-Security' if name == 'trixie-security' else 'Debian'
            if (source['role'], suite, source['origin'], source['label'], source['codename'],
                    source['components']) != ('base', name, 'Debian', expected_label, name, ['main']):
                raise CatalogError('unsupported Debian archive identity/components')
            expected_host = 'deb.debian.org'
        elif name == 'tailscale':
            expected_path = '/stable/debian/'
            if (source['role'], suite, source['origin'], source['label'], source['codename'],
                    source['components']) != ('build', 'trixie', 'Tailscale', 'Tailscale',
                                               'trixie', ['main']):
                raise CatalogError('unsupported Tailscale archive identity/components')
            expected_host = 'pkgs.tailscale.com'
            if (source['declaration_url'] !=
                    'https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list'
                    or source['keyring_url'] !=
                    'https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg'):
                raise CatalogError('Tailscale build source differs from reviewed configuration')
            digest(source['declaration_sha256'])
        else:
            raise CatalogError('unsupported package source; adapter review required')
        uri = source['uri']
        if not isinstance(uri, str):
            raise CatalogError('expected HTTPS source')
        parsed = urlsplit(uri)
        if (parsed.scheme != 'https' or parsed.netloc != expected_host
                or parsed.path != expected_path or parsed.query or parsed.fragment):
            raise CatalogError('unsupported source URI; requires adapter review')
        relative_path(source['keyring'])
        digest(source['keyring_sha256'])
        unique_strings(source['primary_fingerprints'], 'fingerprints')
        if any(not re.fullmatch(r'[0-9A-F]{40}', x) for x in source['primary_fingerprints']):
            raise CatalogError('expected full primary fingerprint')
        freshness = source['freshness']
        if name == 'trixie':
            exact(freshness, ('mode', 'inrelease_sha256'), 'base freshness')
            if freshness['mode'] != 'pinned-release':
                raise CatalogError('base metadata requires explicit signed-envelope pin')
            digest(freshness['inrelease_sha256'])
        else:
            exact(freshness, ('mode', 'max_age_seconds'), 'dynamic freshness')
            expected_mode = 'signed-date' if name == 'tailscale' else 'signed-valid-until'
            age = freshness['max_age_seconds']
            if (freshness['mode'] != expected_mode or type(age) is not int
                    or not 0 < age <= 604800):
                raise CatalogError('dynamic metadata requires bounded signed freshness')
        skew = source['clock_skew_seconds']
        if type(skew) is not int or not 0 <= skew <= 10:
            raise CatalogError('invalid clock-skew bound')
    if ids != expected:
        missing = ', '.join(sorted(expected - ids)) or 'none'
        raise CatalogError(
            f'incomplete configured target source set; missing source ids: {missing}')
    return catalog


def signed_timestamp(fields, name='Date'):
    try:
        value = parsedate_to_datetime(fields[name])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise CatalogError(f'invalid signed {name}') from exc
    if value.tzinfo is None:
        raise CatalogError(f'signed {name} needs timezone')
    return value.astimezone(timezone.utc)


def check_authenticated_dates(source, fields, now, envelope_sha256):
    """Only call after signature verification; this function does not authenticate."""
    if now.tzinfo is None:
        raise CatalogError('clock must include timezone')
    issued = signed_timestamp(fields)
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
        validity = signed_timestamp(fields, 'Valid-Until')
        if validity < issued:
            raise CatalogError('Valid-Until precedes Date')
        expiry = validity if expiry is None else min(expiry, validity)
    elif freshness['mode'] == 'signed-valid-until':
        raise CatalogError('missing signed Valid-Until')
    if expiry is not None and now >= expiry:
        raise CatalogError('signed metadata expired')
    return expiry


def index_path(source, release, *, architecture, component):
    """First native index path, after signature verification and identity checks."""
    return index_specs(source, release, architecture=architecture, component=component)[0]['path']


def index_specs(source, release, *, architecture, component):
    if architecture != 'amd64' or component != 'main':
        raise CatalogError('unsupported architecture/component')
    native_component = 'updates/main' if source['id'] == 'trixie-security' else 'main'
    if (release.get('Origin') != source['origin']
            or release.get('Codename') != source['codename']
            or release.get('Label') != source['label']):
        raise CatalogError('signed archive identity mismatch')
    if (architecture not in release.get('Architectures', '').split()
            or native_component not in release.get('Components', '').split()):
        raise CatalogError('signed archive does not declare selected architecture/component')
    if source['id'] == 'tailscale':
        return [
            {'path': 'main/binary-amd64/Packages.gz', 'compression': 'gzip', 'by_hash': False},
            {'path': 'main/binary-all/Packages.gz', 'compression': 'gzip', 'by_hash': False},
        ]
    return [{'path': 'main/binary-amd64/Packages.xz', 'compression': 'xz', 'by_hash': True}]


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


def select(document, catalog_id, variant, flavor, release, platform):
    catalogs = document.get('package_catalogs', {})
    if catalog_id not in catalogs:
        raise CatalogError('catalog unavailable; no target is silently omitted')
    catalog = validate(catalogs[catalog_id])
    if (variant != catalog['variant'] or flavor not in catalog['flavors']
            or release != catalog['release'] or platform not in catalog['platforms']):
        raise CatalogError('catalog does not cover the explicit variant/flavor/release/platform')
    entry = document['variants'].get(variant)
    if entry is None or entry['base_image'] != catalog['observed_base_image']:
        raise CatalogError('base image changed; refresh the reviewed source observation before lookup')
    selected = next((item for item in entry['flavors'] if item['id'] == flavor), None)
    if selected is None or not selected.get('build_image', False):
        raise CatalogError('flavor is not an enabled image target')
    if platform not in selected.get('platforms', entry['platforms']):
        raise CatalogError('platform is not declared for this flavor')
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
    declared = [(s['uri'], s['suite'], tuple(s['components']))
                for s in catalog['sources'] if s['role'] == 'base']
    if sorted(_native_sources(observation['source_text'])) != sorted(declared):
        raise CatalogError('catalog does not cover the exact observed base source set')
    base = next(s for s in catalog['sources'] if s['id'] == 'trixie')
    if observation['base_inrelease_sha256'] != base['freshness']['inrelease_sha256']:
        raise CatalogError('base metadata pin does not match reviewed observation')
    keys = {}
    for source in catalog['sources']:
        content = _public_file(config_directory, source['keyring'])
        if hashlib.sha256(content).hexdigest() != source['keyring_sha256']:
            raise CatalogError('keyring differs from reviewed trust bytes')
        if (source['role'] == 'base'
                and files[key_path] != {'sha256': source['keyring_sha256'], 'size': len(content)}):
            raise CatalogError('base keyring differs from observed image trust bytes')
        keys[source['id']] = content
    return observation, keys


def _copied_package_source_files(config_directory):
    """Identity every local source/trust file copied into the target."""
    import hashlib
    from pathlib import Path
    root = Path(config_directory)
    inventory = {}
    for relative_root in ('system_files/etc/apt', 'system_files/usr/share/keyrings'):
        directory = root / relative_root
        if directory.is_symlink():
            raise CatalogError('copied package-source paths must not contain symlinks')
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise CatalogError('copied package-source inventory root is not a directory')
        for candidate in sorted(directory.rglob('*')):
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise CatalogError('copied package-source paths must not contain symlinks')
            if candidate.is_dir():
                continue
            content = _public_file(root, relative, limit=8 * 1024 * 1024)
            inventory[relative] = {
                'sha256': hashlib.sha256(content).hexdigest(),
                'size': len(content),
            }
    return inventory


def _common_image_reference(image_versions):
    try:
        text = image_versions.decode('utf-8')
    except UnicodeError as exc:
        raise CatalogError('image version input is not UTF-8') from exc
    matches = re.findall(
        r'(?m)^  - name: common\n    image: ([^\s]+)\n'
        r'    tag: [^\s]+\n    digest: (sha256:[0-9a-f]{64})$',
        text,
    )
    if len(matches) != 1:
        raise CatalogError('common image pin is missing or ambiguous')
    image, image_digest = matches[0]
    return f'{image}@{image_digest}'


def bind_target_configuration(catalog, document, config_directory, flavor):
    """Bind reviewed build-source claims and parsed desktop sources to one target."""
    import hashlib
    raw = _public_file(config_directory, catalog['target_observation'])
    if hashlib.sha256(raw).hexdigest() != catalog['target_observation_sha256']:
        raise CatalogError('target source observation differs from reviewed pin')
    observation = _json(raw)
    exact(observation, ('schema_version', 'variant', 'flavors', 'platform', 'base_image',
                       'observed_at', 'configuration_files', 'copied_package_source_files',
                       'common_image', 'build_sources'),
          'target observation')
    if (type(observation['schema_version']) is not int or observation['schema_version'] != 1
            or observation['variant'] != catalog['variant']
            or observation['flavors'] != catalog['flavors']
            or observation['platform'] != 'linux/amd64'
            or observation['base_image'] != catalog['observed_base_image']):
        raise CatalogError('target observation does not match selected target')
    try:
        observed_at = datetime.fromisoformat(observation['observed_at'].replace('Z', '+00:00'))
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise CatalogError('target observation timestamp is invalid') from exc
    if observed_at.tzinfo is None:
        raise CatalogError('target observation timestamp needs timezone')
    files = observation['configuration_files']
    expected_files = {'Containerfile.debian', 'build_scripts/20-packages.sh',
                      'build_scripts/desktop/install-desktop.sh',
                      'scripts/build-image-inner.sh', 'image-versions.yaml'}
    if not isinstance(files, dict) or set(files) != expected_files:
        raise CatalogError('target observation lacks complete configuration files')
    configuration_bytes = {}
    for path, identity in files.items():
        exact(identity, ('sha256', 'size'), 'configuration file identity')
        digest(identity['sha256'])
        if type(identity['size']) is not int or identity['size'] <= 0:
            raise CatalogError('configuration file size is invalid')
        content = _public_file(config_directory, path, limit=8 * 1024 * 1024)
        if len(content) != identity['size'] or hashlib.sha256(content).hexdigest() != identity['sha256']:
            raise CatalogError('effective package-source configuration changed; refresh observation')
        configuration_bytes[path] = content
    copied_sources = _copied_package_source_files(config_directory)
    if observation['copied_package_source_files'] != copied_sources:
        raise CatalogError('copied package-source inventory changed; refresh observation')
    common_image = _common_image_reference(configuration_bytes['image-versions.yaml'])
    if observation['common_image'] != common_image:
        raise CatalogError('resolved common image differs from reviewed observation')
    build_sources = [{
        'id': source['id'],
        'uri': source['uri'],
        'suite': source['suite'],
        'components': source['components'],
        'declaration_url': source['declaration_url'],
        'keyring_url': source['keyring_url'],
        'declaration_sha256': source['declaration_sha256'],
        'keyring_sha256': source['keyring_sha256'],
    } for source in catalog['sources'] if source['role'] == 'build']
    if observation['build_sources'] != build_sources:
        raise CatalogError('catalog does not cover the observed build source set')
    if flavor != 'base':
        profiles = document.get('desktops', {})
        profile_name = flavor + '-debian' if flavor + '-debian' in profiles else flavor
        policy = profiles.get(profile_name, {}).get('packages', {}).get('apt')
        if not isinstance(policy, dict):
            raise CatalogError('selected flavor has no supported apt package policy')
        repositories = [item for item in policy.get('repos', [])
                        if item.get('condition', '') in ('', 'debian-trixie')]
        if repositories:
            raise CatalogError('selected flavor has desktop repositories without a reviewed adapter')
        if policy.get('before_install'):
            raise CatalogError('selected flavor mutates package sources through an unreviewed operation')
    return observation
