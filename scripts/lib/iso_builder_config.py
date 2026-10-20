"""Portable ISO Builder presentation contract. No catalog or transport authority."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import json
import re
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Invalid presentation input; do not substitute stock branding."""


def table(value, required, optional=()):
    if not isinstance(value, dict):
        raise ConfigError('expected object')
    unknown = set(value) - set(required) - set(optional)
    missing = set(required) - set(value)
    if unknown or missing:
        raise ConfigError(f'unknown keys {sorted(unknown)}; missing keys {sorted(missing)}')


def text(value):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError('expected nonempty single-line string')


def pattern(value, regex):
    text(value)
    if not re.fullmatch(regex, value):
        raise ConfigError(f'invalid value: {value!r}')


def url(value, asset=False):
    text(value)
    if '\\' in value or any(c.isspace() for c in value):
        raise ConfigError('URL must not contain whitespace or backslashes')
    if asset and re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*', value):
        return
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigError('invalid URL') from exc
    if not re.fullmatch(r'https://[^\s/@\\:]+(?::443)?(?:[/?#][^\s\\]*)?', value) or parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or port not in (None, 443):
        raise ConfigError('expected HTTPS URL without credentials or custom port')


def entries(value, fields, collection):
    if not isinstance(value, list):
        raise ConfigError(f'{collection}: expected list')
    seen = set()
    for entry in value:
        table(entry, fields)
        pattern(entry['id'], r'[a-z0-9][a-z0-9-]*')
        if entry['id'] in seen:
            raise ConfigError(f'{collection}: duplicate id {entry["id"]!r}')
        seen.add(entry['id'])
    return seen


def validate(document):
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or document['schema_version'] not in (1, 2):
        raise ConfigError('schema_version must be integer 1 or 2')
    v2 = document['schema_version'] == 2
    table(document, ('schema_version', 'preview_only', 'brand', 'presentation', 'output', 'desktops', 'default_selection', 'curated_app_sets', 'selection' if v2 else 'variants'), ('ddi_channels',))
    if type(document['preview_only']) is not bool:
        raise ConfigError('preview_only must be boolean')
    brand = document['brand']
    table(brand, ('name', 'homepage_url', 'documentation_url'), ('logo_url', 'favicon_url', 'support_url', 'disclaimer'))
    if document['preview_only'] and 'disclaimer' not in brand:
        raise ConfigError('preview_only requires an affiliation disclaimer')
    for key, value in brand.items():
        if key.endswith('_url'):
            url(value, asset=key in ('logo_url', 'favicon_url'))
        else:
            text(value)
    table(document['presentation'], ('headline', 'intro', 'accent_color'), ('colors', 'choice_style', 'font_family') if v2 else ())
    for key in ('headline', 'intro', 'accent_color'):
        text(document['presentation'][key])
    for key, allowed in (('choice_style', ('illustrated', 'thumbnail')), ('font_family', ('system', 'inter', 'dm-sans'))):
        if key in document['presentation'] and document['presentation'][key] not in allowed:
            raise ConfigError(f'unsupported presentation {key}')
    if 'colors' in document['presentation']:
        colors = document['presentation']['colors']
        table(colors, ('background', 'surface', 'text', 'muted', 'accent', 'accent_text'), ('border', 'hover_surface', 'focus', 'selected_surface'))
        for color in colors.values():
            pattern(color, r'#[0-9a-fA-F]{6}')
    pattern(document['presentation']['accent_color'], r'#[0-9a-fA-F]{6}')
    table(document['output'], ('volume_label', 'filename_prefix'))
    pattern(document['output']['volume_label'], r'[A-Z0-9_]{1,32}')
    pattern(document['output']['filename_prefix'], r'[a-z0-9][a-z0-9_-]{0,63}')
    desktops = entries(
        document['desktops'],
        ('id', 'default_flatpaks') if v2 else ('id', 'name', 'description', 'default_flatpaks'),
        'desktops',
    )
    for desktop in document['desktops']:
        if not v2:
            text(desktop['name'])
            text(desktop['description'])
        apps = desktop['default_flatpaks']
        if not isinstance(apps, list):
            raise ConfigError(f'desktops.{desktop["id"]}.default_flatpaks: expected list')
        seen_apps = set()
        for app in apps:
            pattern(app, r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2,}')
            if app in seen_apps:
                raise ConfigError(
                    f'desktops.{desktop["id"]}.default_flatpaks: duplicate Flatpak {app!r}'
                )
            seen_apps.add(app)
    if v2:
        validate_selection(document)
    else:
        variants = entries(document['variants'], ('id', 'name'), 'variants')
        for variant in document['variants']:
            text(variant['name'])
        selection = document['default_selection']
        if not isinstance(selection, dict) or selection.get('kind') not in ('catalog', 'image'):
            raise ConfigError('default_selection.kind must be catalog or image')
        if selection['kind'] == 'catalog':
            table(selection, ('kind', 'variant', 'flavor', 'platform'))
            if not isinstance(selection['variant'], str) or not isinstance(selection['flavor'], str) or selection['variant'] not in variants or selection['flavor'] not in desktops:
                raise ConfigError('default selection must reference configured variant and desktop')
        else:
            table(selection, ('kind', 'image', 'platform'))
            # distribution/reference v0.6.0 path and DNS labels; lowercase host scope.
            # Syntax does not grant inspection, relay admission or qualification.
            pattern(selection['image'], r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*(?::[0-9]+)?/[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*)*(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}(?:@sha256:[0-9a-f]{64})?|@sha256:[0-9a-f]{64})')
        if selection['platform'] not in ('linux/amd64', 'linux/amd64/v2', 'linux/amd64/v3', 'linux/arm64'):
            raise ConfigError('unsupported platform')
    entries(
        document['curated_app_sets'],
        ('id', 'label', 'desktops', 'url', 'format'),
        'curated_app_sets',
    )
    for collection in document['curated_app_sets']:
        text(collection['label'])
        url(collection['url'])
        selected = collection['desktops']
        if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected) or len(set(selected)) != len(selected) or set(selected) - desktops:
            raise ConfigError('collection desktops must be unique configured ids')
        if collection['format'] not in ('brewfile', 'preinstall'):
            raise ConfigError('unsupported collection format')
    entries(document.get('ddi_channels', []), ('id', 'stem', 'name', 'desktop'), 'ddi_channels')
    for channel in document.get('ddi_channels', []):
        pattern(channel['stem'], r'[a-z0-9][a-z0-9-]*')
        text(channel['name'])
        if not isinstance(channel['desktop'], str) or channel['desktop'] not in desktops | {'none'}:
            raise ConfigError('DDI desktop must reference configured desktop or none')
    return document


