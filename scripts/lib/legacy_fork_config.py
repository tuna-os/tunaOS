"""One-way migration of a legacy fork-config file into the primary tunaos.toml.

The legacy format (schema_version 1 YAML/JSON, retired in #3807) described a
*delta* over a stock catalog. The primary file has no catalog beneath it, so a
migration applies that delta to the checkout's own tunaos.toml and returns the
new bytes. Only fields with an exact primary home are converted; anything else
fails with a message naming the field and where its replacement lives. Nothing
falls back to a default, and nothing is dropped silently.

What carries over:

  image.registry / image.namespace         -> [build.publish]
  global.branding.homepage/documentation/support
                                           -> [defaults.branding]
  global.packages.add/optional/repositories -> [defaults.packages]
  overrides.variants.<v>.packages           -> [variants.<v>.packages]

`targets` only chose which cells the preview compiled; pruning the matrix touches
iso_groups, tuna_rollout and the ISO Builder defaults too, so a non-empty
`targets` is refused (docs/ROLL_YOUR_OWN.md, step 2, prunes by hand).

Edits are line-level insertions and replacements, so every comment and the
layout of the rest of the file survive. The edited text is then parsed and
validated by the primary parser, and must equal the original document plus the
intended changes, or no output is produced. Limits: an inline comment on a
value line this command replaces is not kept, and a primary file that already
defines a package table with different contents is refused rather than merged.

Requires PyYAML (already used by the repository's Python tooling).
"""
from __future__ import annotations

import copy
import json
import re

import yaml

from . import tunaos_config
from .tunaos_config import ConfigError

URL_FIELDS = ('homepage', 'documentation', 'support')
PACKAGE_KEYS = ('add', 'remove', 'optional', 'repositories')
HEADER = re.compile(r'^\[(\[)?\s*([^\[\]]+?)\s*\]\]?\s*(?:#.*)?$')

