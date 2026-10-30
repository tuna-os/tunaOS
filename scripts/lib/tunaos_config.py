"""Primary TOML matrix and desktop policy with generated compatibility adapters.

All supported Python versions use the same reviewed TOML 1.0 parser.
Base/shared package and branding ownership remain later migration milestones.
"""
from __future__ import annotations

import configparser
import copy
import hashlib
import sys
import importlib.util
from functools import lru_cache
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from urllib.parse import urlsplit

TOMLI_VERSION = '2.3.2'
_VENDOR = Path(__file__).with_name('_vendor') / 'tomli'
# A path-specific namespace keeps copied checkout imports independent.
_VENDOR_NAME = '_tunaos_tomli_' + hashlib.sha256(str(_VENDOR.resolve()).encode()).hexdigest()
try:
    _spec = importlib.util.spec_from_file_location(
        _VENDOR_NAME, _VENDOR / '__init__.py', submodule_search_locations=[str(_VENDOR)])
    if _spec is None or _spec.loader is None:
        raise ImportError('vendored parser loader is unavailable')
    tomllib = importlib.util.module_from_spec(_spec)
    sys.modules[_VENDOR_NAME] = tomllib
    _spec.loader.exec_module(tomllib)
    if getattr(tomllib, '__version__', None) != TOMLI_VERSION:
        raise ImportError('vendored parser version mismatch')
except (ImportError, OSError) as exc:
    raise SystemExit(f'TunaOS vendored Tomli {TOMLI_VERSION} is unavailable; restore the reviewed source checkout: {exc}') from exc

ROOT = Path(__file__).resolve().parents[2]
ID = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
PLATFORMS = {"linux/amd64", "linux/amd64/v2", "linux/amd64/v3", "linux/arm64"}
# Identity values land in os-release (written as KEY="value" through a sed with
# "|" as delimiter) and in JSON heredocs, so no quote, backslash, pipe, backtick
# or dollar may appear. Names and codenames are plain words.
DISPLAY_TEXT = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9 .,()+_-]*[A-Za-z0-9.,()+_-])?\Z")
FORBIDDEN_URL_CHARACTER = re.compile(r"[\s\"'\\|`$]")
CPE_PART = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
BRANDING_URLS = ('homepage', 'documentation', 'support', 'bug_report')
# The stock usage-report service answers only for TunaOS's own variant and
# flavor ids. An image that carries other project identity must not report to it.
STOCK_PROJECT = ('TunaOS', 'tunaos')
STOCK_COUNTME_HOST = 'countme.tunaos.org'
PROJECT_REQUIRED = ('name', 'id', 'cpe_vendor', 'website', 'docs_url')
PROJECT_OPTIONAL = ('countme_endpoint', 'countme_metrics_url')
# Labels such as "Fedora's deep blue" reach /etc/issue and a JSON heredoc:
# apostrophes are fine there, double quotes and shell metacharacters are not.
LABEL_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,()+_'-]*\Z")
ACCENT = re.compile(r"#[0-9A-F]{6}\Z")
# GNOME takes only these fixed accent names, not an arbitrary colour.
GNOME_ACCENTS = {'blue', 'teal', 'green', 'yellow', 'orange', 'red', 'pink', 'purple', 'slate'}
# A theme directory under system_files/usr/share/plymouth/themes/.
PLYMOUTH_THEME = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
DEFAULT_BRANDING = BRANDING_URLS + ('plymouth',)
VARIANT_BRANDING = ('accent', 'gnome_accent', 'base', 'homage', 'plymouth')
# Variant keys with their own adapters under build_scripts/lib/, not the matrix.
IDENTITY_KEYS = ('codename', 'branding', 'packages')
# Variant keys that shape the generated GitHub workflows, not the build matrix
# (scripts/generate-workflows.py reads them from tunaos.toml): the nightly cron
# whether the manual build-flavor.yml sweep dispatches the variant, and which
# variants the two Asahi sweeps (verify-asahi.yml, asahi-hw-nightly.yml) cover.
WORKFLOW_KEYS = ('schedule', 'flavor_dispatch', 'asahi_verify', 'asahi_hardware')
# RFC 018: days a digest must spend as a cell's :<flavor>-testing image before
# promote-stable.yml may move the bare (stable) tag to it. [defaults] soak_days
# overrides this for every variant and variants.<v>.soak_days for one variant.
DEFAULT_SOAK_DAYS = 3
# Five cron fields of digits and the */,- operators: it is written into a
# double-quoted YAML scalar, so nothing else may reach it.
CRON = re.compile(r"[0-9*/,-]+(?: [0-9*/,-]+){4}\Z")
# Image-wide package additions ([defaults.packages], variants.<v>.packages).
# Plain native names only: no options, URLs, local archives or expressions.
PACKAGE_DELTA_KEYS = ('add', 'optional', 'repositories')
PACKAGE_NAME = r"[A-Za-z0-9][A-Za-z0-9+_.-]*"
PACKAGE_NAMES = {'apt': re.compile(r"[a-z0-9][a-z0-9+.-]*\Z"),
                 'emerge': re.compile(PACKAGE_NAME + '/' + PACKAGE_NAME + r'\Z')}
