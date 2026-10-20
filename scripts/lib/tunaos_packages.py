"""Shared desktop package policy, native selection and compatibility projection."""
import copy
import json
import re
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

# Transitional implementation registry. Package-bearing operations remain
# inventoried until their arguments move into typed configuration inputs.
OPERATIONS = json.loads((Path(__file__).with_name('desktop_operations.json')).read_text())
FAMILIES = {'apt', 'pacman', 'cachyos', 'fedora', 'hummingbird', 'eln', 'el10', 'zypper', 'emerge', 'rawhide'}
LIST_FIELDS = {'required', 'optional', 'exclude', 'groups', 'group_exclude', 'optional_group'}
PROFILE_FIELDS = {'display_manager', 'minimum_version', 'packages', 'emerge_accept_keywords',
                  'versionlock', 'disable_desktop_files', 'after_install', 'after_inline'}
NATIVE_FIELDS = LIST_FIELDS | {'include', 'repos', 'copr', 'ppa', 'before_install', 'display_manager', 'group_options'}

class PolicyError(ValueError):
    pass

def known(data, allowed, where):
    if not isinstance(data, dict) or set(data) - allowed:
        raise PolicyError(f'{where}: expected table with known fields')

def string_list(value, where):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() or any(ord(c) < 32 or ord(c) == 127 for c in x) for x in value):
        raise PolicyError(f'{where}: expected list of nonempty single-line strings')

def identifier(value, where):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', value):
        raise PolicyError(f'{where}: invalid identifier')

def operation_ids(value, kind, where):
    string_list(value, where)
    if set(value) - OPERATIONS[kind].keys():
        raise PolicyError(f'{where}: unknown trusted operation')

def validate_source_records(records, kind, family, where):
    if not isinstance(records, list):
        raise PolicyError(where + ': expected repository records')
    for index, record in enumerate(records):
        item = where + f'[{index}]'
        if kind == 'repos':
            if family == 'apt':
                allowed = {'name', 'uri', 'suite', 'keyring_url', 'condition'}
                required = {'name', 'uri', 'suite', 'keyring_url'}
            elif family == 'cachyos':
                allowed = required = {'name', 'url'}
            elif family in {'el10', 'fedora', 'rawhide', 'eln', 'hummingbird', 'zypper'}:
                allowed = {'name', 'baseurl', 'priority', 'unsigned'}
                required = {'name', 'baseurl'}
            else:
                raise PolicyError(item + ': repositories unsupported for this family')
        elif kind == 'ppa' and family == 'apt':
            allowed, required = {'repo', 'condition'}, {'repo', 'condition'}
        elif kind == 'copr' and family in {'el10', 'fedora', 'rawhide', 'eln', 'hummingbird'}:
            allowed, required = {'repo', 'packages', 'options'}, {'repo', 'packages'}
        else:
            raise PolicyError(item + ': unsupported source kind for family')
        known(record, allowed, item)
        if required - set(record):
            raise PolicyError(item + ': missing required source fields')
        for key, value in record.items():
            if key == 'priority':
                if type(value) is not int or value < 1:
                    raise PolicyError(item + '.priority: expected positive integer')
            elif key == 'unsigned':
                if type(value) is not bool:
                    raise PolicyError(item + '.unsigned: expected boolean')
            elif key == 'packages':
                string_list(value, item + '.packages')
            else:
                string_list([value], item + '.' + key)
        if 'name' in record:
            identifier(record['name'], item + '.name')
        if 'condition' in record and record['condition'] not in {'ubuntu', 'debian-sid', 'debian-trixie'}:
            raise PolicyError(item + '.condition: unknown base selector')
        if kind == 'ppa' and record['condition'] != 'ubuntu':
            raise PolicyError(item + '.condition: PPA consumer supports explicit ubuntu only')
        if kind == 'ppa' and not re.fullmatch(r'ppa:[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', record['repo']):
            raise PolicyError(item + '.repo: expected explicit PPA owner/archive')
        if kind == 'copr' and not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', record['repo']):
            raise PolicyError(item + '.repo: expected explicit COPR owner/project')
        for key in ('uri', 'url', 'baseurl', 'keyring_url'):
            if key not in record:
                continue
            value = record[key]
            if value.startswith('file:'):
                trusted_mounts = {
                    ('utah-packages', 'file:///run/utah-packages'),
                    ('gnome50-el10-packages', 'file:///run/gnome50-el10-packages')}
                if key != 'baseurl' or (record.get('name'), value) not in trusted_mounts:
                    raise PolicyError(item + ': unsupported local repository mount')
            elif not re.fullmatch(r'https://[A-Za-z0-9.-]+/[A-Za-z0-9_./$+-]*', value):
                raise PolicyError(item + '.' + key + ': expected supported HTTPS source URL')
        if record.get('unsigned') and not record.get('baseurl', '').startswith('file:///run/'):
            raise PolicyError(item + ': unsigned remote repositories are unsupported')


