#!/usr/bin/env python3
"""Emit/validate native QEMU evidence; never browser qualification or parity."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

SCHEMA = 'NativeISOQualification/v1'
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{40}')
TRANSITIONS = ['welcome', 'encryption', 'summary', 'progress', 'done']
INPUTS = ('source', 'overlay', 'installer', 'engine', 'media')
BASELINES = {'linux/amd64':'x86-64', 'linux/amd64/v2':'x86-64-v2', 'linux/arm64':'aarch64'}


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


def validate(evidence):
    require(evidence.get('schema') == SCHEMA, 'not native ISO qualification evidence')
    require('browser' not in evidence, 'native evidence must not claim a browser profile')
    require(evidence.get('execution_kind') == 'native-qemu', 'native execution kind required')
    for field in ('variant', 'flavor', 'platform', 'cpu_baseline', 'hardware_scope'):
        require(text(evidence.get(field)), f'missing {field}')
    require(evidence['platform'] in BASELINES and evidence['cpu_baseline'] == BASELINES[evidence['platform']], 'platform/CPU baseline mismatch')
    require(evidence['hardware_scope'] == 'qemu' and evidence['flavor'] == 'gnome', 'unsupported native GUI scope')
    require(evidence.get('offline_network_disabled') is True, 'guest egress must be disabled')
    inputs = evidence.get('resolved_inputs', {})
    require(isinstance(inputs, dict) and all(sha(inputs.get(k)) for k in INPUTS), 'missing immutable input digest')
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
    qemu = evidence.get('qemu', {})
    require(isinstance(qemu, dict) and sha(qemu.get('digest')) and text(qemu.get('version')) and text(qemu.get('cpu_model')), 'measured QEMU identity required')
    require(isinstance(evidence.get('observed'), dict), 'observations must be an object')
    for mode in ('plain', 'luks'):
        observed = evidence['observed'].get(mode, {})
        require(isinstance(observed, dict), f'{mode}: observations missing')
        require(observed.get('mode') == mode, f'{mode}: wrong mode')
        for field in ('installed_boot', 'desktop_contract', 'cold_boot', 'warm_boot', 'media_detached'):
            require(observed.get(field) is True, f'{mode}: {field} not proven')
        require(observed.get('passphrase_prompt') is (mode == 'luks'), f'{mode}: encryption prompt mismatch')
        require(observed.get('source_digest') == inputs['source'] == observed.get('booted_digest'), f'{mode}: installed source mismatch')
        require(text(observed.get('target_imgref')), f'{mode}: missing installed ref')
        for field in ('duration_s', 'install_duration_s', 'cold_boot_s', 'warm_boot_s'):
            require(number(observed.get(field), positive=True), f'{mode}: invalid {field}')
        gui = observed.get('gui', {})
        require(isinstance(gui, dict) and gui.get('mode') == mode, f'{mode}: GUI mode mismatch')
        require(gui.get('installer_digest') == inputs['installer'], f'{mode}: GUI installer mismatch')
        require(gui.get('transitions') == TRANSITIONS, f'{mode}: GUI transitions incomplete')
        for field in ('frontmost', 'submitted', 'accepted', 'completed'):
            require(gui.get(field) is True, f'{mode}: GUI {field} not proven')
        require(sha(gui.get('receipt_digest')), f'{mode}: GUI receipt digest missing')
    require(text(evidence.get('qualifiedAt')), 'qualification time missing')
    require(datetime.fromisoformat(evidence['qualifiedAt'].replace('Z','+00:00')).tzinfo is not None, 'qualification time must include timezone')
    require(evidence.get('receiptDigest') == canonical({k:v for k,v in evidence.items() if k != 'receiptDigest'}), 'native receipt digest mismatch')


def emit(args):
    binding = load(args.binding)
    harness = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=10).strip()
    require(binding.get('repository') == args.repository, 'binding repository differs from current job')
    require(binding.get('producer_run') == args.run_id and binding.get('producer_attempt') == args.attempt,
            'binding is not from this run and attempt')
    require(binding.get('harness_sha') == harness, 'binding harness differs from checked-out code')
    require(binding.get('media_digest') == args.media, 'binding differs from admitted ISO digest')
    require(binding.get('artifact_id') == args.artifact_id and binding.get('archive_digest') == args.archive_digest
            and binding.get('producer_sha') == args.source_sha, 'binding differs from successful build outputs')
    qemu = shutil.which(args.qemu)
    require(qemu is not None, 'invoked QEMU executable missing')
    observed = {}
    for mode in ('plain', 'luks'):
        frag = load(args.directory / f'strict-qual-{mode}.json')
        gui = load(args.directory / f'walkthrough-{mode}' / 'walkthrough-gnome.json')
        frag['gui'] = {key:gui.get(key) for key in ('mode', 'installer_digest', 'transitions',
                                                  'frontmost', 'submitted', 'accepted', 'completed')}
        frag['gui']['receipt_digest'] = canonical(gui)
        observed[mode] = frag
    result = {'schema': SCHEMA, 'execution_kind': 'native-qemu',
              'variant': args.variant, 'flavor': args.flavor, 'platform': args.platform,
              'cpu_baseline': BASELINES[args.platform], 'hardware_scope': 'qemu',
              'resolved_inputs': {key:getattr(args,key) for key in INPUTS},
              'artifact_binding': binding, 'artifact_binding_digest': canonical(binding),
              'qemu': {'digest': digest(qemu), 'cpu_model': args.cpu_model, 'version': subprocess.check_output([qemu,'--version'],text=True,timeout=10).splitlines()[0]},
              'offline_network_disabled': True, 'observed': observed,
              'qualifiedAt': datetime.now(timezone.utc).isoformat()}
    result['receiptDigest'] = canonical(result)
    validate(result)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('validate')
    check.add_argument('receipt', type=Path)
    create = sub.add_parser('emit')
    for key in ('binding', 'directory', 'output'):
        create.add_argument('--'+key, type=Path, required=True)
    for key in ('repository', 'qemu', 'variant', 'flavor', 'platform', 'cpu-model', 'archive-digest', 'source-sha', *INPUTS):
        create.add_argument('--'+key, required=True)
    for key in ('run-id', 'attempt', 'artifact-id'):
        create.add_argument('--'+key, type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'validate':
            validate(load(args.receipt))
        else:
            emit(args)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    print('ok - native ISO qualification evidence (not browser qualification)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