BRANDING_GUIDANCE = {
    'name': 'set [project] name, id and cpe_vendor together in tunaos.toml',
    'logo': "a variant's logo is its emoji mark; see docs/BRANDING.md",
    'wallpaper': 'the single shared wallpaper override has no tunaos.toml key; place drawn art at '
                 'system_files/usr/share/backgrounds/tunaos/<variant>-<desktop>.jpg (docs/BRANDING.md)',
}


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate keys instead of keeping the last value."""


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ConfigError(f'legacy config: duplicate or non-string key {key!r}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_legacy(source):
    try:
        return yaml.load(source, Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise ConfigError(f'legacy config is not valid YAML: {exc}') from exc


def _mapping(value, allowed, where, required=()):
    if not isinstance(value, dict):
        raise ConfigError(f'{where}: expected a mapping')
    unknown, missing = sorted(set(value) - set(allowed)), sorted(set(required) - set(value))
    if unknown or missing:
        raise ConfigError(f'{where}: unknown keys {unknown}, missing keys {missing}; '
                          'this is not a legacy fork-config v1 key set')
    return value


def _strings(value, where):
    if (not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(set(value)) != len(value)):
        raise ConfigError(f'{where}: expected a list of distinct nonempty strings')
    return value


def _layer(value, where, problems):
    """Validate the legacy layer shape; record fields with no primary home."""
    _mapping(value, ('branding', 'packages'), where)
    branding, packages = value.get('branding', {}), value.get('packages', {})
    _mapping(branding, ('name', 'homepage', 'documentation', 'support', 'logo', 'wallpaper'), where + '.branding')
    for key, item in branding.items():
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f'{where}.branding.{key}: expected a nonempty string')
    _mapping(packages, PACKAGE_KEYS, where + '.packages')
    for key, items in packages.items():
        if not isinstance(items, list):
            raise ConfigError(f'{where}.packages.{key}: expected a list')
        if key != 'repositories':
            _strings(items, f'{where}.packages.{key}')
        for index, repo in enumerate(items if key == 'repositories' else ()):
            _mapping(repo, ('id', 'url', 'key_url'), f'{where}.packages.repositories[{index}]',
                     ('id', 'url', 'key_url'))
    if packages.get('remove'):
        problems.append(f'{where}.packages.remove: package removals are not supported in tunaos.toml '
                        '(no protected removal exists yet, #3668 F4b); remove the entries or use the '
                        'custom/ overlay for a personal image')
    return branding, packages


def parse_legacy(document):
    """Return (image, scopes, problems) from a legacy document."""
    problems = []
    config = _mapping(document, ('schema_version', 'catalog', 'image', 'targets', 'global', 'overrides'),
                      'legacy config', ('schema_version', 'catalog'))
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ConfigError('legacy config schema_version: expected integer 1')
    pin = _mapping(config['catalog'], ('sha256',), 'catalog', ('sha256',))['sha256']
    if not isinstance(pin, str) or not re.fullmatch(r'[0-9a-f]{64}', pin):
        raise ConfigError('catalog.sha256: expected a lowercase SHA-256')
    image = config.get('image')
    if image is not None:
        _mapping(image, ('registry', 'namespace'), 'image', ('registry', 'namespace'))
        for key, value in image.items():
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f'image.{key}: expected a nonempty string')
    targets = _mapping(config.get('targets', {}), ('variants', 'flavors', 'platforms'), 'targets')
    for key, value in targets.items():
        _strings(value, f'targets.{key}')
    if targets:
        problems.append('targets: the preview used it to choose which cells to compile; tunaos.toml has no '
                        'selection layer. Build one cell with `just build <variant> <flavor>`, or turn cells '
                        'off with build_image = false and fix the sections that name them '
                        '(docs/ROLL_YOUR_OWN.md, "Prune")')
    scopes = []  # (name, kind, key, branding, packages)
    branding, packages = _layer(config.get('global', {}), 'global', problems)
    scopes.append(('global', 'global', None, branding, packages))
    overrides = _mapping(config.get('overrides', {}), ('variants', 'desktops', 'cells'), 'overrides')
    for kind in ('variants', 'desktops', 'cells'):
        group = overrides.get(kind, {})
        if not isinstance(group, dict):
            raise ConfigError(f'overrides.{kind}: expected a mapping')
        for key, layer in group.items():
            where = f'overrides.{kind}.{key}'
            branding, packages = _layer(layer, where, problems)
            if kind != 'variants' and (branding or any(packages.values())):
                problems.append(f'{where}: tunaos.toml has image-wide package additions only at '
                                '[defaults.packages] and [variants.<id>.packages]; a desktop- or cell-scoped '
                                'layer cannot be converted (desktop package profiles live in '
                                '[desktops.<name>.packages.<family>])')
            scopes.append((where, kind, key, branding, packages))
    for name, kind, key, branding, _ in scopes:
        for field, value in branding.items():
            if field in URL_FIELDS and kind == 'global':
                continue
            where = f'{name}.branding.{field}'
            if kind == 'global' or kind == 'variants':
                why = BRANDING_GUIDANCE.get(field, 'URLs are set once, in [defaults.branding]')
                problems.append(f'{where}: no tunaos.toml equivalent; {why}')
    return image, scopes, problems


def _toml(value):
    return json.dumps(value, ensure_ascii=False)


def _sections(lines):
    found = []
    for index, line in enumerate(lines):
        match = HEADER.match(line)
        if match:
            found.append((index, match.group(2).strip(), bool(match.group(1))))
    return found


def _body(lines, header, which=0, array=False):
    """Half-open line range of the `which`-th table with this header, or None."""
    headers = _sections(lines)
    seen = -1
    for position, (index, name, is_array) in enumerate(headers):
        if name == header and is_array == array:
            seen += 1
            if seen == which:
                end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
                return index, end
    return None


def _last_value_line(lines, start, end):
    """Index of the last line of the table body that is neither blank nor a comment."""
    for index in range(end - 1, start, -1):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith('#'):
            return index
    return start


def _insert_after(lines, index, text):
    if not lines[index].endswith('\n'):
        lines[index] += '\n'
    lines[index + 1:index + 1] = text.splitlines(keepends=True)


def _set_key(lines, header, key, value, which=0, array=False):
    span = _body(lines, header, which, array)
    if span is None:
        raise ConfigError(f'tunaos.toml has no [{header}] table to hold {key}')
    start, end = span
    pattern = re.compile(r'^' + re.escape(key) + r'\s*=\s*(.*)$')
    for index in range(start + 1, end):
        match = pattern.match(lines[index].rstrip('\n'))
        if match:
            rest = match.group(1).strip()
            if rest.startswith('[') and rest.count('[') != rest.count(']'):
                raise ConfigError(f'[{header}] {key}: multi-line value; edit it by hand')
            lines[index] = f'{key} = {_toml(value)}\n'
            return
    _insert_after(lines, _last_value_line(lines, start, end), f'{key} = {_toml(value)}\n')


def _package_block(header, delta):
    text = f'\n[{header}]\n'
    for key in ('add', 'optional'):
        if delta.get(key):
            text += f'{key} = {_toml(delta[key])}\n'
    for repo in delta.get('repositories', []):
        text += f'\n[[{header}.repositories]]\n'
        text += ''.join(f'{key} = {_toml(repo[key])}\n' for key in ('id', 'url', 'key_url'))
    return text


def _delta(packages):
    return {key: [dict(item) if isinstance(item, dict) else item for item in packages[key]]
            for key in ('add', 'optional', 'repositories') if packages.get(key)}


def convert(source, legacy):
    """New tunaos.toml bytes for `legacy` applied to `source`; raises ConfigError, never partial output."""
    source = source if isinstance(source, bytes) else source.encode('utf-8')
    original = tunaos_config.validate(tunaos_config.parse(source, 'tunaos.toml'))
    image, scopes, problems = parse_legacy(legacy)
    if problems:
        raise ConfigError('legacy config has fields that cannot be converted:\n  ' + '\n  '.join(problems))
    lines = source.decode('utf-8').splitlines(keepends=True)
    expected = copy.deepcopy(original)

    if image is not None:
        publish = {'registry': image['registry'], 'namespace': image['namespace']}
        if _body(lines, 'build.publish') is None:
            _insert_after(lines, _last_value_line(lines, *_body(lines, 'build')),
                          f'\n[build.publish]\nregistry = {_toml(publish["registry"])}\n'
                          f'namespace = {_toml(publish["namespace"])}\n')
        else:
            for key, value in publish.items():
                _set_key(lines, 'build.publish', key, value)
        expected['build']['publish'] = publish

    for name, kind, key, branding, packages in scopes:
        if kind == 'global':
            for field in URL_FIELDS:
                if field in branding:
                    _set_key(lines, 'defaults.branding', field, branding[field])
                    expected.setdefault('defaults', {}).setdefault('branding', {})[field] = branding[field]
        delta = _delta(packages) if kind in ('global', 'variants') else {}
        if not delta:
            continue
        if kind == 'global':
            header, holder, anchor = 'defaults.packages', expected.setdefault('defaults', {}), 'defaults.branding'
        else:
            if key not in original['variants']:
                raise ConfigError(f'{name}: no variant {key!r} in tunaos.toml')
            header, holder, anchor = f'variants.{key}.packages', expected['variants'][key], f'variants.{key}'
        if 'packages' in holder:
            if holder['packages'] != delta:
                raise ConfigError(f'tunaos.toml already defines [{header}] differently; merge {name} by hand')
            continue
        span = _body(lines, anchor)
        if span is None:
            raise ConfigError(f'tunaos.toml has no [{anchor}] table to place [{header}] after')
        _insert_after(lines, _last_value_line(lines, *span), _package_block(header, delta))
        holder['packages'] = delta

    output = ''.join(lines).encode('utf-8')
    actual = tunaos_config.validate(tunaos_config.parse(output, '<migrated tunaos.toml>'))
    if actual != expected:
        raise ConfigError('migration would change more than the legacy fields; no output produced. '
                          'Make the edits by hand.')
    # Package names are checked against each variant's package manager here,
    # not at the next build.
    tunaos_config.render_image_packages(actual)
    return output