def expand(groups, policy, stack=()):
    result = {}
    for name in policy.get('include', []):
        if name not in groups or name in stack:
            raise PolicyError(f'package_groups.{name}: unknown group or inclusion cycle')
        included = expand(groups, groups[name], (*stack, name))
        for key, values in included.items():
            result.setdefault(key, []).extend(values)
    for key, value in policy.items():
        if key == 'include':
            continue
        if key in LIST_FIELDS:
            result.setdefault(key, []).extend(copy.deepcopy(value))
        else:
            result[key] = copy.deepcopy(value)
    return result

def validate(document):
    known(document, {'package_groups', 'desktops'}, 'package policy')
    if 'package_groups' not in document:
        raise PolicyError('package_groups: required table')
    groups = document['package_groups']
    profiles = document.get('desktops', {})
    if not isinstance(groups, dict) or not isinstance(profiles, dict) or not profiles:
        raise PolicyError('package_groups/desktops: expected tables with desktop profiles')
    for name, group in groups.items():
        identifier(name, 'package_groups')
        known(group, LIST_FIELDS | {'include'}, f'package_groups.{name}')
        for key, value in group.items():
            string_list(value, f'package_groups.{name}.{key}')
        expand(groups, group, (name,))
    for name, profile in profiles.items():
        identifier(name, 'desktops')
        known(profile, PROFILE_FIELDS, f'desktops.{name}')
        if not isinstance(profile.get('packages'), dict) or set(profile['packages']) - FAMILIES:
            raise PolicyError(f'desktops.{name}.packages: unknown native family')
        for key, value in profile.items():
            if key in {'emerge_accept_keywords', 'versionlock', 'disable_desktop_files'}:
                string_list(value, name + '.' + key)
            elif key in {'after_install', 'after_inline'}:
                operation_ids(value, 'after' if key == 'after_install' else 'inline', name + '.' + key)
            elif key == 'minimum_version' and (type(value) is not int or value < 1):
                raise PolicyError(name + '.minimum_version: expected positive integer')
            elif key == 'display_manager':
                string_list([value], name + '.display_manager')
        for family, policy in profile['packages'].items():
            where = f'desktops.{name}.packages.{family}'
            allowed = NATIVE_FIELDS
            if family in {'apt', 'pacman', 'cachyos', 'zypper', 'emerge'}:
                allowed = {'required', 'include'}
                if family == 'apt':
                    allowed |= {'repos', 'ppa', 'display_manager'}
                elif family == 'cachyos':
                    allowed |= {'repos'}
                elif family == 'zypper':
                    allowed |= {'repos', 'display_manager'}
            known(policy, allowed, where)
            for key, value in policy.items():
                if key in LIST_FIELDS | {'include'}:
                    string_list(value, where + '.' + key)
                elif key == 'before_install':
                    operation_ids(value, 'before', where + '.' + key)
                elif key in {'display_manager', 'group_options'}:
                    string_list([value], where + '.' + key)
                elif key in {'repos', 'copr', 'ppa'}:
                    validate_source_records(value, key, family, where + '.' + key)
            expanded = expand(groups, policy)
            known(expanded, allowed - {'include'}, where + ' (expanded)')
    return document

def legacy_profiles(document):
    validate(document)
    result = {}
    for name, profile in document['desktops'].items():
        out = {}
        for key, value in profile.items():
            if key == 'after_install':
                out['post_install'] = [OPERATIONS['after'][x] for x in value]
            elif key == 'after_inline':
                out['post_install_inline'] = [OPERATIONS['inline'][x] for x in value]
            elif key == 'packages':
                native = {}
                for family, policy in value.items():
                    expanded = expand(document['package_groups'], policy)
                    if family in {'apt', 'pacman', 'zypper', 'emerge'} and set(expanded) == {'required'}:
                        native[family] = expanded['required']
                    else:
                        native[family] = {}
                        for field, data in expanded.items():
                            if field == 'before_install':
                                native[family]['pre_install'] = [OPERATIONS['before'][x] for x in data]
                            else:
                                native[family]['packages' if field == 'required' else field] = data
                out[key] = native
            else:
                out[key] = copy.deepcopy(value)
        result[name] = out
    return result

def resolve(document, desktop, *, manager, os_id, hummingbird=False, eln=False,
            fedora=False, rawhide=False, cachyos=False, el10=False):
    validate(document)
    profiles = document['desktops']
    selected = desktop
    if os_id == 'debian' and desktop + '-debian' in profiles:
        selected += '-debian'
    elif manager == 'pacman' and desktop + '-arch' in profiles:
        selected += '-arch'
    if selected not in profiles:
        raise PolicyError(f'desktop {desktop}: no profile')
    profile = profiles[selected]
    if manager in {'apt', 'pacman', 'zypper', 'emerge'}:
        family = manager
    elif manager == 'dnf':
        if not (hummingbird or eln or fedora or el10):
            raise PolicyError('dnf: explicit supported base-family evidence required')
        if el10 and os_id not in {'almalinux', 'rocky', 'rhel', 'centos'}:
            raise PolicyError('el10: unsupported OS identity')
        family = 'hummingbird' if hummingbird else 'eln' if eln else 'fedora' if fedora else 'el10'
        if family == 'fedora' and rawhide and 'rawhide' in profile['packages']:
            family = 'rawhide'
    else:
        raise PolicyError(f'manager {manager}: unsupported')
    if family not in profile['packages']:
        raise PolicyError(f'{selected}: no {family} policy; unsupported target')
    sections = []
    if manager == 'pacman' and cachyos and 'cachyos' in profile['packages']:
        sections.append(('cachyos', expand(document['package_groups'], profile['packages']['cachyos'])))
    sections.append((family, expand(document['package_groups'], profile['packages'][family])))
    return {'profile': selected, 'family': family, 'sections': sections,
            'display_manager': sections[-1][1].get('display_manager', profile.get('display_manager')),
            'after_install': profile.get('after_install', []),
            'after_inline': profile.get('after_inline', []),
            'verification_supported': selected == 'gnome-debian' and family == 'apt'}


