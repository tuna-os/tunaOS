"""Candidate declarative consumer resolver; observation closes explicit gaps.

API base_resolution: {reference,indexDigest,childDigest,platform,cpuBaseline}.
The caller resolves OCI descriptors and must use that exact child in the build.
This pure module never contacts package repositories or invents providers.
"""
from __future__ import annotations
import hashlib
import json
import pathlib
import re
from typing import Any
import yaml

ADAPTERS = {
    'yellowfin': ('dnf', 'el10', 'almalinux-kitten-10'),
    'albacore': ('dnf', 'el10', 'almalinux-10'),
    'skipjack': ('dnf', 'el10', 'centos-stream-10'),
    'bonito': ('dnf', 'fedora', 'fedora-44'),
    'bonito-rawhide': ('dnf', 'fedora', 'fedora-rawhide'),
    'wahoo': ('dnf', 'eln', 'eln'),
    'hummingbird': ('dnf', 'hummingbird', 'hummingbird'),
    'sailfin': ('zypper', 'zypper', 'opensuse-tumbleweed'),
    'guppy': ('portage', 'emerge', 'gentoo'),
    'gurnard': ('apt', 'apt', 'ubuntu-noble'),
    'grouper': ('apt', 'apt', 'ubuntu-resolute'),
    'marlin': ('pacman', 'pacman', 'arch'),
    'flounder': ('apt', 'apt', 'debian-trixie'),
    'flounder-sid': ('apt', 'apt', 'debian-sid'),
}
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
REVISION = re.compile(r'[0-9a-f]{40}\Z')


from .evidence import canonical_json as canonical, contract_digest, EvidenceError, validate
from .targets import validate_target, resolve_required_targets, target_key
from .base import validate_base
from .sources import classify_policy


def digest(value: Any) -> str:
    return 'sha256:' + hashlib.sha256(canonical(value)).hexdigest()


def _list(value: Any, label: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f'{label} must be a list')
    return value


def _strings(value: Any, label: str) -> list[str]:
    result = _list(value, label)
    if not all(isinstance(x, str) and x.strip() for x in result):
        raise ValueError(f'{label} requires nonempty strings')
    return result


def _condition(value: Any, family: str) -> bool:
    if value in (None, ''):
        return True
    if not isinstance(value, str) or value not in {'ubuntu', 'debian'}:
        raise ValueError(f'unsupported repository condition: {value!r}')
    return family.startswith(value)


