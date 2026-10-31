#!/usr/bin/env python3
"""Emit/validate native QEMU evidence; never browser qualification or parity."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contracts.iso_qualification import DESKTOPS, NATIVE_OSTREE_VARIANTS, manifest, validate_session
from contracts.iso_qualification import cpu_baseline
from lib.xfce_candidate import TRANSITIONS as XFCE_TRANSITIONS, validate_frontend, COMMIT as XFCE_COMMIT

SCHEMA = 'NativeISOQualification/v2'
DESKTOP_SCHEMA = 'NativeISOQualificationCandidate/v3'
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
TRANSITIONS = ['welcome', 'encryption', 'summary', 'progress', 'done']
INPUTS = ('source', 'overlay', 'installer', 'engine', 'media')
NATIVE_PLATFORMS = frozenset({'linux/amd64', 'linux/amd64/v2', 'linux/arm64'})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            value.update(chunk)
    return 'sha256:' + value.hexdigest()


def canonical(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def load(path):
    path = Path(path)
    require(path.stat().st_size <= 1024*1024, 'receipt exceeds 1 MiB')
    value = json.loads(path.read_text())
    require(isinstance(value, dict), 'receipt must be an object')
    return value


def text(value):
    return isinstance(value, str) and bool(value.strip())


def sha(value, pattern=DIGEST):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def number(value, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and value >= (1 if positive else 0)


def validate_artifact_binding(evidence):
    inputs = evidence['resolved_inputs']
    binding = evidence.get('artifact_binding', {})
    require(isinstance(binding, dict), 'missing artifact binding')
    require(binding.get('repository') == 'tuna-os/tunaOS', 'unexpected producer repository')
    require(binding.get('producer_workflow') == '.github/workflows/live-iso-bootc.yml', 'unexpected producer workflow')
    require(binding.get('producer_build_conclusion') == 'success', 'successful producer build proof required')
    require((binding.get('producer_status') in ('queued', 'in_progress') and binding.get('producer_conclusion') is None)
            or (binding.get('producer_status') == 'completed' and binding.get('producer_conclusion') == 'success'),
            'invalid producer aggregate lifecycle')
    for field in ('producer_run', 'producer_attempt', 'producer_build_job', 'artifact_id', 'media_size'):
        require(type(binding.get(field)) is int and binding[field] > 0, f'invalid binding {field}')
    for field in ('producer_sha', 'harness_sha'):
        require(sha(binding.get(field), SHA), f'invalid binding {field}')
    require(binding['producer_sha'] == binding['harness_sha'], 'producer and trusted harness revisions differ')
    require(sha(binding.get('archive_digest')), 'archive digest required')
    require(binding.get('media_digest') == inputs['media'], 'artifact/media digest mismatch')
    require(binding.get('status') == 'download_verified_not_boot_tested', 'unexpected admission receipt kind')
    require(evidence.get('artifact_binding_digest') == canonical(binding), 'artifact binding digest mismatch')

def validate(evidence):
    extended = evidence.get('schema') == DESKTOP_SCHEMA
    require(evidence.get('schema') in (SCHEMA, DESKTOP_SCHEMA), 'not native ISO qualification evidence')
    require(evidence.get('boot_policy') == 'unmodified-installed', 'unknown or modified installed boot policy')
    require('browser' not in evidence, 'native evidence must not claim a browser profile')
    require(evidence.get('execution_kind') == 'native-qemu', 'native execution kind required')
    for field in ('variant', 'flavor', 'platform', 'cpu_baseline', 'hardware_scope'):
        require(text(evidence.get(field)), f'missing {field}')
    if extended:
        validate_desktop_identity(evidence)
    else:
        require(evidence['variant'] in NATIVE_OSTREE_VARIANTS, 'native target is not admitted')
        require(
            evidence['platform'] in NATIVE_PLATFORMS
            and evidence['cpu_baseline'] == cpu_baseline(evidence['variant'], evidence['platform']),
            'platform/CPU baseline mismatch',
        )
        require(evidence['hardware_scope'] == 'qemu' and evidence['flavor'] == 'gnome', 'unsupported native GUI scope')
    require(evidence.get('storage_backend', 'ostree') == 'ostree', 'native-composefs requires separate proof')
    require(evidence.get('offline_network_disabled') is True, 'guest egress must be disabled')
    inputs = evidence.get('resolved_inputs', {})
    require(isinstance(inputs, dict) and all(sha(inputs.get(k)) for k in INPUTS), 'missing immutable input digest')
    validate_artifact_binding(evidence)
    qemu = evidence.get('qemu', {})
    require(isinstance(qemu, dict) and sha(qemu.get('digest')) and text(qemu.get('version')) and text(qemu.get('cpu_model')), 'measured QEMU identity required')
    require(isinstance(evidence.get('observed'), dict), 'observations must be an object')
    for mode in ('plain', 'luks'):
        observed = evidence['observed'].get(mode, {})
        require(isinstance(observed, dict), f'{mode}: observations missing')
        require(observed.get('mode') == mode, f'{mode}: wrong mode')
        for field in ('installed_boot', 'desktop_contract', 'cold_boot', 'warm_boot', 'media_detached'):
            require(observed.get(field) is True, f'{mode}: {field} not proven')
        require(observed.get('boot_arguments_unmodified') is True, f'{mode}: unchanged installed boot arguments not proven')
        require(observed.get('passphrase_prompt') is (mode == 'luks'), f'{mode}: encryption prompt mismatch')
        require(observed.get('source_digest') == inputs['source'] == observed.get('booted_digest'), f'{mode}: installed source mismatch')
        require(text(observed.get('target_imgref')), f'{mode}: missing installed ref')
        for field in ('duration_s', 'install_duration_s', 'cold_boot_s', 'warm_boot_s'):
            require(number(observed.get(field), positive=True), f'{mode}: invalid {field}')
        gui = observed.get('gui', {})
        require(isinstance(gui, dict) and gui.get('mode') == mode, f'{mode}: GUI mode mismatch')
        require(gui.get('installer_digest') == inputs['installer'], f'{mode}: GUI installer mismatch')
        require(gui.get('transitions') == (XFCE_TRANSITIONS if extended and evidence['flavor']=='xfce' else TRANSITIONS), f'{mode}: GUI transitions incomplete')
        for field in ('frontmost', 'submitted', 'accepted', 'completed'):
            require(gui.get(field) is True, f'{mode}: GUI {field} not proven')
        require(sha(gui.get('receipt_digest')), f'{mode}: GUI receipt digest missing')
    require(text(evidence.get('qualifiedAt')), 'qualification time missing')
    require(datetime.fromisoformat(evidence['qualifiedAt'].replace('Z','+00:00')).tzinfo is not None, 'qualification time must include timezone')
    require(evidence.get('receiptDigest') == canonical({k:v for k,v in evidence.items() if k != 'receiptDigest'}), 'native receipt digest mismatch')



def validate_desktop_identity(evidence):
    """v3 is a validation contract; producer admission still requires a driver.

    Never upgrade v2 by relabeling it. v3 requires independent cold/warm
    logged-in session observations and full target/source/frontend identity.
    """
    doc = manifest()
    require(evidence.get('manifest_digest') == doc['manifestDigest'], 'target manifest mismatch')
    matches = [row for row in doc['targets'] if all(row['target'][key] == evidence.get(key)
               for key in ('variant', 'flavor', 'platform'))]
    require(len(matches) == 1, 'target not configured')
    row = matches[0]
    require(row['image_supported'] and row['configured'], 'target policy conflict or unscheduled')
    require(not [gap for gap in row['gaps'] if gap != 'production qualification driver not admitted for this frontend'],
            'target has unresolved support or hardware gaps')
    require(evidence.get('cpu_baseline') == row['target']['cpuBaseline'], 'platform/CPU baseline mismatch')
    require(row['backend'] == 'ostree', 'native producer backend not admitted')
    require(evidence.get('storage_backend') == 'ostree', 'backend is not OSTree; native-composefs requires separate proof')
    require(evidence.get('hardware_scope') == 'qemu', 'unsupported hardware scope')
    require('nvidia' not in evidence['flavor'].split('-'), 'physical GPU evidence required')
    require(evidence['platform'] != 'linux/arm64', 'architecture producer not implemented')
    desktop = row['desktop']
    require(desktop in ('gnome', 'kde', 'xfce'), 'desktop qualification contract not implemented')
    inputs = evidence.get('resolved_inputs', {})
    binding = evidence.get('consumer_target', {})
    for field in ('variant', 'flavor', 'platform'):
        require(binding.get(field) == evidence[field], 'consumer target identity mismatch')
    require(binding.get('source_digest') == inputs.get('source') and sha(binding.get('source_digest')), 'consumer source mismatch')
    require(binding.get('storage_backend') == 'ostree', 'consumer backend mismatch')
    all_boot_ids = []
    host_backends = []
    for mode in ('plain', 'luks'):
        observed = evidence.get('observed', {}).get(mode, {})
        expected_ref = row['publication']['repository'] + ':' + row['publication']['tag']
        require(observed.get('target_imgref') == expected_ref, 'installed publication/full flavor mismatch')
        require(observed.get('fresh_install') is True, 'fresh install not proven')
        require(observed.get('storage_backend') == 'ostree', 'installed backend mismatch')
        require(observed.get('flavor') == evidence['flavor'], 'installed full flavor mismatch')
        require(observed.get('platform') == evidence['platform'], 'installed platform mismatch')
        sessions = observed.get('sessions', {})
        boot_ids = []
        for phase in ('cold', 'warm'):
            session = sessions.get(phase)
            validate_session(session, desktop, evidence['platform'])
            require(isinstance(session.get('boot_id'), str) and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', session['boot_id']), 'session boot identity missing')
            require(session.get('source_digest') == inputs['source'], 'session booted source mismatch')
            require(session.get('phase') == phase and session.get('mode') == mode, 'session phase/mode mismatch')
            boot_ids.append(session['boot_id'])
        require(len(set(boot_ids)) == 2, 'cold/warm session observations must be distinct boots')
        all_boot_ids.extend(boot_ids)
        gui = observed.get('gui', {})
        require(gui.get('desktop') == desktop and gui.get('frontend') == DESKTOPS[desktop][0], 'installer desktop/frontend mismatch')
        require(gui.get('mode') == mode, 'GUI mode mismatch')
        if desktop == 'xfce':
            validate_frontend(observed.get('frontend_identity'))
            media=observed['frontend_identity'].get('media_input',{})
            require(media.get('schemaVersion')==1 and media.get('platform')==evidence['platform']
                    and media.get('image')==expected_ref and media.get('targetImgref')==expected_ref
                    and media.get('platformManifestDigest')==inputs['source']
                    and media.get('ociLayoutPath')=='/usr/lib/tunaos/xfce-candidate-oci', 'XFCE media input/source mismatch')
            host_backends.append(observed['frontend_identity']['host_fisherman_digest'])
            require(sessions['cold']['uid']==sessions['warm']['uid'], 'installed account UID changed between boots')
            require(inputs['installer'] == 'sha256:'+XFCE_COMMIT, 'XFCE installer digest mismatch')
            require(gui.get('source_selection') == 'live-self-install', 'XFCE live self-install not proven')
            require(sha(gui.get('account_digest')), 'GUI-created account identity missing')
            for session in sessions.values():
                require(session.get('account_digest') == gui['account_digest'], 'GUI-created account/session mismatch')
                require(session.get('storage_backend') == 'ostree', 'session backend mismatch')
    if desktop=='xfce':
        require(len(set(host_backends))==1, 'host backend changed between install modes')
    require(len(set(all_boot_ids)) == 4, 'plain/LUKS session observations must be four distinct boots')


def emit(args):
    require(not os.environ.get('TUNAOS_LUKS_GRUB_APPEND', '')
            and not os.environ.get('STRICT_LUKS_GRUB_APPEND', ''),
            'diagnostic GRUB overrides cannot emit native qualification')
    candidate = getattr(args, 'command', '') == 'emit-candidate'
    if candidate:
        require((args.variant,args.flavor,args.platform)==('bonito','xfce','linux/amd64'), 'candidate target outside bounded XFCE scope')
    binding = load(args.binding)
    harness = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=10).strip()
    require(type(args.run_id) is int and args.run_id > 0 and type(args.attempt) is int and args.attempt > 0,
            'validated producer run and attempt are required')
    require(binding.get('repository') == args.repository, 'binding repository differs from current job')
    require(binding.get('producer_run') == args.run_id and binding.get('producer_attempt') == args.attempt,
            'binding does not match the validated producer run and attempt')
    require(binding.get('harness_sha') == harness, 'binding harness differs from checked-out code')
    require(binding.get('media_digest') == args.media, 'binding differs from admitted ISO digest')
    require(binding.get('artifact_id') == args.artifact_id and binding.get('archive_digest') == args.archive_digest
            and binding.get('producer_sha') == args.source_sha, 'binding differs from successful build outputs')
    qemu = shutil.which(args.qemu)
    require(qemu is not None, 'invoked QEMU executable missing')
    observed = {}
    for mode in ('plain', 'luks'):
        frag = load(args.directory / f'strict-qual-{mode}.json')
        gui = load(args.directory / f'walkthrough-{mode}' / ('walkthrough-xfce.json' if candidate else 'walkthrough-gnome.json'))
        frag['gui'] = {key:gui.get(key) for key in ('mode', 'installer_digest', 'transitions',
                                                  'frontmost', 'submitted', 'accepted', 'completed')}
        frag['gui']['receipt_digest'] = canonical(gui)
        if candidate:
            frag['gui'].update({key:gui.get(key) for key in ('desktop','frontend','account_digest','source_selection')})
            frag.update(fresh_install=True, storage_backend='ostree', flavor=args.flavor, platform=args.platform,
                frontend_identity=load(args.directory / f'frontend-{mode}.json'),
                sessions={phase:load(args.directory/f'session-{mode}-{phase}.json') for phase in ('cold','warm')})
        observed[mode] = frag
    result = {'schema': SCHEMA, 'execution_kind': 'native-qemu',
              'boot_policy': 'unmodified-installed',
              'variant': args.variant, 'flavor': args.flavor, 'platform': args.platform,
              'cpu_baseline': cpu_baseline(args.variant, args.platform), 'hardware_scope': 'qemu',
              'storage_backend': 'ostree',
              'resolved_inputs': {key:getattr(args,key) for key in INPUTS},
              'artifact_binding': binding, 'artifact_binding_digest': canonical(binding),
              'qemu': {'digest': digest(qemu), 'cpu_model': args.cpu_model, 'version': subprocess.check_output([qemu,'--version'],text=True,timeout=10).splitlines()[0]},
              'offline_network_disabled': True, 'observed': observed,
              'qualifiedAt': datetime.now(timezone.utc).isoformat()}
    if candidate:
        result.update(schema=DESKTOP_SCHEMA, manifest_digest=manifest()['manifestDigest'])
        result['consumer_target']=dict(variant=args.variant,flavor=args.flavor,platform=args.platform,source_digest=args.source,storage_backend='ostree')
    result['receiptDigest'] = canonical(result)
    validate(result)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('validate')
    check.add_argument('receipt', type=Path)
    candidate = sub.add_parser('validate-candidate')
    candidate.add_argument('receipt', type=Path)
    create = sub.add_parser('emit')
    for key in ('binding', 'directory', 'output'):
        create.add_argument('--'+key, type=Path, required=True)
    for key in ('repository', 'qemu', 'variant', 'flavor', 'platform', 'cpu-model', 'archive-digest', 'source-sha', *INPUTS):
        create.add_argument('--'+key, required=True)
    for key in ('run-id', 'attempt', 'artifact-id'):
        create.add_argument('--'+key, type=int, required=True)
    sub.add_parser('emit-candidate', parents=[create], add_help=False)
    args = parser.parse_args()
    try:
        if args.command in ('validate', 'validate-candidate'):
            receipt = load(args.receipt)
            expected = DESKTOP_SCHEMA if args.command == 'validate-candidate' else SCHEMA
            require(receipt.get('schema') == expected, 'candidate evidence is not admitted native qualification')
            validate(receipt)
        else:
            emit(args)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    if args.command in ('validate-candidate', 'emit-candidate'):
        print('ok - candidate contract only; not admitted native qualification')
    else:
        print('ok - native ISO qualification evidence (not browser qualification)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
