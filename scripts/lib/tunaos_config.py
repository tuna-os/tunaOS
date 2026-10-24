"""Primary TOML matrix and desktop policy with generated compatibility adapters.

All supported Python versions use the same reviewed TOML 1.0 parser.
Base/shared package and branding ownership remain later migration milestones.
"""
from __future__ import annotations

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
import tempfile

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
HTTPS_URL = re.compile(r"https://[^\s/\"'\\|`$]+(?:/[^\s\"'\\|`$]*)?\Z")
CPE_PART = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
BRANDING_URLS = ('homepage', 'documentation', 'support', 'bug_report')
# Labels such as "Fedora's deep blue" reach /etc/issue and a JSON heredoc:
# apostrophes are fine there, double quotes and shell metacharacters are not.
LABEL_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,()+_'-]*\Z")
ACCENT = re.compile(r"#[0-9A-F]{6}\Z")
# GNOME takes only these fixed accent names, not an arbitrary colour.
GNOME_ACCENTS = {'blue', 'teal', 'green', 'yellow', 'orange', 'red', 'pink', 'purple', 'slate'}
VARIANT_BRANDING = ('accent', 'gnome_accent', 'base', 'homage')
# Identity-only variant keys: they have their own adapters, not the matrix.
IDENTITY_KEYS = ('codename', 'branding')
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
    table(config, ('schema_version', 'build', 'iso_groups', 'sibling_images', 'tuna_rollout', 'variants', 'package_groups', 'desktops', 'iso_builder', 'flavor_metadata', 'flatpak_preinstall', 'package_catalogs', 'project', 'defaults'),
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
    if 'project' in config:
        table(config['project'], ('name', 'id', 'cpe_vendor'), ('name', 'id', 'cpe_vendor'), 'project')
        if not isinstance(config['project']['name'], str) or not DISPLAY_TEXT.fullmatch(config['project']['name']):
            raise ConfigError('project.name: expected plain words (letters, digits, spaces, .,()+_-)')
        identifier(config['project']['id'], 'project.id')
        if not isinstance(config['project']['cpe_vendor'], str) or not CPE_PART.fullmatch(config['project']['cpe_vendor']):
            raise ConfigError('project.cpe_vendor: expected a lowercase CPE component such as tunaos')
    if 'defaults' in config:
        table(config['defaults'], ('branding',), ('branding',), 'defaults')
        table(config['defaults']['branding'], BRANDING_URLS, BRANDING_URLS, 'defaults.branding')
        for key in BRANDING_URLS:
            value = config['defaults']['branding'][key]
            if not isinstance(value, str) or not HTTPS_URL.fullmatch(value):
                raise ConfigError(f'defaults.branding.{key}: expected an https:// URL')
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
                        'upstream_track', 'experimental', 'akmods', 'publish_name', 'tag_suffix', 'codename', 'branding'),
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
    if 'flatpak_preinstall' in config:
        try:
            flatpak_policy().validate(config)
        except flatpak_policy().PolicyError as exc:
            raise ConfigError(str(exc)) from exc
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
    # Identity (codename, branding) has its own adapters; keep it out of the
    # build matrix so every jq/yq consumer of build-config.yml sees the
    # unchanged shape.
    return copy.deepcopy({'config': config['build'], 'iso_groups': config['iso_groups'],
                          'sibling_images': config['sibling_images'], 'tuna_rollout': config['tuna_rollout'],
                          'variants': [{'id': name, **{k: v for k, v in value.items() if k not in IDENTITY_KEYS}}
                                       for name, value in config['variants'].items()]})


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
             # -g: stays global even when a caller sources this inside a function.
             'declare -gA TUNAOS_CODENAMES=(']
    # Keys and values stay quoted for deterministic, diff-friendly shell.
    lines += [f'\t["{name}"]="{variant["codename"]}"' for name, variant in config['variants'].items()]
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
# Read by build_scripts/90-image-info.sh and the desktop branding hooks at
# build time, and by the scripts/branding/ generators when artwork is redrawn.
#
# gnome_accent is the nearest of GNOME's fixed accent names (blue teal green
# yellow orange red pink purple slate); GNOME cannot take an arbitrary colour.
#
# id\taccent\tgnome_accent\tbase\thomage
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
