#!/usr/bin/env python3
"""Re-observe a package catalog's base image and update its pins.

Reviewed refresh step for the error "base image changed; refresh the reviewed
source observation before lookup", which follows a Renovate bump of the
variant's `base_image`. It pulls the OCI index, the amd64 manifest and the
single layer of `variants.<variant>.base_image` by digest from the registry,
reads the APT source, os-release and archive-keyring files from the layer
without running image code, and writes the source observation in the same
schema. With --write it replaces the observation file and the
`observed_base_image` and `source_observation_sha256` pins in tunaos.toml,
then checks the result with the same binding the search uses. Keys, sources
and the pinned InRelease are not changed: a different keyring or source set
fails the binding and needs a separate review. Afterwards run
`scripts/refresh-package-observation.py --catalog <name> --write`, because the
target observation records the base image too.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path
from lib import package_authoring as author
from lib import package_catalogs as catalogs
from lib import tunaos_config


SOURCE_PATH = 'etc/apt/sources.list.d/debian.sources'
OS_RELEASE_PATH = 'usr/lib/os-release'
KEYRING_PATH = 'usr/share/keyrings/debian-archive-keyring.pgp'
INDEX_TYPES = ('application/vnd.oci.image.index.v1+json',
               'application/vnd.docker.distribution.manifest.list.v2+json')
MANIFEST_TYPES = ('application/vnd.oci.image.manifest.v1+json',
                  'application/vnd.docker.distribution.manifest.v2+json')
LAYER_LIMIT = 256 * 1024 * 1024


def _registry_get(repository, path, token, accept=None, limit=8 * 1024 * 1024):
    request = urllib.request.Request(f'https://registry-1.docker.io/v2/{repository}/{path}')
    request.add_header('Authorization', f'Bearer {token}')
    if accept:
        request.add_header('Accept', ', '.join(accept))
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise catalogs.CatalogError(f'registry object exceeds size bound: {path}')
    return data


def _member_path(name):
    """Canonical relative path of a layer member; refuse absolute and escaping names."""
    if name.startswith('/'):
        raise catalogs.CatalogError(f'observed base layer has an absolute path: {name}')
    parts = [part for part in name.split('/') if part not in ('', '.')]
    if '..' in parts:
        raise catalogs.CatalogError(f'observed base layer has a parent-traversal path: {name}')
    return '/'.join(parts)


def observe(base_image, inrelease_sha256, now):
    """Return source-observation bytes for an exact docker.io library digest."""
    match = re.fullmatch(r'docker\.io/(library/[a-z0-9._-]+):([A-Za-z0-9._-]+)@(sha256:[0-9a-f]{64})', base_image)
    if match is None:
        raise catalogs.CatalogError('base image must be an exact docker.io/library reference by digest')
    repository, _, index_digest = match.groups()
    with urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io'
                                f'&scope=repository:{repository}:pull', timeout=60) as response:
        token = json.load(response)['token']
    index_bytes = _registry_get(repository, f'manifests/{index_digest}', token, INDEX_TYPES)
    if 'sha256:' + hashlib.sha256(index_bytes).hexdigest() != index_digest:
        raise catalogs.CatalogError('registry index does not match the pinned digest')
    index = json.loads(index_bytes)
    entries = [entry for entry in index.get('manifests', [])
               if entry.get('platform') == {'architecture': 'amd64', 'os': 'linux'}]
    if len(entries) != 1:
        raise catalogs.CatalogError('index has no single linux/amd64 manifest')
    manifest_digest = entries[0]['digest']
    manifest_bytes = _registry_get(repository, f'manifests/{manifest_digest}', token, MANIFEST_TYPES)
    if 'sha256:' + hashlib.sha256(manifest_bytes).hexdigest() != manifest_digest:
        raise catalogs.CatalogError('registry manifest does not match the index digest')
    manifest = json.loads(manifest_bytes)
    layers = manifest.get('layers')
    if not isinstance(layers, list) or len(layers) != 1:
        raise catalogs.CatalogError('observed base must have exactly one layer')
    layer = layers[0]
    blob = _registry_get(repository, f'blobs/{layer["digest"]}', token, limit=LAYER_LIMIT)
    if 'sha256:' + hashlib.sha256(blob).hexdigest() != layer['digest'] or len(blob) != layer['size']:
        raise catalogs.CatalogError('registry layer does not match the manifest')
    contents, apt_members = {}, []
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:*') as archive:
        for member in archive:
            name = _member_path(member.name)
            if name == 'etc/apt/sources.list' or (name.startswith('etc/apt/sources.list.d/')
                                                  and not member.isdir()):
                apt_members.append({'path': name, 'type': member.type.decode(),
                                    'size': member.size, 'linkname': member.linkname})
            if name in (SOURCE_PATH, OS_RELEASE_PATH, KEYRING_PATH):
                if not member.isreg():
                    raise catalogs.CatalogError(f'observed base file is not a regular file: {name}')
                contents[name] = archive.extractfile(member).read()
    if set(contents) != {SOURCE_PATH, OS_RELEASE_PATH, KEYRING_PATH}:
        raise catalogs.CatalogError('observed base lacks a required source, os-release or keyring file')
    revision = entries[0].get('annotations', {}).get('org.opencontainers.image.revision', '')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise catalogs.CatalogError('index entry has no upstream artifact revision')
    observation = {
        'base_image': base_image,
        'platform': 'linux/amd64',
        'manifest_sha256': manifest_digest.split(':', 1)[1],
        'layers': layers,
        'files': {path: {'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}
                  for path, content in sorted(contents.items(), key=lambda item: (
                      SOURCE_PATH, OS_RELEASE_PATH, KEYRING_PATH).index(item[0]))},
        'apt_source_members': apt_members,
        'schema_version': 1,
        'observed_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'base_inrelease_sha256': inrelease_sha256,
        'upstream_artifact_commit': revision,
        'source_text': contents[SOURCE_PATH].decode('utf-8'),
        'os_release_text': contents[OS_RELEASE_PATH].decode('utf-8'),
        'image_index': index_bytes.decode('utf-8'),
        'image_manifest': manifest_bytes.decode('utf-8'),
    }
    return (json.dumps(observation, indent=2) + '\n').encode()


def _replace_pins(source, catalog_name, base_image, digest):
    """Replace the two base pins inside [package_catalogs.<name>]; nothing else."""
    header = re.search(r'(?m)^\[package_catalogs\.' + re.escape(catalog_name) + r'\]\s*$', source)
    if header is None:
        raise catalogs.CatalogError(f'tunaos.toml has no [package_catalogs.{catalog_name}] table')
    following = re.search(r'(?m)^\[', source[header.end():])
    end = header.end() + following.start() if following else len(source)
    table = source[header.end():end]
    image_pin = re.compile(r'(?m)^(observed_base_image = ")[^"\n]+(")$')
    hash_pin = re.compile(r'(?m)^(source_observation_sha256 = ")[0-9a-f]{64}(")$')
    if len(image_pin.findall(table)) != 1 or len(hash_pin.findall(table)) != 1:
        raise catalogs.CatalogError('base observation pins are missing or ambiguous')
    table = image_pin.sub(lambda m: m.group(1) + base_image + m.group(2), table)
    table = hash_pin.sub(lambda m: m.group(1) + digest + m.group(2), table)
    return source[:header.end()] + table + source[end:]


def _load_refresh_tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'refresh_package_observation', Path(__file__).with_name('refresh-package-observation.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    refresh_tool = _load_refresh_tool()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=tunaos_config.ROOT / 'tunaos.toml')
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--write', action='store_true',
                        help='replace the observation file and the pins; default only reports')
    args = parser.parse_args(argv)
    try:
        source = author.read_config(args.config)
        document = tunaos_config.validate(tunaos_config.parse(source, path=str(args.config)))
        catalog = document.get('package_catalogs', {}).get(args.catalog)
        if catalog is None:
            raise catalogs.CatalogError(f'unknown package catalog: {args.catalog}')
        base_image = document['variants'][catalog['variant']]['base_image']
        if base_image == catalog['observed_base_image']:
            print(f'{args.catalog}: base observation is current; nothing to do')
            return 0
        base = next(s for s in catalog['sources'] if s['role'] == 'base' and s['id'] == 'trixie')
        raw = observe(base_image, base['freshness']['inrelease_sha256'], datetime.now(timezone.utc))
        digest = hashlib.sha256(raw).hexdigest()
        root = args.config.resolve().parent
        old_raw = catalogs._public_file(root, catalog['source_observation'])
        old = json.loads(old_raw)
        new = json.loads(raw)
        print(f'observed_base_image: {catalog["observed_base_image"]} -> {base_image}')
        for key in ('files', 'apt_source_members', 'source_text', 'upstream_artifact_commit'):
            print(f'{key}: {"unchanged" if old.get(key) == new[key] else "changed"}')
        candidate = dict(catalog, observed_base_image=base_image, source_observation_sha256=digest)
        observation_path = root / catalog['source_observation']
        if not args.write:
            print('dry run: review the changes above, then repeat with --write')
            return 0
        updated = _replace_pins(source.decode('utf-8'), args.catalog, base_image, digest)
        refresh_tool._atomic_write(observation_path, raw)
        try:
            catalogs.bind_observation(candidate, root)
            refresh_tool._atomic_write(args.config, updated.encode())
        except BaseException:
            refresh_tool._atomic_write(observation_path, old_raw)
            raise
        print(f'source_observation_sha256: {catalog["source_observation_sha256"][:12]} -> {digest[:12]}')
        print('written: now run scripts/refresh-package-observation.py --catalog '
              f'{args.catalog} --write, review `git diff`, then run the package catalog tests')
    except (catalogs.CatalogError, tunaos_config.ConfigError, ValueError, OSError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
