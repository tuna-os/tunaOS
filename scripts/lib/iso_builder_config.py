"""Portable ISO Builder presentation contract. No catalog or transport authority."""
from __future__ import annotations

import copy
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
    table(document, ('schema_version', 'preview_only', 'brand', 'presentation', 'output', 'desktops', 'variants', 'default_selection', 'curated_app_sets'), ('ddi_channels',))
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ConfigError('schema_version must be integer 1')
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
    table(document['presentation'], ('headline', 'intro', 'accent_color'))
    for value in document['presentation'].values():
        text(value)
    pattern(document['presentation']['accent_color'], r'#[0-9a-fA-F]{6}')
    table(document['output'], ('volume_label', 'filename_prefix'))
    pattern(document['output']['volume_label'], r'[A-Z0-9_]{1,32}')
    pattern(document['output']['filename_prefix'], r'[a-z0-9][a-z0-9_-]{0,63}')
    desktops = entries(document['desktops'], ('id', 'name', 'description', 'default_flatpaks'), 'desktops')
    for desktop in document['desktops']:
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
        # Syntax only. Inspection, relay admission and qualification remain engine policy.
        pattern(selection['image'], r'[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[0-9a-f]{64})')
    if selection['platform'] not in ('linux/amd64', 'linux/amd64/v2', 'linux/amd64/v3', 'linux/arm64'):
        raise ConfigError('unsupported platform')
    entries(document['curated_app_sets'], ('id', 'label', 'desktops', 'url', 'format'), 'curated_app_sets')
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
    validate(result)
    variants = primary['variants']
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
