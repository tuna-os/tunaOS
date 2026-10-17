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


def test_permanent_flavor_limit_is_separate_from_scheduler_narrowing():
    data = config()
    data['variants'][0]['flavors'] = [{
        'id': 'base-nvidia', 'build_image': True,
        'platforms': ['linux/amd64'],
        'required_platforms': ['linux/amd64'],
    }]
    records = [
        row for row in targets.resolve_required_targets(data)
        if row['target']['variant'] == 'albacore'
    ]
    assert [row['target']['platform'] for row in records] == ['linux/amd64']
    assert records[0]['scheduled'] is True


@pytest.mark.parametrize('flavor,platforms', [
    ('gnome-asahi', ['linux/amd64', 'linux/arm64']),
    ('gnome-t2', ['linux/amd64', 'linux/arm64']),
])
def test_hardware_incompatible_scheduler_cells_are_rejected(flavor, platforms):
    data = config()
    data['variants'][1]['flavors'] = [{
        'id': flavor, 'build_image': True, 'platforms': platforms,
    }]
    with pytest.raises(ValueError):
        targets.resolve_required_targets(data)


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
              'cpuBaseline': 'x86-64-v3', 'hardwareScope': 'generic'}
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


@pytest.mark.parametrize('variant', ['skipjack', 'wahoo'])
def test_native_v3_baseline_keeps_ordinary_oci_amd64_identity(variant):
    data = {'variants': [{'id': variant, 'platforms': ['linux/amd64'],
                         'flavors': [{'id': 'cosmic', 'build_image': True}]}]}
    rows = targets.resolve_required_targets(data)
    assert [row['target'] for row in rows] == [
        {'variant': variant, 'flavor': 'cosmic', 'platform': 'linux/amd64',
         'cpuBaseline': 'x86-64-v3', 'hardwareScope': 'generic'},
        {'variant': variant, 'flavor': 'cosmic', 'platform': 'linux/arm64',
         'cpuBaseline': 'armv8-a', 'hardwareScope': 'generic'}]
    for baseline in ['x86-64', 'x86-64-v2']:
        with pytest.raises(ValueError):
            targets.validate_target({**rows[0]['target'], 'cpuBaseline': baseline})


_sample_config = config

DIGEST_A = 'sha256:' + 'a' * 64
DIGEST_B = 'sha256:' + 'b' * 64
DIGEST_C = 'sha256:' + 'c' * 64
DIGEST_D = 'sha256:' + 'd' * 64
DIGEST_E = 'sha256:' + 'e' * 64
DIGEST_F = 'sha256:' + 'f' * 64
DIGEST_1 = 'sha256:' + '1' * 64
DIGEST_2 = 'sha256:' + '2' * 64