def project(primary):
    if 'iso_builder' not in primary:
        raise ConfigError('iso_builder is required for builder export; no stock fallback')
    result = copy.deepcopy(primary['iso_builder'])
    if 'flatpak_preinstall' in primary:
        if not isinstance(result, dict):
            raise ConfigError('expected builder object')
        entries(result.get('desktops'), ('id',) if result.get('schema_version') == 2 else ('id', 'name', 'description'), 'desktops')
        spec = importlib.util.spec_from_file_location('builder_flatpak_policy', Path(__file__).with_name('flatpak_preinstall.py'))
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        try:
            for desktop in result['desktops']:
                if 'default_flatpaks' in desktop:
                    raise ConfigError('primary image declarations own builder defaults; remove duplicate default_flatpaks')
                desktop['default_flatpaks'] = [app['id'] for app in policy.apps(primary, desktop['id'])]
        except policy.PolicyError as exc:
            raise ConfigError(str(exc)) from exc
    validate(result)
    variants = primary['variants']
    if result['schema_version'] == 2:
        validate_primary_selection(primary, result)
        return result
    if any(item['id'] not in variants for item in result['variants']):
        raise ConfigError('builder variant does not exist in primary matrix')
    selection = result['default_selection']
    if selection['kind'] == 'catalog':
        variant = variants[selection['variant']]
        flavor = next((item for item in variant['flavors'] if item['id'] == selection['flavor']), None)
        if not flavor or not flavor['build_image'] or selection['platform'] not in flavor.get('platforms', variant['platforms']):
            raise ConfigError('builder default is not a build-enabled primary matrix cell')
    return result


def render(primary):
    return json.dumps(project(primary), ensure_ascii=False, indent=2, sort_keys=True) + '\n'


FACETS = {'family', 'base', 'desktop', 'hardware', 'platform', 'graphics', 'edition', 'gaming_mode', 'channel', 'graphics_generation'}
PLATFORMS = {'linux/amd64', 'linux/amd64/v2', 'linux/amd64/v3', 'linux/arm64'}


def leaf_id(value):
    pattern(value, r'[a-z0-9][a-z0-9:/._-]{0,191}')


def selection_text(value):
    text(value)
    if len(value) > 2048 or '<' in value or '>' in value:
        raise ConfigError('selection text must be plain text of at most 2048 characters')