def desktop_outputs(document):
    """Complete deterministic host projections; no package manager is invoked."""
    profiles = legacy_profiles(document)
    outputs = {f'manifests/desktops/{name}.yaml': json.dumps(profile, ensure_ascii=False, indent=2) + '\n'
               for name, profile in profiles.items()}
    # The first supported installed-package contract deliberately has one native
    # family. Other profiles retain their exact compatibility projection.
    contract = resolve(document, 'gnome', manager='apt', os_id='debian')
    policy = contract['sections'][-1][1]
    receipt = {'schema_version': 1, 'profile': contract['profile'], 'family': 'apt',
               'required': policy['required'], 'display_manager': contract['display_manager'],
               'after_install': contract['after_install'], 'after_inline': contract['after_inline']}
    outputs['manifests/desktop-plans/gnome-debian.apt.json'] = json.dumps(receipt, indent=2) + '\n'
    return outputs


def validate_debian_contract_target(variant, desktop):
    """Use the existing build routing authority, never infer family from a name."""
    import subprocess
    resolver = Path(__file__).resolve().parents[1] / 'resolve-flavor.sh'
    try:
        result = subprocess.run(['bash', str(resolver), variant, desktop],
                                check=True, capture_output=True, text=True)
        routing = {key: json.loads(value) for key, value in
                   (line.split('=', 1) for line in result.stdout.splitlines())}
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise PolicyError('cannot resolve selected desktop build target') from exc
    if (desktop != 'gnome' or routing.get('CONTAINERFILE') != 'Containerfile.debian'
            or routing.get('DESKTOP_FLAVOR') != 'gnome'):
        raise PolicyError('installed contract: selected build target is not supported Debian GNOME')


def installation_contract(document, source_sha256, variant, desktop, platform, *, manager, os_id):
    """Bind the supported native policy to an exact source and matrix cell."""
    if not re.fullmatch(r'[0-9a-f]{64}', source_sha256):
        raise PolicyError('source_sha256: expected SHA-256 digest')
    variants = document.get('variants', {})
    if variant not in variants:
        raise PolicyError('variant: unknown matrix variant')
    validate_debian_contract_target(variant, desktop)
    entry = variants[variant]
    flavor = next((item for item in entry['flavors'] if item['id'] == desktop), None)
    if flavor is None or platform not in flavor.get('platforms', entry['platforms']):
        raise PolicyError('desktop/platform: not a declared matrix cell')
    policy_document = {key: document[key] for key in ('package_groups', 'desktops')}
    selected = resolve(policy_document, desktop, manager=manager, os_id=os_id)
    if not selected['verification_supported']:
        raise PolicyError('installed contract: unsupported native verification target')
    policy = selected['sections'][-1][1]
    return {'schema_version': 1, 'source_sha256': source_sha256,
            'variant': variant, 'desktop': desktop, 'platform': platform,
            'profile': selected['profile'], 'family': selected['family'],
            'required': policy['required'], 'display_manager': selected['display_manager'],
            'after_install': selected['after_install'], 'after_inline': selected['after_inline']}


def verify_installed_receipt(receipt, expected, query_installed):
    """A matching request receipt is necessary, but actual package state decides."""
    if receipt != expected:
        raise PolicyError('installed receipt is stale or does not match the selected source/cell')
    missing = [name for name in expected['required'] if not query_installed(name)]
    if missing:
        raise PolicyError('required packages are not installed: ' + ', '.join(missing))


def verify_debian_image_receipt(image, expected, run):
    """Read the installed receipt and query dpkg state, with no shell expansion."""
    prefix = ['podman', 'run', '--rm', '--entrypoint']
    receipt_result = run([*prefix, 'cat', image, '/usr/share/tunaos/desktop-package-contract.json'],
                         text=True, capture_output=True)
    if receipt_result.returncode:
        raise PolicyError('image has no readable installed desktop contract')
    try:
        receipt = json.loads(receipt_result.stdout)
    except (TypeError, ValueError) as exc:
        raise PolicyError('image desktop contract is not valid JSON') from exc

    def installed(name):
        result = run([*prefix, 'dpkg-query', image, '-W', '-f=${db:Status-Status}', name],
                     text=True, capture_output=True)
        return result.returncode == 0 and result.stdout.strip() == 'installed'

    verify_installed_receipt(receipt, expected, installed)