def test_catalog_snapshot_accounts_for_required_and_extra_published_candidates():
    data = _sample_config()
    descriptors = {
        'albacore:cosmic:linux/amd64/v2': {
            'indexDigest': DIGEST_A,
            'platformManifestDigest': DIGEST_B,
            'configDigest': DIGEST_C,
            'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': 'v2'},
            'facts': {
                'digest': DIGEST_B,
                'desktop': 'cosmic',
                'kernelVer': '6.12.0-100.el10.x86_64',
                'hasSdBoot': True,
                'pkgManager': 'dnf',
                'repoFamily': 'el10',
                'layerCount': 52,
                'compressedSize': 1987654321,
                'bootc': True,
            },
        },
        'skipjack:cosmic-hwe:linux/amd64': {
            'indexDigest': DIGEST_A,
            'platformManifestDigest': DIGEST_D,
            'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': None},
        },
        'skipjack:cosmic-hwe:linux/arm64': {
            'indexDigest': DIGEST_A,
            'platformManifestDigest': DIGEST_E,
            'ociPlatform': {'os': 'linux', 'architecture': 'arm64', 'variant': 'v8'},
        },
        'skipjack:xfce:linux/amd64': {
            'platformManifestDigest': DIGEST_F,
            'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': None},
        },
    }
    overlays = {
        'albacore:cosmic:linux/amd64/v2': {
            'liveOverlayDigest': DIGEST_1,
            'labels': {
                'org.tunaos.live-overlay.actual-base-digest': DIGEST_B,
                'org.tunaos.live-overlay.base-digest': DIGEST_B,
            },
        },
        'skipjack:cosmic-hwe:linux/amd64': {
            'liveOverlayDigest': DIGEST_2,
            'liveOverlayBaseDigest': DIGEST_D,
        },
        'skipjack:cosmic-hwe:linux/arm64': {
            'liveOverlayDigest': DIGEST_2,
            'liveOverlayBaseDigest': DIGEST_E,
        },
        'skipjack:xfce:linux/amd64': {
            'liveOverlayDigest': DIGEST_2,
            'liveOverlayBaseDigest': DIGEST_F,
        },
    }
    receipts = [
        {
            'target': {
                'variant': 'albacore',
                'flavor': 'cosmic',
                'platform': 'linux/amd64/v2',
                'cpuBaseline': 'x86-64-v2',
                'hardwareScope': 'generic',
            },
            'platformManifestDigest': DIGEST_B,
            'liveOverlayDigest': DIGEST_1,
            'qualifiedAt': '2026-10-17T01:02:03Z',
            'receiptDigest': DIGEST_C,
        },
        {
            'variant': 'skipjack',
            'flavor': 'cosmic-hwe',
            'platform': 'linux/amd64',
            'platformManifestDigest': DIGEST_D,
            'liveOverlayDigest': DIGEST_2,
            'localOnly': True,
            'reason': 'qemu-only-verification',
            'qualifiedAt': '2026-10-17T02:00:00Z',
        },
    ]

    snapshot = targets.catalog_snapshot(
        data,
        descriptors=descriptors,
        overlays=overlays,
        receipts=receipts,
        producer_revision='rev-1',
        generated_at='2026-10-17T03:00:00Z',
        installer_revision='inst-1',
        engine_revision='eng-1',
    )
    targets.validate_catalog_snapshot(snapshot)
    assert snapshot['coverageDigest'] == targets.coverage_document(data)['coverageDigest']

    by_key = {entry['targetKey']: entry for entry in snapshot['targets']}
    assert set(by_key) == {
        'albacore:cosmic:linux/amd64/v2',
        'albacore:cosmic:linux/arm64',
        'skipjack:cosmic-hwe:linux/amd64',
        'skipjack:cosmic-hwe:linux/arm64',
        'skipjack:gnome-asahi:linux/arm64',
        'skipjack:gnome-t2:linux/amd64',
        'skipjack:xfce:linux/amd64',
    }

    alma_v2 = by_key['albacore:cosmic:linux/amd64/v2']
    assert alma_v2['required'] is True
    assert alma_v2['scheduled'] is False
    assert alma_v2['availability'] == {
        'available': True,
        'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': 'v2'},
    }
    assert alma_v2['qualification']['status'] == 'qualified'
    assert alma_v2['qualification']['reason'] is None
    assert alma_v2['qualification']['qualifiedAt'] == '2026-10-17T01:02:03Z'
    assert alma_v2['qualification']['receiptDigest'] == DIGEST_C

    alma_arm = by_key['albacore:cosmic:linux/arm64']
    assert alma_arm['required'] is True
    assert alma_arm['availability']['available'] is False
    assert alma_arm['qualification']['status'] == 'unqualified'
    assert alma_arm['qualification']['reason'] == 'missing-platform-descriptor'

    skipjack_local = by_key['skipjack:cosmic-hwe:linux/amd64']
    assert skipjack_local['qualification']['status'] == 'local-only'
    assert skipjack_local['qualification']['reason'] == 'qemu-only-verification'
    assert skipjack_local['qualification']['qualifiedAt'] == '2026-10-17T02:00:00Z'
    assert skipjack_local['qualification']['receiptDigest'].startswith('sha256:')

    skipjack_untested = by_key['skipjack:cosmic-hwe:linux/arm64']
    assert skipjack_untested['availability']['available'] is True
    assert skipjack_untested['qualification']['status'] == 'unqualified'
    assert skipjack_untested['qualification']['reason'] == 'untested-snapshot'

    for unsupported_key in ('skipjack:gnome-asahi:linux/arm64', 'skipjack:gnome-t2:linux/amd64'):
        assert by_key[unsupported_key]['required'] is True
        assert by_key[unsupported_key]['qualification']['status'] == 'unsupported'
        assert by_key[unsupported_key]['qualification']['reason'] == 'hardware-scope-unsupported'

    extra = by_key['skipjack:xfce:linux/amd64']
    assert extra['required'] is False
    assert extra['target'] == {
        'variant': 'skipjack',
        'flavor': 'xfce',
        'platform': 'linux/amd64',
        'cpuBaseline': 'x86-64-v3',
        'hardwareScope': 'generic',
    }
    assert extra['availability']['available'] is True
    assert extra['qualification']['status'] == 'unqualified'
    assert extra['qualification']['reason'] == 'untested-snapshot'