PACKAGE_ARCHIVE = re.compile(r"\.(rpm|deb|udeb|ebuild|tbz2|gpkg\.tar|pkg\.tar(\.[a-z0-9]+)?)\Z", re.I)
REPOSITORY_ID = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
REPOSITORY_URL = re.compile(r"https://[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~%+,:=@/-]*)?\Z")
# The Containerfile a variant builds with decides its package manager.
ROUTE_MANAGERS = {'Containerfile.el10': 'dnf', 'Containerfile.ubuntu': 'apt', 'Containerfile.debian': 'apt',
                  'Containerfile.arch': 'pacman', 'Containerfile.opensuse': 'zypper', 'Containerfile.gentoo': 'emerge'}
# OCI distribution grammar: a registry host with an optional port, and
# lowercase repository path components separated by "/".
REGISTRY = re.compile(r"(?:localhost|[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)(?::[0-9]{1,5})?\Z")
NAMESPACE = re.compile(r"[a-z0-9]+(?:(?:\.|_|__|-+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:\.|_|__|-+)[a-z0-9]+)*)*\Z")


class ConfigError(ValueError):
    """Invalid primary configuration; never fall back to stock data."""


def parse(source, path='<string>'):
    """Parse the host-independent grammar and report resource limits cleanly."""
    try:
        if isinstance(source, bytes):
            source = source.decode('utf-8')
        return tomllib.loads(source)
    except (ValueError, RecursionError) as exc:
        raise ConfigError(f'{path}: {exc}') from exc


def table(value, allowed, required, path):
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: expected table")
    unknown, missing = set(value) - set(allowed), set(required) - set(value)
    if unknown or missing:
        problems = ([f"unknown keys {sorted(unknown)}"] if unknown else []) + ([f"missing keys {sorted(missing)}"] if missing else [])
        raise ConfigError(f"{path}: {'; '.join(problems)}")


def https_url(value):
    if not isinstance(value, str) or FORBIDDEN_URL_CHARACTER.search(value):
        return False
    try:
        parsed = urlsplit(value)
        parsed.port  # Validate an optional numeric port and its range.
    except ValueError:
        return False
    return (
        parsed.scheme == 'https'
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )

def site_url(value, path):
    """A site root or docs root: https, no query or fragment, no trailing slash."""
    if not https_url(value) or value.endswith('/') or '?' in value or '#' in value:
        raise ConfigError(f'{path}: expected an https:// URL without a trailing slash, query or fragment, such as https://acme.example')


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


def plymouth_theme(value, path):
    if not isinstance(value, str) or not PLYMOUTH_THEME.fullmatch(value):
        raise ConfigError(f"{path}: expected a theme directory name (lowercase letters, digits, -)")


def soak_days(value, path):
    if type(value) is not int or value < 1:
        raise ConfigError(f"{path}: expected a positive integer number of days")


