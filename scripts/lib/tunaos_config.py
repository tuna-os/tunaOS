"""Primary TOML matrix and desktop policy with generated compatibility adapters.

Python 3.10 uses the pinned tomli parser; 3.11+ uses the standard library.
Base/shared package and branding ownership remain later migration milestones.
"""
from __future__ import annotations

import copy
import importlib.util
from functools import lru_cache
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Python 3.10 requires tomli. Install the reviewed dependencies: "
            "python3 -m pip install -r requirements-config.txt"
        ) from exc

ROOT = Path(__file__).resolve().parents[2]
ID = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
PLATFORMS = {"linux/amd64", "linux/amd64/v2", "linux/amd64/v3", "linux/arm64"}


class ConfigError(ValueError):
    """Invalid primary configuration; never fall back to stock data."""


def table(value, allowed, required, path):
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: expected table")
    unknown, missing = set(value) - set(allowed), set(required) - set(value)
    if unknown or missing:
        raise ConfigError(f"{path}: unknown keys {sorted(unknown)}; missing keys {sorted(missing)}")


def text(value, path, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or any(ord(c) < 32 for c in value):
        raise ConfigError(f"{path}: expected {'possibly empty ' if empty else ''}single-line string")


def strings(value, path, platform=False):
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{path}: expected nonempty list of strings")
    for item in value:
        text(item, path)
    if len(set(value)) != len(value):
        raise ConfigError(f"{path}: duplicate values")
    if platform and set(value) - PLATFORMS:
        raise ConfigError(f"{path}: unsupported platform")


def identifier(value, path):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ConfigError(f"{path}: expected lowercase identifier")


@lru_cache(maxsize=1)
def package_policy():
    spec = importlib.util.spec_from_file_location('tunaos_package_policy', Path(__file__).with_name('tunaos_packages.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(config):
    """Validate the implemented surface; reject inert future sections."""
    table(config, ('schema_version', 'build', 'iso_groups', 'sibling_images', 'tuna_rollout', 'variants', 'package_groups', 'desktops'),
          ('schema_version', 'build', 'iso_groups', 'sibling_images', 'tuna_rollout', 'variants'), 'config')
    if 'desktops' in config or 'package_groups' in config:
        tunaos_packages = package_policy()
        try:
            tunaos_packages.validate({key: config[key] for key in ('package_groups', 'desktops') if key in config})
        except tunaos_packages.PolicyError as exc:
            raise ConfigError(str(exc)) from exc
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ConfigError('schema_version: expected integer 1')
    table(config['build'], ('global_platforms',), ('global_platforms',), 'build')
    strings(config['build']['global_platforms'], 'build.global_platforms', platform=True)
    variants = config['variants']
    if not isinstance(variants, dict) or not variants:
        raise ConfigError('variants: expected nonempty table')
    for name, variant in variants.items():
        where = f'variants.{name}'
        identifier(name, where)
        table(variant, ('emoji', 'description', 'base_image', 'aliases', 'platforms', 'flavors',
                        'upstream_track', 'experimental', 'akmods', 'publish_name', 'tag_suffix'),
              ('emoji', 'description', 'base_image', 'platforms', 'flavors'), where)
        for key in ('emoji', 'description', 'base_image', 'upstream_track', 'akmods', 'publish_name', 'tag_suffix'):
            if key in variant:
                text(variant[key], where + '.' + key)
        if 'experimental' in variant and type(variant['experimental']) is not bool:
            raise ConfigError(f'{where}.experimental: expected boolean')
        strings(variant['platforms'], where + '.platforms', platform=True)
        if 'aliases' in variant:
            strings(variant['aliases'], where + '.aliases')
            for alias in variant['aliases']:
                identifier(alias, where + '.aliases')
        flavors = variant['flavors']
        if not isinstance(flavors, list) or not flavors:
            raise ConfigError(f'{where}.flavors: expected nonempty list')
        seen = set()
        for i, flavor in enumerate(flavors):
            fp = f'{where}.flavors[{i}]'
            table(flavor, ('id', 'stage', 'build_image', 'build_iso', 'build_qcow2', 'platforms', 'luks_e2e'),
                  ('id', 'stage', 'build_image'), fp)
            identifier(flavor['id'], fp + '.id')
            if flavor['id'] in seen:
                raise ConfigError(f'{fp}.id: duplicate flavor')
            seen.add(flavor['id'])
            if type(flavor['stage']) is not int or not 1 <= flavor['stage'] <= 4:
                raise ConfigError(f'{fp}.stage: expected integer 1..4')
            for key in ('build_image', 'build_iso', 'build_qcow2', 'luks_e2e'):
                if key in flavor and type(flavor[key]) is not bool:
                    raise ConfigError(f'{fp}.{key}: expected boolean')
            if 'platforms' in flavor:
                strings(flavor['platforms'], fp + '.platforms', platform=True)
    if not isinstance(config['iso_groups'], list):
        raise ConfigError('iso_groups: expected list')
    suffixes = set()
    for i, group in enumerate(config['iso_groups']):
        where = f'iso_groups[{i}]'
        table(group, ('suffix', 'flavors', 'offline_flavors'), ('suffix', 'flavors', 'offline_flavors'), where)
        text(group['suffix'], where + '.suffix', empty=True)
        if group['suffix'] in suffixes:
            raise ConfigError(f'{where}.suffix: duplicate')
        suffixes.add(group['suffix'])
        strings(group['flavors'], where + '.flavors')
        strings(group['offline_flavors'], where + '.offline_flavors')
    if not isinstance(config['sibling_images'], list):
        raise ConfigError('sibling_images: expected list')
    sibling_ids = set()
    for i, sibling in enumerate(config['sibling_images']):
        where = f'sibling_images[{i}]'
        keys = ('id', 'emoji', 'description', 'image', 'repo', 'workflow', 'desktops')
        table(sibling, keys, keys, where)
        for key in keys[:-1]:
            text(sibling[key], where + '.' + key)
        identifier(sibling['id'], where + '.id')
        if sibling['id'] in sibling_ids:
            raise ConfigError(f'{where}.id: duplicate')
        sibling_ids.add(sibling['id'])
        strings(sibling['desktops'], where + '.desktops')
    rollout = config['tuna_rollout']
    if not isinstance(rollout, dict) or set(rollout) != set(variants):
        raise ConfigError('tuna_rollout: must account for exactly all variants')
    for name, policy in rollout.items():
        where = f'tuna_rollout.{name}'
        table(policy, ('status', 'package_target', 'reason', 'portals'), ('status', 'package_target'), where)
        for key, value in policy.items():
            text(value, where + '.' + key)
        if policy['status'] not in ('admitted', 'unsupported'):
            raise ConfigError(f'{where}.status: expected admitted or unsupported')
        if policy['status'] == 'unsupported' and not policy.get('reason'):
            raise ConfigError(f'{where}.reason: required for unsupported variant')
    # Image aliases share namespaces only when their complete published tags differ.
    # Variant platforms are defaults; a flavor may intentionally extend them.
    reserved = set(variants) | {v['publish_name'] for v in variants.values() if v.get('publish_name')}
    published = {}
    flavor_ids = {f['id'] for v in variants.values() for f in v['flavors']}
    for name, variant in variants.items():
        suffix = variant.get('tag_suffix', '')
        aliases = variant.get('aliases', [])
        for alias in aliases:
            if alias in reserved:
                raise ConfigError(f'variants.{name}.aliases: {alias!r} shadows a canonical image name')
        canonical = variant.get('publish_name', name)
        for flavor in variant['flavors']:
            tag = flavor['id'] + (f'-{suffix}' if suffix else '')
            platforms = flavor.get('platforms', variant['platforms'])
            # reusable-build-image.yml: Push Manifest and Promote Image emit
            # canonical, testing, architecture, and YYYYMMDD history tags.
            stems = [tag, *(tag + '-' + p.removeprefix('linux/').replace('/', '-')
                            for p in platforms)]
            entries = [(canonical, stem, dated) for stem in stems for dated in (False, True)]
            entries.append((canonical, tag + '-testing', False))
            # Build pushes also use safeplatform names, before promotion.
            for platform in platforms:
                build_tag = tag + '-' + platform.replace('/', '-')
                entries.extend([(canonical, build_tag, False),
                                (canonical, build_tag + '.packages', False)])
            entries.extend((alias, tag, dated) for alias in aliases for dated in (False, True))
            owner = (name, flavor['id'])
            for destination, stem, dated in entries:
                for previous_stem, previous_dated, previous_owner in published.get(destination, []):
                    if previous_owner == owner:
                        continue
                    if publication_tags_overlap(stem, dated, previous_stem, previous_dated):
                        display = stem + ('-YYYYMMDD' if dated else '')
                        raise ConfigError(f'variants.{name}: {destination}:{display} '
                                          f'also belongs to {previous_owner[0]}')
                published.setdefault(destination, []).append((stem, dated, owner))
    for i, group in enumerate(config['iso_groups']):
        # Offline payloads intentionally include flavors absent from the live menu.
        for key in ('flavors', 'offline_flavors'):
            unknown = set(group[key]) - flavor_ids
            if unknown:
                raise ConfigError(f'iso_groups[{i}].{key}: unknown flavors {sorted(unknown)}')
    return config


def publication_tags_overlap(left, left_dated, right, right_dated):
    """Compare literal tags and the workflow's calendar-date suffix families."""
    if left_dated == right_dated:
        return left == right
    stem, literal = (left, right) if left_dated else (right, left)
    if not literal.startswith(stem + '-'):
        return False
    suffix = literal[len(stem) + 1:]
    if not re.fullmatch(r'[0-9]{8}', suffix):
        return False
    try:
        datetime.strptime(suffix, '%Y%m%d')
    except ValueError:
        return False
    return True


def load(path=None):
    path = Path(path) if path is not None else ROOT / 'tunaos.toml'
    try:
        with path.open('rb') as stream:
            config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f'{path}: {exc}') from exc
    return validate(config)


def matrix(config):
    """Project the old consumer shape without inventing defaults or losing flags."""
    validate(config)
    return copy.deepcopy({'config': config['build'], 'iso_groups': config['iso_groups'],
                          'sibling_images': config['sibling_images'], 'tuna_rollout': config['tuna_rollout'],
                          'variants': [{'id': name, **value} for name, value in config['variants'].items()]})


def render(config):
    # JSON is also YAML; old jq/yq/PyYAML consumers keep their data contract.
    return json.dumps(matrix(config), ensure_ascii=False, indent=2) + '\n'


def prepare(root=ROOT):
    """Atomically refresh ignored legacy adapter from the primary source."""
    root = Path(root)
    document = load(root / 'tunaos.toml')
    content = render(document)
    if 'desktops' in document:
        prepare_desktops(root, document)
    target = root / '.github/build-config.yml'
    if target.is_symlink() or target.parent.is_symlink():
        raise ConfigError(f'{target}: generated adapter must not be a symlink')
    if target.exists() and not target.is_file():
        raise ConfigError(f'{target}: generated adapter must be a regular file')
    if target.is_file() and target.read_text() == content:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.build-config-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o644)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def prepare_desktops(root=ROOT, document=None):
    """Validate every desktop output before refreshing its compatibility file."""
    root = Path(root)
    document = load(root / 'tunaos.toml') if document is None else validate(document)
    policy = {key: document[key] for key in ('package_groups', 'desktops')}
    outputs = package_policy().desktop_outputs(policy)
    targets = []
    for relative in outputs:
        target = root / relative
        if any(parent.is_symlink() for parent in (target, *target.parents) if parent != root.parent):
            raise ConfigError(f'{target}: generated desktop paths must not be symlinks')
        if target.exists() and not target.is_file():
            raise ConfigError(f'{target}: generated desktop adapter must be a regular file')
        targets.append(target)
    for target, content in zip(targets, outputs.values()):
        if target.is_file() and target.read_text() == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                             prefix='.desktop-policy-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o644)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return targets


def prepare_debian_contract(root, variant, desktop, platform):
    """Bind a declared Debian build cell before its context is hashed or copied."""
    import hashlib
    root = Path(root)
    source = (root / 'tunaos.toml').read_bytes()
    document = validate(tomllib.loads(source.decode('utf-8')))
    try:
        contract = package_policy().installation_contract(document, hashlib.sha256(source).hexdigest(),
                                                         variant, desktop, platform,
                                                         manager='apt', os_id='debian')
    except package_policy().PolicyError as exc:
        raise ConfigError(str(exc)) from exc
    target = root / 'manifests/desktop-contracts' / variant / desktop / (platform.replace('/', '-') + '.json')
    if any(parent.is_symlink() for parent in (target, *target.parents) if parent != root.parent):
        raise ConfigError(f'{target}: contract destination must not be a symlink')
    content = json.dumps(contract, indent=2) + '\n'
    if target.is_file() and target.read_text() == content:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.desktop-contract-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o644)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def prepare_debian_build_context(root, output, variant, desktop, platforms):
    """Copy reviewed tracked inputs and generate only the requested cell contracts."""
    import hashlib
    import shutil
    import subprocess
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(root):
        raise ConfigError('build context output must be new and outside the source checkout')
    if not platforms or len(set(platforms)) != len(platforms):
        raise ConfigError('build context requires distinct target platforms')
    tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'], text=True).split('\0')
    snapshot = {}
    inputs = set(filter(None, tracked))
    # Prepared preview contexts carry a validated manifest and content-addressed
    # assets outside their Git index. Preserve only those explicit inputs.
    payload = root / 'manifests/fork-config.json'
    if payload.exists() or payload.is_symlink():
        if payload.is_symlink() or not payload.is_file():
            raise ConfigError('prepared customization manifest must be a regular file')
        manifest = json.loads(payload.read_text())
        inputs.add('manifests/fork-config.json')
        assets = manifest.get('assets', {})
        if not isinstance(assets, dict):
            raise ConfigError('prepared customization assets must be a mapping')
        for asset in assets.values():
            if not isinstance(asset, dict) or set(asset) != {'path', 'sha256'}:
                raise ConfigError('prepared customization asset requires path and sha256')
            digest = asset['sha256']
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ConfigError('prepared customization asset digest is invalid')
            if asset['path'] != f'fork-assets/{digest}.jpg':
                raise ConfigError('prepared customization asset path is invalid')
            relative = 'manifests/' + asset['path']
            path = root / relative
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ConfigError('prepared customization asset is missing or has changed')
            inputs.add(relative)
    for relative in sorted(inputs):
        # Derived files can exist in an old checkout index during migration;
        # they are never authorities and must not enter the source snapshot.
        if relative.startswith(('manifests/desktops/', 'manifests/desktop-plans/', 'manifests/desktop-contracts/')):
            continue
        source = root / relative
        if source.is_symlink():
            content = b'symlink:' + os.readlink(source).encode()
        elif source.is_file():
            content = source.read_bytes()
        else:
            raise ConfigError(f'{relative}: unsupported directory/submodule source')
        snapshot[relative] = {'sha256': hashlib.sha256(content).hexdigest(),
                              'mode': source.lstat().st_mode & 0o777}
    output.mkdir(parents=True)
    for relative, digest in snapshot.items():
        source, target = root / relative, output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
            content = b'symlink:' + os.readlink(target).encode()
        else:
            shutil.copy2(source, target)
            content = target.read_bytes()
        if (hashlib.sha256(content).hexdigest() != digest['sha256']
                or target.lstat().st_mode & 0o777 != digest['mode']):
            raise ConfigError('sources changed during context preparation; discard and retry')
    # Detect edits to an earlier-copied input while later files were copied.
    for relative, digest in snapshot.items():
        source = root / relative
        content = (b'symlink:' + os.readlink(source).encode()
                   if source.is_symlink() else source.read_bytes())
        if (hashlib.sha256(content).hexdigest() != digest['sha256']
                or source.lstat().st_mode & 0o777 != digest['mode']):
            raise ConfigError('sources changed during context preparation; discard and retry')
    prepare(output)
    for platform in platforms:
        prepare_debian_contract(output, variant, desktop, platform)
    # Hash only relative paths and bytes. Temporary directory names and another
    # target's accumulated generated outputs cannot perturb this identity.
    generated = {}
    for path in sorted((output / 'manifests').rglob('*')):
        if path.is_file():
            generated[path.relative_to(output).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    context_digest = hashlib.sha256(json.dumps({'source': snapshot, 'generated': generated}, sort_keys=True).encode()).hexdigest()
    (output / 'desktop-context-receipt.json').write_text(json.dumps({'sha256': context_digest, 'sources': snapshot,
                                                                   'generated': generated}, indent=2) + '\n')
    return output