def test_catalog_binds_facts_and_customization_inputs_to_platform_manifest_digest():
    data = _sample_config()
    descriptors = {
        'albacore:cosmic:linux/amd64/v2': {
            'indexDigest': DIGEST_A,
            'platformManifestDigest': DIGEST_B,
            'configDigest': DIGEST_C,
            'facts': {
                'digest': DIGEST_B,
                'desktop': 'cosmic',
                'kernelVer': '6.12.0-100.el10.x86_64',
                'hasSdBoot': True,
                'pkgManager': 'dnf',
                'repoFamily': 'el10',
                'layerCount': 48,
                'compressedSize': 123456789,
                'bootc': True,
            },
        },
        'skipjack:cosmic-hwe:linux/amd64': {
            'indexDigest': DIGEST_A,
            'platformManifestDigest': DIGEST_D,
            'facts': {
                'digest': DIGEST_E,
                'desktop': 'cosmic',
                'kernelVer': 'stale-kernel-from-old-tag',
                'hasSdBoot': True,
                'pkgManager': 'dnf',
                'repoFamily': 'el10',
                'layerCount': 99,
                'compressedSize': 999999,
                'bootc': True,
            },
        },
    }
    overlays = {
        'albacore:cosmic:linux/amd64/v2': {
            'liveOverlayDigest': DIGEST_1,
            'liveOverlayBaseDigest': DIGEST_B,
        },
    }
    snapshot = targets.catalog_snapshot(
        data,
        descriptors=descriptors,
        overlays=overlays,
        installer_revision='inst-rev-42',
        engine_revision='eng-rev-99',
    )
    by_key = {entry['targetKey']: entry for entry in snapshot['targets']}

    bound = by_key['albacore:cosmic:linux/amd64/v2']
    assert bound['resolvedInputs'] == {
        'platformManifestDigest': DIGEST_B,
        'indexDigest': DIGEST_A,
        'configDigest': DIGEST_C,
        'liveOverlayDigest': DIGEST_1,
        'liveOverlayBaseDigest': DIGEST_B,
        'installerRevision': 'inst-rev-42',
        'engineRevision': 'eng-rev-99',
    }
    assert bound['facts'] == {
        'digest': DIGEST_B,
        'desktop': 'cosmic',
        'kernelVer': '6.12.0-100.el10.x86_64',
        'hasSdBoot': True,
        'pkgManager': 'dnf',
        'repoFamily': 'el10',
        'layerCount': 48,
        'compressedSize': 123456789,
        'bootc': True,
    }

    stale_facts_entry = by_key['skipjack:cosmic-hwe:linux/amd64']
    assert stale_facts_entry['facts']['digest'] == DIGEST_D
    assert stale_facts_entry['facts']['kernelVer'] == ''
    assert stale_facts_entry['facts']['layerCount'] == 0
    assert stale_facts_entry['facts']['compressedSize'] == 0
    assert stale_facts_entry['facts']['hasSdBoot'] is False

    with pytest.raises(ValueError, match='conflated'):
        targets.catalog_snapshot(
            data,
            descriptors={
                'albacore:cosmic:linux/amd64/v2': {
                    'indexDigest': DIGEST_A,
                    'platformManifestDigest': DIGEST_A,
                },
            },
        )