def package_delta(value, path):
    """Shape of [defaults.packages] / variants.<v>.packages; names are checked
    against the variant's package manager when the adapter is rendered."""
    if isinstance(value, dict) and 'remove' in value:
        raise ConfigError(f'{path}.remove: package removals are not supported; a removal can take out '
                          'packages the base or desktop needs, and no protected removal exists yet (#3668)')
    table(value, PACKAGE_DELTA_KEYS, (), path)
    for key in ('add', 'optional'):
        if key in value:
            strings(value[key], f'{path}.{key}')
            for name in value[key]:
                if not re.fullmatch(PACKAGE_NAME + f'(?:/{PACKAGE_NAME})?', name) or PACKAGE_ARCHIVE.search(name):
                    raise ConfigError(f'{path}.{key}: {name!r} is not a plain native package name')
    repositories = value.get('repositories', [])
    if not isinstance(repositories, list) or (not repositories and 'repositories' in value):
        raise ConfigError(f'{path}.repositories: expected nonempty list of tables')
    for index, repo in enumerate(repositories):
        where = f'{path}.repositories[{index}]'
        table(repo, ('id', 'url', 'key_url'), ('id', 'url', 'key_url'), where)
        if not isinstance(repo['id'], str) or not REPOSITORY_ID.fullmatch(repo['id']):
            raise ConfigError(f'{where}.id: expected a lowercase filename-safe token')
        for key in ('url', 'key_url'):
            if not isinstance(repo[key], str) or not REPOSITORY_URL.fullmatch(repo[key]):
                raise ConfigError(f'{where}.{key}: expected a literal https:// URL without query, fragment or credentials')


