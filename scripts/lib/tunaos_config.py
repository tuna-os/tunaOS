"""Primary TOML matrix contract and generated compatibility adapter.

Python 3.10 uses the pinned tomli parser; 3.11+ uses the standard library.
This first ownership migration does not yet consume package/branding sections.
"""
from __future__ import annotations

import copy
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


def validate(config):
    """Validate the complete phase-1 surface; reject inert future sections."""
    table(config, ('schema_version', 'build', 'iso_groups', 'sibling_images', 'tuna_rollout', 'variants'),
          ('schema_version', 'build', 'iso_groups', 'sibling_images', 'tuna_rollout', 'variants'), 'config')
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
        destinations = [variant.get('publish_name', name), *aliases]
        for destination in destinations:
            for flavor in variant['flavors']:
                tag = flavor['id'] + (f'-{suffix}' if suffix else '')
                key = (destination, tag)
                if key in published and published[key] != name:
                    raise ConfigError(f'variants.{name}: {destination}:{tag} also belongs to {published[key]}')
                published[key] = name
    for i, group in enumerate(config['iso_groups']):
        # Offline payloads intentionally include flavors absent from the live menu.
        for key in ('flavors', 'offline_flavors'):
            unknown = set(group[key]) - flavor_ids
            if unknown:
                raise ConfigError(f'iso_groups[{i}].{key}: unknown flavors {sorted(unknown)}')
    return config


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
    content = render(load(root / 'tunaos.toml'))
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