def resolve_consumer(target: dict, config: dict, base_resolution: dict, source_revision: str,
                     root: str | pathlib.Path, policy_baseline: object | None = None,
                     policy_revision: str | None = None) -> dict:
    validate_target(target)
    if not REVISION.fullmatch(source_revision):
        raise ValueError('sourceRevision must be a full lowercase commit')
    root = pathlib.Path(root)
    manager, section_name, family = ADAPTERS[target['variant']]
    variants = [v for v in config['variants'] if v['id'] == target['variant']]
    if len(variants) != 1:
        raise ValueError('variant must occur exactly once in build config')
    flavors = [f for f in variants[0]['flavors'] if f['id'] == target['flavor']]
    if len(flavors) != 1 or flavors[0].get('build_image') is not True:
        raise ValueError('requested consumer flavor is not enabled')
    base_resolution = validate_base(base_resolution, target, variants[0]['base_image'])
    desktop = target['flavor'].split('-')[0]
    relative = pathlib.Path('manifests/desktops') / f'{desktop}.yaml'
    override = '-debian' if family.startswith('debian') else '-arch' if manager == 'pacman' else ''
    if override and (root / relative.with_name(f'{desktop}{override}.yaml')).is_file():
        relative = relative.with_name(f'{desktop}{override}.yaml')
    if policy_revision is not None and not REVISION.fullmatch(policy_revision):
        raise EvidenceError('policy revision must be an immutable full lowercase SHA')
    manifest: dict = {}
    requirements: list[dict] = []
    sources: list[dict] = []
    groups: list[dict] = []
    unresolved: list[dict] = []
    hooks: list[dict] = []
    inputs = [{'path': '.github/build-config.yml', 'digest': digest(config)}]
    exclusions: list[str] = []
    locks: list[str] = []

    def gap(code: str, path: str, detail: str) -> None:
        unresolved.append({'code': code, 'origin': path, 'detail': detail})

    def request(expression: str, path: str, required: bool = True, source: str | None = None) -> None:
        # Expressions stay native. No RPM/Debian/Portage comparison is attempted.
        record = {'nativeExpression': expression, 'manager': manager, 'scope': 'final',
                  'required': required, 'origins': [{'path': path, 'phase': 'desktop'}]}
        if source is not None:
            record['requestedSource'] = source  # intent only, never a resolved provider
        requirements.append(record)

    def consume(section: Any, label: str) -> None:
        nonlocal exclusions
        if isinstance(section, list):
            for expression in _strings(section, label):
                request(expression, label)
            return
        if not isinstance(section, dict):
            raise ValueError(f'{label}: expected package list or mapping')
        known = {'packages', 'repos', 'ppa', 'copr', 'groups', 'group_options', 'group_exclude',
                 'exclude', 'optional', 'optional_group', 'pre_install', 'display_manager', 'versionlock'}
        for field in sorted(set(section) - known):
            gap('unsupported-manifest-field', label, field)
        for expression in _strings(section.get('packages'), label + '.packages'):
            request(expression, label + '.packages')
        for expression in _strings(section.get('optional'), label + '.optional'):
            request(expression, label + '.optional', False)
        optional_group = _strings(section.get('optional_group'), label + '.optional_group')
        for expression in optional_group:
            request(expression, label + '.optional_group', False)
        if optional_group:
            gap('optional-group-native-condition-required', label + '.optional_group', optional_group[0])
        exclusions.extend(_strings(section.get('exclude'), label + '.exclude'))
        for group in _strings(section.get('groups'), label + '.groups'):
            groups.append({'nativeId': group, 'options': section.get('group_options', ''),
                           'excludes': _strings(section.get('group_exclude'), label + '.group_exclude'),
                           'origins': [{'path': label + '.groups', 'phase': 'desktop'}]})
            gap('native-group-expansion-required', label, group)
        for field in ('repos', 'ppa', 'copr'):
            for index, entry in enumerate(_list(section.get(field), label + '.' + field)):
                if not isinstance(entry, dict):
                    raise ValueError(f'{field} entry must be a mapping')
                if not _condition(entry.get('condition'), family):
                    continue
                origin = f'{label}.{field}[{index}]'
                sources.append({'declarationType': field, 'declaration': entry, 'origin': origin})
                gap('source-snapshot-and-signature-unresolved', origin, 'observe enabled repository identity and content')
                if field == 'copr':
                    for expression in _strings(entry.get('packages'), origin + '.packages'):
                        request(expression, origin, True, entry.get('repo'))
        for index, command in enumerate(_strings(section.get('pre_install'), label + '.pre_install')):
            hooks.append({'commandDigest': digest(command), 'origin': f'{label}.pre_install[{index}]'})
            gap('shell-hook-observation-required', label, 'pre_install')
        locks.extend(_strings(section.get('versionlock'), label + '.versionlock'))

    if desktop in {'base', 'base-no-de'}:
        gap('base-demand-observation-required', 'build_scripts/10-base-packages.sh', 'base flavor has no desktop manifest')
    elif not (root / relative).is_file():
        gap('missing-effective-manifest', str(relative), desktop)
    else:
        raw = (root / relative).read_bytes()
        manifest = yaml.safe_load(raw)
        inputs.append({'path': str(relative), 'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()})
        if not isinstance(manifest, dict) or not isinstance(manifest.get('packages'), dict):
            raise ValueError('desktop manifest requires packages mapping')
        known_fields = {'packages', 'display_manager', 'versionlock', 'post_install',
                        'post_install_commands', 'post_install_inline', 'disable_desktop_files', 'minimum_version'}
        for field in sorted(set(manifest) - known_fields):
            gap('unsupported-manifest-field', str(relative), str(field))
        if 'minimum_version' in manifest:
            gap('native-desktop-version-floor-required', str(relative) + ':minimum_version',
                str(manifest['minimum_version']))
        section = manifest['packages'].get(section_name)
        if section is None:
            gap('missing-manager-section', str(relative), section_name)
        else:
            consume(section, f'{relative}:packages.{section_name}')
        if manager == 'pacman' and 'cachyos' in target['flavor'].split('-'):
            extra = manifest['packages'].get('cachyos')
            if extra is None:
                gap('missing-cachyos-section', str(relative), 'cachyos')
            else:
                consume(extra, f'{relative}:packages.cachyos')
        locks.extend(_strings(manifest.get('versionlock'), str(relative) + ':versionlock'))
        for index, command in enumerate(_strings(manifest.get('post_install_inline'), str(relative) + ':post_install_inline')):
            origin = f'{relative}:post_install_inline[{index}]'
            hooks.append({'commandDigest': digest(command), 'origin': origin})
            gap('shell-hook-observation-required', origin, 'post_install_inline')
        for hook_field in ('post_install', 'post_install_commands'):
            for command in _strings(manifest.get(hook_field), str(relative) + ':' + hook_field):
                hook_path = pathlib.Path('build_scripts') / command
                if hook_path.is_absolute() or '..' in hook_path.parts:
                    raise EvidenceError('hook path escapes build scripts')
                hook_file = root / hook_path
                if hook_file.is_symlink() or not hook_file.resolve().is_relative_to((root / 'build_scripts').resolve()):
                    raise EvidenceError('hook script escapes build scripts or is a symlink')
                if not hook_file.is_file():
                    gap('missing-hook-script', str(hook_path), hook_field)
                else:
                    hooks.append({'script': str(hook_path), 'scriptDigest': 'sha256:' + hashlib.sha256(hook_file.read_bytes()).hexdigest(), 'origin': str(relative) + ':' + hook_field})
                gap('shell-hook-observation-required', str(relative), hook_field)

    policy = classify_policy(manifest, policy_baseline)
    for violation in policy['forbiddenNew']:
        gap('forbidden-new-package-source', str(relative), violation)
    if policy_revision is None:
        gap('missing-policy-revision', str(relative), 'trusted immutable policy revision is required')
    source_policy = {**policy, 'policyRevision': policy_revision,
                     'baselineDigest': digest(policy_baseline) if policy_baseline is not None else None}

    for relative_script in ['build_scripts/10-base-packages.sh', 'build_scripts/20-packages.sh',
                            'build_scripts/26-packages-post.sh']:
        path = root / relative_script
        if path.is_file():
            inputs.append({'path': relative_script, 'digest': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()})
        gap('base-demand-observation-required', relative_script, 'direct/native transactions need ledger')
    overlay_tokens = {'asahi', 't2', 'hwe', 'nvidia', 'cachyos'} & set(target['flavor'].split('-'))
    for overlay in sorted(overlay_tokens):
        relative_script = f'build_scripts/overlay/{overlay}.sh'
        path = root / relative_script
        if path.is_file():
            inputs.append({'path': relative_script, 'digest': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()})
        gap('overlay-demand-observation-required', relative_script, overlay)
    gap('inherited-base-inventory-required', base_resolution['reference'], 'require measured native base inventory')
    gap('native-closure-and-provider-resolution-required', str(relative), family)
    materials = sorted(set((root / 'build_scripts').rglob('*')) | set(root.glob('Containerfile*')) | set((root / 'scripts/contracts').glob('*.py')))
    for material in materials:
        if '__pycache__' in material.parts or material.suffix in {'.pyc', '.pyo'}:
            continue
        if material.is_symlink():
            raise EvidenceError('build material symlink requires explicit resolution')
        if material.is_file():
            inputs.append({'path': str(material.relative_to(root)), 'digest': 'sha256:' + hashlib.sha256(material.read_bytes()).hexdigest()})
    inputs = list({item['path']: item for item in inputs}.values())

    # Merge exact expressions without losing requiredness, source intent or origins.
    merged: dict[tuple, dict] = {}
    for item in requirements:
        key = (item['nativeExpression'], item['scope'], item.get('requestedSource'))
        if key not in merged:
            merged[key] = item
        else:
            merged[key]['required'] |= item['required']
            for origin in item['origins']:
                if origin not in merged[key]['origins']:
                    merged[key]['origins'].append(origin)
    blocked = any(g['code'].startswith(('missing-', 'unsupported-', 'forbidden-')) for g in unresolved)
    document = {'schemaVersion': 1, 'kind': 'consumer-contract', 'target': target,
                'sourceRevision': source_revision, 'baseReference': base_resolution['reference'],
                'baseDigest': base_resolution['childDigest'], 'baseResolution': base_resolution,
                'packageManager': manager, 'adapter': family,
                'packageRequirements': sorted(merged.values(), key=lambda x: canonical(x)),
                'sourceDeclarations': sources, 'sourcePolicy': source_policy, 'approvedSources': [], 'nativeGroups': groups,
                'nativeExcludes': sorted(set(exclusions)), 'nativeVersionLocks': sorted(set(locks)),
                'hooks': hooks, 'inputs': sorted(inputs, key=lambda x: x['path']),
                'requiredChecks': ['demand-coverage', 'native-install', 'package-signatures', 'cpu-baseline'],
                'resolution': {'status': 'blocked' if blocked else 'incomplete', 'unresolved': unresolved}}
    document['contractDigest'] = contract_digest(document)
    validate(document, 'consumer-contract')
    return document


def resolve_all(config: dict, base_records: dict, source_revision: str, root: str | pathlib.Path,
                policy_baselines: dict | None = None, policy_revision: str | None = None) -> dict:
    rows = []
    for required in resolve_required_targets(config):
        target = required['target']
        key = target_key(target)
        if key not in base_records:
            rows.append({**required, 'status': 'blocked', 'contract': None,
                         'reasons': [{'code': 'missing-base-record', 'detail': key}]})
            continue
        try:
            desktop = target['flavor'].split('-')[0]
            path = pathlib.Path('manifests/desktops') / f'{desktop}.yaml'
            manager, _, family = ADAPTERS[target['variant']]
            suffix = '-debian' if family.startswith('debian') else '-arch' if manager == 'pacman' else ''
            if suffix and (pathlib.Path(root) / path.with_name(f'{desktop}{suffix}.yaml')).is_file():
                path = path.with_name(f'{desktop}{suffix}.yaml')
            baseline = (policy_baselines or {}).get(str(path))
            contract = resolve_consumer(target, config, base_records[key], source_revision, root, baseline, policy_revision)
            rows.append({**required, 'status': contract['resolution']['status'], 'contract': contract,
                         'reasons': contract['resolution']['unresolved']})
        except (ValueError, KeyError, OSError, yaml.YAMLError) as exc:
            rows.append({**required, 'status': 'blocked', 'contract': None,
                         'reasons': [{'code': 'consumer-resolution-error', 'detail': str(exc)}]})
    return {'schemaVersion': 1, 'kind': 'consumer-preparation', 'sourceRevision': source_revision,
            'coverageDigest': digest(resolve_required_targets(config)), 'targets': rows}


def main() -> None:
    import argparse
    import subprocess
    from .evidence import loads
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='.github/build-config.yml')
    parser.add_argument('--base-records', required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--policy-revision', required=True, help='trusted immutable authored-source policy SHA')
    parser.add_argument('--root', default='.')
    parser.add_argument('--target', help='canonical variant:flavor:platform; otherwise all required')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = pathlib.Path(args.root)
    actual_revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if actual_revision != args.source_revision:
        raise EvidenceError('requested source revision differs from actual checkout')
    material_paths = ['.github/build-config.yml', 'manifests', 'build_scripts', 'Containerfile*', 'scripts/contracts']
    dirty = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=all', '--', *material_paths], text=True).splitlines()
    dirty = [line for line in dirty if '__pycache__/' not in line and not line.endswith(('.pyc', '.pyo'))]
    if dirty:
        raise EvidenceError('consumer source materials must be committed and clean before CLI export')
    config = yaml.safe_load((root / args.config).read_text())
    records = loads(pathlib.Path(args.base_records).read_text())
    if not REVISION.fullmatch(args.policy_revision):
        raise EvidenceError('policy revision must be a full lowercase SHA')
    baselines = {}
    for path in sorted((root / 'manifests/desktops').glob('*.yaml')):
        relative = str(path.relative_to(root))
        try:
            body = subprocess.check_output(['git', '-C', str(root), 'show', args.policy_revision + ':' + relative], text=True, stderr=subprocess.DEVNULL)
            baselines[relative] = yaml.safe_load(body)
        except (subprocess.CalledProcessError, yaml.YAMLError):
            baselines[relative] = None
    document = resolve_all(config, records, args.source_revision, root, baselines, args.policy_revision)
    if args.target:
        matches = [row for row in document['targets'] if target_key(row['target']) == args.target]
        if len(matches) != 1:
            raise EvidenceError('target is not in required coverage')
        document['targets'] = matches
    pathlib.Path(args.output).write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