@lru_cache(maxsize=1)
def package_policy():
    spec = importlib.util.spec_from_file_location('tunaos_package_policy', Path(__file__).with_name('tunaos_packages.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def flatpak_policy():
    spec = importlib.util.spec_from_file_location('flatpak_preinstall_policy', Path(__file__).with_name('flatpak_preinstall.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def package_catalog_schema():
    spec = importlib.util.spec_from_file_location('tunaos_package_catalogs', Path(__file__).with_name('package_catalogs.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(config):
    """Validate the implemented surface; reject inert future sections."""
    table(config, ('schema_version', 'build', 'iso_groups', 'iso_delivery', 'sibling_images', 'tuna_rollout', 'variants', 'package_groups', 'desktops', 'iso_builder', 'flavor_metadata', 'flatpak_preinstall', 'package_catalogs', 'project', 'defaults'),
          ('schema_version', 'build', 'iso_groups', 'sibling_images', 'tuna_rollout', 'variants'), 'config')
    if 'desktops' in config or 'package_groups' in config:
        tunaos_packages = package_policy()
        try:
            tunaos_packages.validate({key: config[key] for key in ('package_groups', 'desktops') if key in config})
        except tunaos_packages.PolicyError as exc:
            raise ConfigError(str(exc)) from exc
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ConfigError('schema_version: expected integer 1')
    table(config['build'], ('global_platforms', 'publish'), ('global_platforms',), 'build')
    strings(config['build']['global_platforms'], 'build.global_platforms', platform=True)
    if 'iso_delivery' in config:
        policy = config['iso_delivery']
        table(policy, ('cutover_targets', 'retained_r2_isos'),
              ('cutover_targets', 'retained_r2_isos'), 'iso_delivery')
        if not isinstance(policy['cutover_targets'], list):
            raise ConfigError('iso_delivery.cutover_targets: expected list')
        if not isinstance(policy['retained_r2_isos'], list):
            raise ConfigError('iso_delivery.retained_r2_isos: expected list')
        for i, name in enumerate(policy['retained_r2_isos']):
            text(name, f'iso_delivery.retained_r2_isos[{i}]')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+~-]*\.iso', name):
                raise ConfigError(f'iso_delivery.retained_r2_isos[{i}]: unsafe ISO basename')
        if len(policy['retained_r2_isos']) != len(set(policy['retained_r2_isos'])):
            raise ConfigError('iso_delivery.retained_r2_isos: duplicate ISO basename')
        target_fields = ('variant', 'flavor', 'platform', 'qualification', 'qualified_at', 'evidence')
        for i, target in enumerate(policy['cutover_targets']):
            where = f'iso_delivery.cutover_targets[{i}]'
            table(target, target_fields, target_fields, where)
            for key in target_fields:
                text(target[key], f'{where}.{key}')
            if target['platform'] not in PLATFORMS:
                raise ConfigError(f'{where}.platform: unsupported platform')
            if target['qualification'] != 'browser-qualified':
                raise ConfigError(f'{where}.qualification: expected browser-qualified')
            qualified_at = target['qualified_at']
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', qualified_at):
                raise ConfigError(f'{where}.qualified_at: expected ISO date YYYY-MM-DD')
            try:
                datetime.strptime(qualified_at, '%Y-%m-%d')
            except ValueError as exc:
                raise ConfigError(f'{where}.qualified_at: invalid ISO date') from exc
    if 'project' in config:
        table(config['project'], PROJECT_REQUIRED + PROJECT_OPTIONAL, PROJECT_REQUIRED, 'project')
        if not isinstance(config['project']['name'], str) or not DISPLAY_TEXT.fullmatch(config['project']['name']):
            raise ConfigError('project.name: expected plain words (letters, digits, spaces, .,()+_-)')
        identifier(config['project']['id'], 'project.id')
        if not isinstance(config['project']['cpe_vendor'], str) or not CPE_PART.fullmatch(config['project']['cpe_vendor']):
            raise ConfigError('project.cpe_vendor: expected a lowercase CPE vendor such as acme '
                              '(letters, digits and ._-)')
        project = config['project']
        for key in ('website', 'docs_url'):
            site_url(project[key], f'project.{key}')
        endpoint = project.get('countme_endpoint', '')
        metrics = project.get('countme_metrics_url', '')
        for key, value in (('countme_endpoint', endpoint), ('countme_metrics_url', metrics)):
            if value != '' and not https_url(value):
                raise ConfigError(f'project.{key}: expected an https:// URL, or "" to disable usage reports')
        if endpoint and urlsplit(endpoint).hostname == STOCK_COUNTME_HOST and (project['name'], project['id']) != STOCK_PROJECT:
            raise ConfigError(f"project.countme_endpoint: {endpoint!r} is TunaOS's own usage-report service, but project.name/id "
                              f"are {project['name']!r}/{project['id']!r}; set your own endpoint, or \"\" to send no reports")
        if metrics and not endpoint:
            raise ConfigError('project.countme_metrics_url: set without project.countme_endpoint; usage reports are disabled, '
                              'so there is no public page to link')
    if 'defaults' in config:
        table(config['defaults'], ('branding', 'packages', 'soak_days'), ('branding',), 'defaults')
        if 'soak_days' in config['defaults']:
            soak_days(config['defaults']['soak_days'], 'defaults.soak_days')
        if 'packages' in config['defaults']:
            package_delta(config['defaults']['packages'], 'defaults.packages')
        table(config['defaults']['branding'], DEFAULT_BRANDING, DEFAULT_BRANDING, 'defaults.branding')
        for key in BRANDING_URLS:
            value = config['defaults']['branding'][key]
            if not https_url(value):
                raise ConfigError(f'defaults.branding.{key}: expected an https:// URL')
        plymouth_theme(config['defaults']['branding']['plymouth'], 'defaults.branding.plymouth')
    if 'publish' in config['build']:
        # Optional: a fork's own destination. Omitted, CI publishes to the
        # repository owner's namespace, so the stock file stays fork-neutral.
        publish = config['build']['publish']
        table(publish, ('registry', 'namespace'), ('registry', 'namespace'), 'build.publish')
        if not isinstance(publish['registry'], str) or not REGISTRY.fullmatch(publish['registry']):
            raise ConfigError('build.publish.registry: expected a lowercase registry host such as ghcr.io')
        if not isinstance(publish['namespace'], str) or not NAMESPACE.fullmatch(publish['namespace']):
            raise ConfigError('build.publish.namespace: expected lowercase OCI path components such as acme')
    variants = config['variants']
    if not isinstance(variants, dict) or not variants:
        raise ConfigError('variants: expected nonempty table')
    for name, variant in variants.items():
        where = f'variants.{name}'
        identifier(name, where)
        table(variant, ('emoji', 'description', 'base_image', 'aliases', 'platforms', 'flavors',
                        'upstream_track', 'experimental', 'akmods', 'publish_name', 'tag_suffix', 'codename', 'branding',
                        'packages', 'soak_days', *WORKFLOW_KEYS),
              ('emoji', 'description', 'base_image', 'platforms', 'flavors'), where)
        for key in ('emoji', 'description', 'base_image', 'upstream_track', 'akmods', 'publish_name', 'tag_suffix'):
            if key in variant:
                text(variant[key], where + '.' + key)
        if 'codename' in variant and (not isinstance(variant['codename'], str) or not DISPLAY_TEXT.fullmatch(variant['codename'])):
            raise ConfigError(f'{where}.codename: expected plain words (letters, digits, spaces, .,()+_-)')
        if 'branding' in variant:
            branding = variant['branding']
            table(branding, VARIANT_BRANDING, VARIANT_BRANDING, where + '.branding')
            if not isinstance(branding['accent'], str) or not ACCENT.fullmatch(branding['accent']):
                raise ConfigError(f'{where}.branding.accent: expected #RRGGBB in uppercase hex')
            if branding['gnome_accent'] not in GNOME_ACCENTS:
                raise ConfigError(f'{where}.branding.gnome_accent: expected one of {sorted(GNOME_ACCENTS)}')
            for key in ('base', 'homage'):
                if not isinstance(branding[key], str) or not LABEL_TEXT.fullmatch(branding[key]):
                    raise ConfigError(f"{where}.branding.{key}: expected plain words (letters, digits, spaces, .,()+_'-)")
            plymouth_theme(branding['plymouth'], where + '.branding.plymouth')
        if 'packages' in variant:
            package_delta(variant['packages'], where + '.packages')
        if 'experimental' in variant and type(variant['experimental']) is not bool:
            raise ConfigError(f'{where}.experimental: expected boolean')
        if 'soak_days' in variant:
            soak_days(variant['soak_days'], where + '.soak_days')
        if 'schedule' in variant:
            if not isinstance(variant['schedule'], str) or not CRON.fullmatch(variant['schedule']):
                raise ConfigError(f'{where}.schedule: expected five cron fields such as "20 0 * * *"')
            if variant.get('experimental'):
                raise ConfigError(f'{where}.schedule: an experimental variant is dispatch-only and has no nightly')
        for key in ('flavor_dispatch', 'asahi_verify', 'asahi_hardware'):
            if key in variant and type(variant[key]) is not bool:
                raise ConfigError(f'{where}.{key}: expected boolean')
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
    if 'flatpak_preinstall' in config:
        try:
            flatpak_policy().validate(config)
        except flatpak_policy().PolicyError as exc:
            raise ConfigError(str(exc)) from exc
        remote_url = config['flatpak_preinstall'].get('remote_url', '')
        if remote_url != '' and (not https_url(remote_url) or not urlsplit(remote_url).path.endswith('.flatpakrepo')):
            raise ConfigError('flatpak_preinstall.remote_url: expected an https:// URL of a .flatpakrepo file, '
                              'or "" to register no tuna-os remote')
    if 'iso_builder' in config or 'flavor_metadata' in config:
        module_path = Path(__file__).with_name('iso_builder_config.py')
        spec = importlib.util.spec_from_file_location('iso_builder_config', module_path)
        if spec is None or spec.loader is None:
            raise ConfigError(f'iso_builder: cannot load validator at {module_path}')
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except OSError as exc:
            raise ConfigError(f'iso_builder: cannot read validator at {module_path}: {exc}') from exc
        try:
            if 'flavor_metadata' in config:
                module.flavor_metadata(config)
            if 'iso_builder' in config:
                module.project(config)
        except module.ConfigError as exc:
            raise ConfigError(f'iso_builder: {exc}') from exc
    if 'package_catalogs' in config:
        catalogs = package_catalog_schema()
        try:
            catalogs.validate_document(config)
        except catalogs.CatalogError as exc:
            raise ConfigError(f'package_catalogs: {exc}') from exc
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
        source = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f'{path}: {exc}') from exc
    return validate(parse(source, path))


def matrix(config):
    """Project the old consumer shape without inventing defaults or losing flags."""
    validate(config)
    # Identity (codename, branding) has its own adapters, and the workflow
    # keys (schedule, flavor_dispatch) are read from tunaos.toml by
    # scripts/generate-workflows.py; keep both out of the build matrix so
    # every jq/yq consumer of build-config.yml sees the unchanged shape.
    # soak_days (RFC 018) is resolved per variant once [defaults] declares it,
    # so promote-stable.yml reads one number per cell; a source without it
    # keeps the historical shape and readers fall back to DEFAULT_SOAK_DAYS.
    default_soak = config.get('defaults', {}).get('soak_days')
    projected = copy.deepcopy({'config': config['build'], 'iso_groups': config['iso_groups'],
                          'sibling_images': config['sibling_images'], 'tuna_rollout': config['tuna_rollout'],
                          'variants': [{'id': name, **{k: v for k, v in value.items() if k not in IDENTITY_KEYS + WORKFLOW_KEYS},
                                        **({} if default_soak is None else {'soak_days': value.get('soak_days', default_soak)})}
                                       for name, value in config['variants'].items()]})
    if 'iso_delivery' in config:
        projected['iso_delivery'] = copy.deepcopy(config['iso_delivery'])
    return projected


def render(config):
    # JSON is also YAML; old jq/yq/PyYAML consumers keep their data contract.
    return json.dumps(matrix(config), ensure_ascii=False, indent=2) + '\n'


def render_identity(config):
    """Shell adapter sourced by build_scripts/90-image-info.sh in every image.

    Committed beside the other build scripts so overlay and Debian contexts,
    which do not carry manifests/, read the same values. TunaOS's own identity
    passes through here exactly like a fork's; there is no stock fallback.
    """
    validate(config)
    missing = [key for key in ('project', 'defaults') if key not in config]
    unnamed = [name for name, variant in config['variants'].items() if 'codename' not in variant]
    needs = []
    if missing:
        needs.append('identity needs sections: ' + ', '.join(missing))
    if unnamed:
        needs.append('identity needs a codename for variants: ' + ', '.join(unnamed))
    if needs:
        raise ConfigError('; '.join(needs))
    project, urls = config['project'], config['defaults']['branding']
    lines = ['# Generated from tunaos.toml by `scripts/config.py generate-identity`; do not edit.',
             f"TUNAOS_PROJECT_NAME={shlex.quote(project['name'])}",
             f"TUNAOS_PROJECT_ID={shlex.quote(project['id'])}",
             f"TUNAOS_CPE_VENDOR={shlex.quote(project['cpe_vendor'])}",
             f"TUNAOS_HOME_URL={shlex.quote(urls['homepage'])}",
             f"TUNAOS_DOCUMENTATION_URL={shlex.quote(urls['documentation'])}",
             f"TUNAOS_SUPPORT_URL={shlex.quote(urls['support'])}",
             f"TUNAOS_BUG_REPORT_URL={shlex.quote(urls['bug_report'])}",
             # Boot splash for a variant that has no branding row.
             f"TUNAOS_PLYMOUTH_THEME={shlex.quote(urls['plymouth'])}",
             f"TUNAOS_WEBSITE={shlex.quote(project['website'])}",
             f"TUNAOS_DOCS_URL={shlex.quote(project['docs_url'])}",
             # Empty means the image sends no usage reports / registers no remote.
             f"TUNAOS_COUNTME_ENDPOINT={shlex.quote(project.get('countme_endpoint', ''))}",
             f"TUNAOS_COUNTME_METRICS_URL={shlex.quote(project.get('countme_metrics_url', ''))}",
             f"TUNAOS_FLATPAK_REMOTE_URL={shlex.quote(config.get('flatpak_preinstall', {}).get('remote_url', ''))}",
             # -g: stays global even when a caller sources this inside a function.
             'declare -gA TUNAOS_CODENAMES=(']
    # Double-quote every key even when its characters happen to be shell-safe:
    # formatters must never reinterpret a hyphenated associative subscript.
    lines += [
        f'\t[{json.dumps(name)}]={shlex.quote(config["variants"][name]["codename"])}'
        for name in sorted(config['variants'])
    ]
    return '\n'.join(lines + [')']) + '\n'


VARIANT_IDENTITY_HEADER = """\
# Per-variant identity: what makes each variant look like itself.
# Generated from each variant's `branding` in tunaos.toml by
# `scripts/config.py generate-variant-identity`; do not edit. `just check`
# fails when this file and tunaos.toml disagree.
#
# Every variant is TunaOS first, but wears one accent colour borrowed from the
# distro it is built on, as a nod to that project: Arch blue for marlin,
# Ubuntu orange for grouper, openSUSE green for sailfin, and so on.
#
# Read by build_scripts/90-image-info.sh, plymouth-set-theme.sh and the
# desktop branding hooks at build time.
#
# gnome_accent is the nearest of GNOME's fixed accent names (blue teal green
# yellow orange red pink purple slate); GNOME cannot take an arbitrary colour.
# plymouth is the boot splash, a theme under system_files/usr/share/plymouth/themes/.
#
# id\taccent\tgnome_accent\tbase\thomage\tplymouth
"""


def render_variant_identity(config):
    """build_scripts/lib/variant-identity.tsv, at its existing path and format."""
    validate(config)
    unbranded = [name for name, variant in config['variants'].items() if 'branding' not in variant]
    if unbranded:
        raise ConfigError('variant identity needs branding for ' + ', '.join(unbranded))
    rows = ['\t'.join([name] + [variant['branding'][key] for key in VARIANT_BRANDING])
            for name, variant in config['variants'].items()]
    return VARIANT_IDENTITY_HEADER + '\n'.join(rows) + '\n'


VARIANT_ALIASES_HEADER = """\
# Friendly alias tags and the variant each belongs to. Generated from each
# variant's `aliases` in tunaos.toml by `scripts/config.py
# generate-variant-aliases`; do not edit. `just check` fails when this file
# and tunaos.toml disagree.
#
# An alias is a second tag for the same digest, so it never becomes the
# image's identity. Builds that derive IMAGE_NAME from the base distro arrive
# as the alias (sailfin as "opensuse"); 90-image-info.sh and
# plymouth-set-theme.sh fold it back with this table. When two variants share
# an alias (bonito and bonito-rawhide both publish "fedora"), the first in
# tunaos.toml owns it.
#
# alias\tvariant
"""


def render_variant_aliases(config):
    """build_scripts/lib/variant-aliases.tsv: alias -> canonical variant."""
    validate(config)
    owners = {}
    for name, variant in config['variants'].items():
        for alias in variant.get('aliases', []):
            owners.setdefault(alias, name)
    return VARIANT_ALIASES_HEADER + ''.join(f'{alias}\t{name}\n' for alias, name in owners.items())


IMAGE_PACKAGES_HEADER = """\
# Image-wide package additions per variant. Generated from [defaults.packages]
# and each variant's `packages` in tunaos.toml by `scripts/config.py
# generate-image-packages`; do not edit. `just check` fails when this file and
# tunaos.toml disagree.
#
# build_scripts/30-image-packages.sh installs a variant's rows in the base
# stage of every Containerfile, so every flavor has them. A variant with no
# rows builds exactly as before. Removals are not supported.
#
# variant\tmanager\tadd|optional\tname
# variant\tmanager\trepository\tid\turl\tkey_url
"""


def variant_managers(config, names, root=ROOT):
    """The package manager each variant builds with, from its Containerfile route."""
    managers = {}
    for name in names:
        found = set()
        for flavor in config['variants'][name]['flavors']:
            output = subprocess.run(['bash', str(Path(root) / 'scripts/resolve-flavor.sh'), name, flavor['id']],
                                    capture_output=True, text=True, check=True).stdout
            routing = {key: json.loads(value) for key, value in (line.split('=', 1) for line in output.splitlines())}
            if routing['CONTAINERFILE'] in ROUTE_MANAGERS:
                found.add(ROUTE_MANAGERS[routing['CONTAINERFILE']])
        if len(found) != 1:
            raise ConfigError(f'variants.{name}: expected one package manager route, found {sorted(found)}')
        managers[name] = found.pop()
    return managers


def image_packages(config, managers=None):
    """Effective additions per variant: [defaults.packages] first, then its own."""
    validate(config)
    defaults = config.get('defaults', {}).get('packages', {})
    deltas = {}
    for name, variant in config['variants'].items():
        own = variant.get('packages', {})
        add = list(dict.fromkeys(defaults.get('add', []) + own.get('add', [])))
        optional = list(dict.fromkeys(defaults.get('optional', []) + own.get('optional', [])))
        if set(add) & set(optional):
            raise ConfigError(f'variants.{name}.packages: both required and optional: {sorted(set(add) & set(optional))}')
        repositories = {}
        for repo in defaults.get('repositories', []) + own.get('repositories', []):
            if repositories.setdefault(repo['id'], repo) != repo:
                raise ConfigError(f"variants.{name}.packages: repository {repo['id']!r} is defined twice, differently")
        if add or optional or repositories:
            deltas[name] = {'add': add, 'optional': optional, 'repositories': list(repositories.values())}
    managers = managers or variant_managers(config, deltas)
    for name, delta in deltas.items():
        manager = delta['manager'] = managers[name]
        pattern = PACKAGE_NAMES.get(manager, re.compile(PACKAGE_NAME + r'\Z'))
        shared = set(defaults.get('add', []) + defaults.get('optional', []))
        for package in delta['add'] + delta['optional']:
            if not pattern.fullmatch(package):
                where = 'defaults.packages' if package in shared else f'variants.{name}.packages'
                hint = (' (use category/name)' if manager == 'emerge' else '') + (
                    f'; [defaults.packages] reaches every variant, so move {package!r} to the variants whose package manager names it differently'
                    if package in shared else '')
                raise ConfigError(f'{where}: {package!r} is not a valid package name for {manager}, which variant {name} builds with{hint}')
        if delta['repositories'] and manager not in ('dnf', 'zypper'):
            own_repositories = config['variants'][name].get('packages', {}).get('repositories')
            where = f'variants.{name}.packages' if own_repositories else 'defaults.packages'
            raise ConfigError(f'{where}: repositories are supported on dnf and zypper only, not {manager}, which variant {name} builds with')
    return deltas


def render_image_packages(config, managers=None):
    """build_scripts/lib/image-packages.tsv, read by 30-image-packages.sh."""
    rows = []
    for name, delta in image_packages(config, managers).items():
        rows += [f"{name}\t{delta['manager']}\t{kind}\t{package}" for kind in ('add', 'optional') for package in delta[kind]]
        rows += [f"{name}\t{delta['manager']}\trepository\t{repo['id']}\t{repo['url']}\t{repo['key_url']}"
                 for repo in delta['repositories']]
    return IMAGE_PACKAGES_HEADER + ''.join(row + '\n' for row in rows)


def _file_prefix(path, size):
    with open(path, 'rb') as handle:
        return handle.read(size)


def drawn_artwork_problems(config, root=ROOT):
    """Drawn art each variant needs, which no generator can make from TOML.

    Wallpapers and boot splashes are fork-supplied: select-wallpaper.sh picks
    <variant>.jpg (an optional <variant>-anime.jpg or <variant>-<desktop>.jpg
    wins over it), and plymouth-set-theme.sh installs branding.plymouth.
    A file that is present can still be wrong in the two ways a fork produces
    by copying: a wallpaper that is not a JPEG (a renamed PNG, a placeholder),
    and a copied theme whose .plymouth still names the theme it was copied
    from, so the image would boot the old splash.
    """
    validate(config)
    root = Path(root)
    backgrounds = root / 'system_files/usr/share/backgrounds/tunaos'
    themes = root / 'system_files/usr/share/plymouth/themes'
    wanted = {f'{backgrounds.relative_to(root)}/tunaos-default.jpg (the generic wallpaper)': backgrounds / 'tunaos-default.jpg'}
    splashes = {config['defaults']['branding']['plymouth']: 'defaults.branding.plymouth'}
    for name, variant in config['variants'].items():
        wanted[f'{backgrounds.relative_to(root)}/{name}.jpg (variants.{name})'] = backgrounds / f'{name}.jpg'
        splashes.setdefault(variant['branding']['plymouth'], f'variants.{name}.branding.plymouth')
    for theme, owner in splashes.items():
        for suffix in ('plymouth', 'script'):
            wanted[f'{themes.relative_to(root)}/{theme}/{theme}.{suffix} ({owner})'] = themes / theme / f'{theme}.{suffix}'
    problems = [f'{label}: missing' for label, path in wanted.items() if not path.is_file()]
    for label, path in wanted.items():
        if path.is_file() and path.suffix == '.jpg' and _file_prefix(path, 3) != b'\xff\xd8\xff':
            problems.append(f'{label}: not a JPEG (a wallpaper must be a JPEG file, not a renamed PNG or a placeholder)')
    for theme, owner in splashes.items():
        descriptor = themes / theme / f'{theme}.plymouth'
        if not descriptor.is_file():
            continue
        # Plymouth reads these two keys from the [script] section, as INI.
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        try:
            parser.read_string(descriptor.read_text(encoding='utf-8', errors='replace'))
        except configparser.Error:
            parser = configparser.ConfigParser(interpolation=None)
        keys = dict(parser['script']) if parser.has_section('script') else {}
        expected = {'ImageDir': f'/usr/share/plymouth/themes/{theme}', 'ScriptFile': f'/usr/share/plymouth/themes/{theme}/{theme}.script'}
        for key, value in expected.items():
            if keys.get(key) != value:
                problems.append(f'{descriptor.relative_to(root)} ({owner}): {key} is {keys.get(key)!r}, expected {value!r}; '
                                'a theme copied from another keeps that theme\'s paths until you edit them')
    return problems


def display_names(config):
    """The name each variant shows: os-release PRETTY_NAME and its artwork.

    90-image-info.sh sets PRETTY_NAME to ${IMAGE_NAME^} where IMAGE_NAME is the
    publish name (bonito-rawhide publishes as bonito), so only the first
    character is uppercased. The artwork generators use the same rule.
    """
    validate(config)
    publish_names = {name: variant.get('publish_name') or name for name, variant in config['variants'].items()}
    return {name: published[:1].upper() + published[1:] for name, published in publish_names.items()}


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
    document = validate(parse(source, root / 'tunaos.toml'))
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