def test_amd64_descriptor_never_satisfies_alma_amd64_v2_target():
    data = _sample_config()
    descriptors = {
        'albacore:cosmic:linux/amd64/v2': {
            'platformManifestDigest': DIGEST_B,
            'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': None},
        },
        'ghcr.io/tuna-os/albacore:cosmic@linux/amd64': {
            'platformManifestDigest': DIGEST_C,
            'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': None},
        },
    }
    snapshot = targets.catalog_snapshot(data, descriptors=descriptors)
    by_key = {entry['targetKey']: entry for entry in snapshot['targets']}

    alma_v2 = by_key['albacore:cosmic:linux/amd64/v2']
    assert alma_v2['availability'] == {
        'available': False,
        'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': 'v2'},
    }
    assert alma_v2['resolvedInputs']['platformManifestDigest'] is None
    assert alma_v2['qualification']['status'] == 'unqualified'
    assert alma_v2['qualification']['reason'] == 'missing-platform-descriptor'
    assert 'albacore:cosmic:linux/amd64' not in by_key

    bad_entry = deepcopy(alma_v2)
    bad_entry['availability']['ociPlatform'] = {'os': 'linux', 'architecture': 'amd64', 'variant': None}
    with pytest.raises(ValueError, match='ociPlatform'):
        targets.validate_catalog_entry(bad_entry)


def test_overlay_base_digest_mismatch_and_label_conflict_block_qualification():
    data = _sample_config()
    descriptors = {
        'albacore:cosmic:linux/amd64/v2': {
            'platformManifestDigest': DIGEST_B,
            'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': 'v2'},
        },
        'skipjack:cosmic-hwe:linux/amd64': {
            'platformManifestDigest': DIGEST_D,
            'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': None},
        },
        'skipjack:cosmic-hwe:linux/arm64': {
            'platformManifestDigest': DIGEST_E,
            'ociPlatform': {'os': 'linux', 'architecture': 'arm64', 'variant': None},
        },
    }
    overlays = {
        'albacore:cosmic:linux/amd64/v2': {
            'liveOverlayDigest': DIGEST_1,
            'labels': {
                'org.tunaos.live-overlay.actual-base-digest': DIGEST_C,
                'org.tunaos.live-overlay.base-digest': DIGEST_C,
            },
        },
        'skipjack:cosmic-hwe:linux/amd64': {
            'liveOverlayDigest': DIGEST_2,
            'labels': {
                'org.tunaos.live-overlay.actual-base-digest': DIGEST_D,
                'org.tunaos.live-overlay.base-digest': DIGEST_C,
            },
        },
    }
    receipts = {
        'albacore:cosmic:linux/amd64/v2': {
            'platformManifestDigest': DIGEST_B,
            'liveOverlayDigest': DIGEST_1,
            'qualifiedAt': '2026-10-17T00:00:00Z',
        },
        'skipjack:cosmic-hwe:linux/amd64': {
            'platformManifestDigest': DIGEST_D,
            'liveOverlayDigest': DIGEST_2,
            'qualifiedAt': '2026-10-17T00:00:00Z',
        },
    }

    snapshot = targets.catalog_snapshot(
        data,
        descriptors=descriptors,
        overlays=overlays,
        receipts=receipts,
    )
    by_key = {entry['targetKey']: entry for entry in snapshot['targets']}

    mismatched_base = by_key['albacore:cosmic:linux/amd64/v2']
    assert mismatched_base['qualification']['status'] == 'unqualified'
    assert mismatched_base['qualification']['reason'] == 'overlay-base-digest-mismatch'

    conflicting_labels = by_key['skipjack:cosmic-hwe:linux/amd64']
    assert conflicting_labels['qualification']['status'] == 'unqualified'
    assert conflicting_labels['qualification']['reason'] == 'overlay-base-digest-mismatch'

    missing_overlay = by_key['skipjack:cosmic-hwe:linux/arm64']
    assert missing_overlay['qualification']['status'] == 'unqualified'
    assert missing_overlay['qualification']['reason'] == 'missing-live-overlay'


