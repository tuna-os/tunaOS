"""Required coverage survives scheduler restrictions and preserves OCI identity."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from contracts import targets


def config():
    return {'config': {'required_platforms': ['linux/amd64', 'linux/arm64']},
            'variants': [{'id': 'albacore', 'platforms': ['linux/amd64'],
                          'flavors': [{'id': 'cosmic', 'build_image': True}]},
                         {'id': 'skipjack', 'experimental': True,
                          'platforms': ['linux/amd64', 'linux/arm64'],
                          'flavors': [{'id': 'cosmic-hwe', 'build_image': True},
                                      {'id': 'gnome-asahi', 'build_image': True, 'platforms': ['linux/arm64']},
                                      {'id': 'gnome-t2', 'build_image': True, 'platforms': ['linux/amd64']},
                                      {'id': 'xfce', 'build_image': False}]}]}


def test_enabled_targets_are_commitments_independent_of_scheduling():
    records = targets.resolve_required_targets(config())
    assert [(r['target']['variant'], r['target']['flavor'], r['target']['platform']) for r in records] == [
        ('albacore', 'cosmic', 'linux/amd64/v2'), ('albacore', 'cosmic', 'linux/arm64'),
        ('skipjack', 'cosmic-hwe', 'linux/amd64'), ('skipjack', 'cosmic-hwe', 'linux/arm64'),
        ('skipjack', 'gnome-asahi', 'linux/arm64'), ('skipjack', 'gnome-t2', 'linux/amd64')]
    assert all(r['required'] for r in records)
    assert [r['scheduled'] for r in records] == [False, False, True, True, True, True]
    assert records[0]['target'] == {'variant': 'albacore', 'flavor': 'cosmic', 'platform': 'linux/amd64/v2',
                                   'cpuBaseline': 'x86-64-v2', 'hardwareScope': 'generic'}


def test_scheduler_shrink_does_not_remove_required_cells():
    before = targets.resolve_required_targets(config())
    changed = config()
    changed['variants'][1]['platforms'] = ['linux/amd64']
    after = targets.resolve_required_targets(changed)
    assert [r['target'] for r in after] == [r['target'] for r in before]
    assert after[3]['scheduled'] is False


def test_multiline_yaml_and_null_override_inherit_variant():
    loaded = yaml.safe_load('''variants:
  - id: yellowfin
    platforms:
      - linux/amd64/v2
      - linux/arm64
    flavors:
      - id: base
        build_image: true
        platforms: null
''')
    result = targets.resolve_required_targets(loaded)
    assert [r['target']['platform'] for r in result] == ['linux/amd64/v2', 'linux/arm64']
    assert all(r['scheduled'] for r in result)


def test_publication_alias_and_suffix_do_not_replace_canonical_variant():
    data = config()
    data['variants'][1].update(id='bonito-rawhide', publish_name='bonito', tag_suffix='rawhide')
    record = targets.resolve_required_targets(data)[2]
    assert record['target']['variant'] == 'bonito-rawhide'
    assert record['publication'] == {'repository': 'ghcr.io/tuna-os/bonito', 'tag': 'cosmic-hwe-rawhide'}


@pytest.mark.parametrize('platform,identity,manager,package', [
    ('linux/amd64/v2', ('linux', 'amd64', 'v2'), 'rpm', 'x86_64'),
    ('linux/amd64', ('linux', 'amd64', None), 'dpkg', 'amd64'),
    ('linux/arm64', ('linux', 'arm64', None), 'dnf', 'aarch64'),
    ('linux/arm64', ('linux', 'arm64', None), 'apt', 'arm64'),
    ('linux/arm64', ('linux', 'arm64', None), 'pacman', 'aarch64'),
    ('linux/amd64/v2', ('linux', 'amd64', 'v2'), 'portage', 'x86_64')])
def test_oci_and_package_architecture_are_distinct(platform, identity, manager, package):
    assert targets.split_platform(platform) == identity
    assert targets.package_architecture(platform, manager) == package


@pytest.mark.parametrize('bad', ['linux/amd54', 'linux/amd64/v3', 'amd64/v2', None, 42])
def test_unknown_platforms_fail(bad):
    with pytest.raises(ValueError):
        targets.split_platform(bad)


@pytest.mark.parametrize('mutation', [
    lambda c: c['variants'].append(deepcopy(c['variants'][0])),
    lambda c: c['variants'][0]['flavors'].append(deepcopy(c['variants'][0]['flavors'][0])),
    lambda c: c['config'].update(required_platforms=['linux/amd64']),
    lambda c: c['config'].update(required_platforms=['linux/amd64', 'linux/amd64', 'linux/arm64']),
    lambda c: c['variants'][0].update(required_platforms=['linux/amd64', 'linux/arm64']),
    lambda c: c['variants'][0].update(platforms=[]),
    lambda c: c['variants'][0]['flavors'][0].update(platforms=[]),
    lambda c: c['variants'][0]['flavors'][0].update(build_image='true'),
    lambda c: c['variants'][0]['flavors'][0].update(id='gnome-asahi-t2'),
    lambda c: c['variants'][0].update(id='../albacore')])
def test_invalid_or_weakened_configuration_fails(mutation):
    data = config()
    mutation(data)
    with pytest.raises(ValueError):
        targets.resolve_required_targets(data)


@pytest.mark.parametrize('field,value', [('cpuBaseline', 'x86-64'), ('hardwareScope', 'apple-t2'),
                                        ('platform', 'linux/amd64'), ('variant', 'skipjack'), ('flavor', 'bad/name')])
def test_inconsistent_identity_fails(field, value):
    target = {'variant': 'albacore', 'flavor': 'cosmic', 'platform': 'linux/amd64/v2',
              'cpuBaseline': 'x86-64-v2', 'hardwareScope': 'generic'}
    target[field] = value
    with pytest.raises(ValueError):
        targets.target_key(target)


def test_generator_checks_generated_coverage_without_mutating(tmp_path):
    (tmp_path / '.github/workflows').mkdir(parents=True)
    (tmp_path / '.github/build-config.yml').write_text(yaml.safe_dump(config()))
    command = [sys.executable, str(ROOT / 'scripts/generate-workflows.py')]
    assert subprocess.run(command, cwd=tmp_path, capture_output=True).returncode == 0
    coverage = tmp_path / 'required-targets.json'
    original = coverage.read_bytes()
    assert subprocess.run(command + ['--check'], cwd=tmp_path, capture_output=True).returncode == 0
    coverage.write_text('{}\n')
    failed = subprocess.run(command + ['--check'], cwd=tmp_path, capture_output=True, text=True)
    assert failed.returncode != 0
    assert 'required-targets.json' in failed.stdout + failed.stderr
    assert coverage.read_text() == '{}\n'
    coverage.write_bytes(original)
    wrapper = tmp_path / '.github/workflows/build-albacore.yml'
    wrapper.write_text('drift\n')
    assert subprocess.run(command + ['--check'], cwd=tmp_path, capture_output=True).returncode != 0
    assert wrapper.read_text() == 'drift\n'


@pytest.mark.parametrize('flavor,platform,baseline,scope', [
    ('gnome-asahi', 'linux/amd64', 'x86-64', 'apple-silicon'),
    ('gnome-t2', 'linux/arm64', 'armv8-a', 'apple-t2')])
def test_hardware_incompatible_target_fails(flavor, platform, baseline, scope):
    with pytest.raises(ValueError):
        targets.validate_target({'variant': 'skipjack', 'flavor': flavor, 'platform': platform,
                                 'cpuBaseline': baseline, 'hardwareScope': scope})


def test_alma_t2_requires_v2_intel():
    data = config()
    data['variants'][0]['flavors'] = [{'id': 'gnome-t2', 'build_image': True}]
    records = targets.resolve_required_targets(data)
    assert records[0]['target'] == {'variant': 'albacore', 'flavor': 'gnome-t2',
                                   'platform': 'linux/amd64/v2', 'cpuBaseline': 'x86-64-v2',
                                   'hardwareScope': 'apple-t2'}
    assert len([r for r in records if r['target']['variant'] == 'albacore']) == 1


def test_identity_rejects_unknown_or_missing_fields():
    target = {'variant': 'skipjack', 'flavor': 'base', 'platform': 'linux/amd64',
              'cpuBaseline': 'x86-64', 'hardwareScope': 'generic'}
    with pytest.raises(ValueError):
        targets.validate_target({**target, 'architecture': 'amd64'})
    del target['cpuBaseline']
    with pytest.raises(ValueError):
        targets.validate_target(target)


def test_coverage_digest_is_deterministic_and_binds_scheduling():
    first = targets.coverage_document(config())
    assert first['schemaVersion'] == 1
    assert first['kind'] == 'required-targets'
    assert targets.coverage_document(deepcopy(config())) == first
    changed = config()
    changed['variants'][0]['platforms'] = ['linux/amd64/v2', 'linux/arm64']
    assert targets.coverage_document(changed)['coverageDigest'] != first['coverageDigest']
