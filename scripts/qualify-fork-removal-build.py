#!/usr/bin/env python3
"""Build and check actual optional-removal intent; local images only, no boot claim."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


PREPARE = module("prepare_removal_build", ROOT / "scripts/prepare-fork-config.py")
OPTIONAL = module("optional_removal_proof", ROOT / "scripts/qualify-fork-optional-removal.py")

VERIFY = r'''
import importlib.util, json
from pathlib import Path
context = Path('/run/context')
spec = importlib.util.spec_from_file_location('optional', context / 'build_scripts/lib/fork-optional-removals.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
manifest = context / 'manifests/fork-config.json'
value, identity = helper.validate(manifest)
name = '--'.join(value[k].replace('/', '-') for k in ('variant', 'flavor', 'platform'))
receipt = Path('/usr/share/tunaos/fork-config/packages') / (name + '.json')
overall, _ = helper.read_json(receipt)
if (overall.get('status') != 'complete' or overall.get('remove') != ['fastfetch']
        or overall.get('manifest_sha256') != identity['manifest_sha256']):
    raise ValueError('actual build did not complete the exact removal intent')
result = helper.verify_complete(manifest, Path(str(receipt) + '.baseline.json'),
                                Path(str(receipt) + '.removal.json'), context, Path('/'), 'gnome')
print(json.dumps({'overall_receipt': overall, 'native_removal_receipt': result}, sort_keys=True))
'''


def inspect(image):
    values = json.loads(subprocess.check_output(['podman', 'image', 'inspect', image], text=True),
                        object_pairs_hook=OPTIONAL.unique_pairs)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError('image must resolve to exactly one local ID')
    image_id = values[0].get('Id', '')
    if isinstance(image_id, str) and re.fullmatch(r'[0-9a-f]{64}', image_id):
        image_id = 'sha256:' + image_id
    if not isinstance(image_id, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise ValueError('image lacks an immutable local ID')
    return image_id


def build(variant, remove, output, source, root):
    output.mkdir()
    namespace = 'fork-removal-build-target' if remove else 'fork-removal-build-stock'
    config = {'schema_version': 1, 'catalog': {'sha256': source},
              'image': {'registry': 'localhost', 'namespace': namespace},
              'targets': {'variants': [variant], 'flavors': ['gnome'], 'platforms': ['linux/amd64']},
              'global': {'packages': {'remove': ['fastfetch'] if remove else []}}}
    config_path = output / 'fork.yaml'
    config_path.write_text(yaml.safe_dump(config))
    builds = PREPARE.prepare(config_path, output / 'prepared', root)
    if len(builds) != 1 or not builds[0]['base_digest_pinned']:
        raise ValueError('actual removal proof needs one digest-pinned build')
    entry = builds[0]
    context = output / 'prepared' / entry['context']
    manifest = json.loads((context / 'manifests/fork-config.json').read_text())
    if manifest['sources'] != {'sha256': source}:
        raise ValueError('prepared build differs from the intended source pin')
    if (context / 'manifests/fork-identity.json').exists():
        raise ValueError('package proof must not carry paired identity authority')
    env = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'], 'LANG': 'C.UTF-8', **entry['environment']}
    if (env['IMAGE_TAG'] != f'localhost/{namespace}/{variant}:gnome-linux-amd64'
            or env['USE_CACHE'] != '0' or env['IS_CI'] != '0' or env['SKIP_RECHUNK'] != '1'):
        raise ValueError('build environment differs from the nonpublishing proof')
    # Keep the existing no-cache boundary. Cache relaxation needs its own proof.
    with (output / 'build.log').open('w') as log:
        subprocess.run(['bash', 'scripts/build-image-inner.sh'], cwd=context, env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    return context, inspect(env['IMAGE_TAG']), env['BASE_IMAGE']


def verify_built(context, image_id, output):
    name = 'tuna-removal-build-' + uuid.uuid4().hex
    label = 'org.tunaos.removal-build-proof'
    command = ['podman', 'run', '--pull=never', '--name', name, '--label', f'{label}={name}',
               '--network=none', '--entrypoint', 'python3', '--volume', f'{context.resolve()}:/run/context:ro',
               image_id, '-c', VERIFY]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=1200)
        (output / 'verify.stdout.log').write_text(result.stdout[-1024 * 1024:])
        (output / 'verify.stderr.log').write_text(result.stderr[-1024 * 1024:])
        result.check_returncode()
        evidence = json.loads(result.stdout, object_pairs_hook=OPTIONAL.unique_pairs)
        if set(evidence) != {'overall_receipt', 'native_removal_receipt'}:
            raise ValueError('incomplete final-image removal evidence')
        (output / 'native-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    finally:
        exists = subprocess.run(['podman', 'container', 'exists', name], capture_output=True, timeout=30)
        if exists.returncode == 0:
            values = json.loads(subprocess.check_output(['podman', 'container', 'inspect', name], text=True, timeout=30))
            if (not isinstance(values, list) or len(values) != 1
                    or values[0].get('Config', {}).get('Labels', {}).get(label) != name):
                raise ValueError('refuse cleanup: disposable child identity differs')
            subprocess.run(['podman', 'rm', '--force', name], check=True, capture_output=True, timeout=60)
        elif exists.returncode != 1:
            raise ValueError('cannot determine disposable child status')
        if subprocess.run(['podman', 'container', 'exists', name], capture_output=True, timeout=30).returncode != 1:
            raise ValueError('cannot verify disposable child cleanup')
    return evidence


def qualify(variant, output, root=ROOT):
    if variant not in {'grouper', 'yellowfin'}:
        raise ValueError('unsupported optional-removal variant')
    if output.exists() or any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError('output must be new and have no symlink ancestors')
    output.mkdir(parents=True)
    report = {'schema_version': 1, 'variant': variant, 'scope': 'actual-package-removal-build',
              'status': 'running', 'publishing': False, 'boot': 'not-run', 'identity': 'not-run',
              'installer': 'not-run', 'stock_build': 'not-run', 'child_proof': 'not-run',
              'removal_build': 'not-run', 'final_native_verification': 'not-run'}
    receipt = output / 'qualification.json'
    try:
        source = PREPARE.COMPILER.source_receipt(root)['sha256']
        report['source_sha256'] = source
        report['stock_build'] = 'running'
        context, stock_id, base = build(variant, False, output / 'stock', source, root)
        report.update(stock_build='passed', stock_image_id=stock_id, base_image=base)
        report['child_proof'] = 'running'
        OPTIONAL.qualify(stock_id, variant, context / 'manifests/fork-config.json', output / 'child', root)
        report['child_proof'] = 'passed'
        report['removal_build'] = 'running'
        target_context, target_id, target_base = build(variant, True, output / 'removal', source, root)
        if target_base != base:
            raise ValueError('base image changed between stock and removal builds')
        report.update(removal_build='passed', removal_image_id=target_id)
        report['final_native_verification'] = 'running'
        verify_built(target_context, target_id, output)
        report.update(final_native_verification='passed', status='passed')
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        report.update(status='failed', error=str(exc))
        raise
    finally:
        for key, value in list(report.items()):
            if value == 'running':
                report[key] = 'failed'
        receipt.write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', required=True, choices=['grouper', 'yellowfin'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        qualify(args.variant, args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'optional-removal build proof: {exc}\n')


if __name__ == '__main__':
    main()