def test_moving_tag_without_matching_digest_receipt_is_unqualified():
    data = _sample_config()
    descriptors = {
        'albacore:cosmic:linux/amd64/v2': {
            'platformManifestDigest': DIGEST_B,
            'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': 'v2'},
        },
        'skipjack:cosmic-hwe:linux/amd64': {
            'platformManifestDigest': DIGEST_D,
            'ociPlatform': {'os': 'linux', 'architecture': 'amd64', 'variant': None},
        },
    }
    receipts = {
        'ghcr.io/tuna-os/albacore:cosmic': {
            'variant': 'albacore',
            'flavor': 'cosmic',
            'platform': 'linux/amd64/v2',
            'platformManifestDigest': DIGEST_A,
            'qualifiedAt': '2026-10-16T00:00:00Z',
            'receiptDigest': DIGEST_C,
        },
    }

    stale_snapshot = targets.catalog_snapshot(data, descriptors=descriptors, receipts=receipts)
    by_key = {entry['targetKey']: entry for entry in stale_snapshot['targets']}
    assert by_key['albacore:cosmic:linux/amd64/v2']['qualification'] == {
        'status': 'unqualified',
        'reason': 'stale-qualification-receipt',
        'qualifiedAt': None,
        'receiptDigest': None,
        'browser': None,
        'resources': None,
    }
    assert by_key['skipjack:cosmic-hwe:linux/amd64']['qualification']['status'] == 'unqualified'
    assert by_key['skipjack:cosmic-hwe:linux/amd64']['qualification']['reason'] == 'untested-snapshot'

    receipts['ghcr.io/tuna-os/albacore:cosmic']['platformManifestDigest'] = DIGEST_B
    qualified_snapshot = targets.catalog_snapshot(data, descriptors=descriptors, receipts=receipts)
    qualified_by_key = {entry['targetKey']: entry for entry in qualified_snapshot['targets']}
    assert qualified_by_key['albacore:cosmic:linux/amd64/v2']['qualification']['status'] == 'qualified'
    assert qualified_by_key['albacore:cosmic:linux/amd64/v2']['qualification']['reason'] is None
    assert qualified_by_key['albacore:cosmic:linux/amd64/v2']['qualification']['qualifiedAt'] == '2026-10-16T00:00:00Z'
    assert qualified_by_key['albacore:cosmic:linux/amd64/v2']['qualification']['receiptDigest'] == DIGEST_C


def test_validate_catalog_snapshot_rejects_schema_and_policy_violations():
    snapshot = targets.catalog_snapshot(_sample_config())
    targets.validate_catalog_snapshot(snapshot)

    tampered = deepcopy(snapshot)
    tampered['snapshotDigest'] = DIGEST_A
    with pytest.raises(ValueError, match='snapshotDigest'):
        targets.validate_catalog_snapshot(tampered)

    unsorted = deepcopy(snapshot)
    unsorted['targets'] = list(reversed(unsorted['targets']))
    with pytest.raises(ValueError, match='sorted'):
        targets.validate_catalog_snapshot(unsorted)

    by_key = {entry['targetKey']: entry for entry in snapshot['targets']}
    unavail_qualified = deepcopy(by_key['albacore:cosmic:linux/amd64/v2'])
    unavail_qualified['qualification'] = {
        'status': 'qualified',
        'reason': None,
        'qualifiedAt': '2026-10-17T00:00:00Z',
        'receiptDigest': DIGEST_C,
        'browser': None,
        'resources': None,
    }
    with pytest.raises(ValueError, match='available platformManifestDigest'):
        targets.validate_catalog_entry(unavail_qualified)

    missing_reason = deepcopy(by_key['albacore:cosmic:linux/amd64/v2'])
    missing_reason['qualification']['reason'] = ''
    with pytest.raises(ValueError, match='blocker reason'):
        targets.validate_catalog_entry(missing_reason)