def validate_selection(document):
    selection = document['selection']
    table(selection, ('paths', 'default_path', 'facets', 'recommendations'))
    paths = entries(selection['paths'], ('id', 'label', 'facets'), 'selection.paths')
    if not 1 <= len(paths) <= 4:
        raise ConfigError('selection requires 1..4 paths')
    facets = selection['facets']
    if not isinstance(facets, list) or not 1 <= len(facets) <= len(FACETS):
        raise ConfigError('selection requires known facets')
    seen = set()
    values = {}
    for facet in facets:
        table(facet, ('id', 'label', 'values'), ('description',))
        if not isinstance(facet['id'], str) or facet['id'] not in FACETS or facet['id'] in seen:
            raise ConfigError('unknown or duplicate facet')
        seen.add(facet['id'])
        selection_text(facet['label'])
        if 'description' in facet:
            selection_text(facet['description'])
        if not isinstance(facet['values'], list) or not 1 <= len(facet['values']) <= 256:
            raise ConfigError('facet requires 1..256 values')
        ids = set()
        for value in facet['values']:
            table(value, ('id', 'label'), ('description', 'card'))
            if 'card' in value:
                card = value['card']
                table(card, ('image_url', 'image_alt'), ('badge',))
                url(card['image_url'], asset=True)
                selection_text(card['image_alt'])
                if 'badge' in card:
                    selection_text(card['badge'])
            if facet['id'] == 'platform':
                if not isinstance(value['id'], str) or value['id'] not in PLATFORMS:
                    raise ConfigError('unsupported facet platform')
            else:
                pattern(value['id'], r'[a-z0-9][a-z0-9-]{0,63}')
            if value['id'] in ids:
                raise ConfigError('duplicate facet value')
            ids.add(value['id'])
            selection_text(value['label'])
            if 'description' in value:
                selection_text(value['description'])
        values[facet['id']] = ids
    for path in selection['paths']:
        pattern(path['id'], r'[a-z0-9][a-z0-9-]{0,63}')
        selection_text(path['label'])
        ids = path['facets']
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in seen for i in ids) or len(set(ids)) != len(ids):
            raise ConfigError('path must reference unique configured facets')
    if not isinstance(selection['default_path'], str) or selection['default_path'] not in paths:
        raise ConfigError('unknown default path')
    if {d['id'] for d in document['desktops']} - values.get('desktop', set()):
        raise ConfigError('desktop app policy must reference a configured desktop facet')
    recommendations = selection['recommendations']
    if not isinstance(recommendations, list) or len(recommendations) > 8:
        raise ConfigError('expected at most 8 recommendations')
    recommended = set()
    for recommendation in recommendations:
        table(recommendation, ('leaf_id', 'label', 'reason'))
        leaf_id(recommendation['leaf_id'])
        if recommendation['leaf_id'] in recommended:
            raise ConfigError('duplicate recommended leaf')
        recommended.add(recommendation['leaf_id'])
        selection_text(recommendation['label'])
        selection_text(recommendation['reason'])
    default = document['default_selection']
    if not isinstance(default, dict) or default.get('kind') not in ('leaf', 'none'):
        raise ConfigError('default_selection.kind must be leaf or none')
    table(default, ('kind', 'leaf_id') if default['kind'] == 'leaf' else ('kind',))
    if default['kind'] == 'leaf':
        leaf_id(default['leaf_id'])


def flavor_metadata(primary):
    metadata = primary.get('flavor_metadata')
    if not isinstance(metadata, dict):
        raise ConfigError('flavor_metadata must be a table')
    expected = {f['id'] for v in primary['variants'].values() for f in v['flavors']}
    if set(metadata) != expected:
        raise ConfigError('flavor_metadata must cover exact primary flavor IDs')
    for value in metadata.values():
        table(value, ('desktop', 'edition'))
        for item in value.values():
            pattern(item, r'[a-z0-9][a-z0-9-]{0,63}')
        if value['desktop'] not in set(primary.get('desktops', {})) | {'none'}:
            raise ConfigError('flavor desktop must reference primary desktop policy or none')
    return {'schema_version': 1, 'kind': 'builder-flavor-metadata', 'flavors': [dict(id=key, **metadata[key]) for key in sorted(metadata)]}


def render_flavors(primary):
    return json.dumps(flavor_metadata(primary), ensure_ascii=False, indent=2) + '\n'


def validate_primary_selection(primary, document):
    flavor_metadata(primary)
    values = {f['id']: {v['id'] for v in f['values']} for f in document['selection']['facets']}
    if values.get('base', set()) - set(primary['variants']):
        raise ConfigError('unknown primary base facet')
    metadata = primary['flavor_metadata']
    for key in ('desktop', 'edition'):
        if values.get(key, set()) - {v[key] for v in metadata.values()}:
            raise ConfigError('unknown primary flavor facet')
    cells = {}
    for variant_id, variant in primary['variants'].items():
        for flavor in variant['flavors']:
            if flavor['build_image']:
                for platform in flavor.get('platforms', variant['platforms']):
                    cells[f"{variant_id}:{flavor['id']}:{platform}"] = (variant_id, flavor['id'], platform)
    references = [r['leaf_id'] for r in document['selection']['recommendations']]
    if document['default_selection']['kind'] == 'leaf':
        references.append(document['default_selection']['leaf_id'])
    for reference in references:
        if reference not in cells:
            raise ConfigError('default/recommendation must reference a build-enabled primary cell')
        base, flavor, platform = cells[reference]
        facets = {'base': base, 'platform': platform, **metadata[flavor]}
        if any(key in values and value not in values[key] for key, value in facets.items()):
            raise ConfigError('default/recommendation excluded by configured facets')
