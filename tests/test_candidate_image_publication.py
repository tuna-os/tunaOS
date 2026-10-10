"""Feature dispatch must build boot-testable candidates without production tags."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TAG = "${{ github.repository == 'tuna-os/tunaOS' && github.ref == 'refs/heads/main' && inputs.default-tag || format('candidate-{0}-{1}-{2}', github.run_id, github.run_attempt, inputs.default-tag) }}"
PIN = '${{ needs.manifest.outputs.image }}@${{ needs.manifest.outputs.digest }}'


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())


def test_all_remote_tag_environments_are_source_aware():
    jobs = workflow('reusable-build-image.yml')['jobs']
    count = 0
    for job in jobs.values():
        environments = [job.get('env', {})] + [step.get('env', {}) for step in job.get('steps', [])]
        for environment in environments:
            if 'DEFAULT_TAG' in environment:
                assert environment['DEFAULT_TAG'] in {TAG, '${{ env.DEFAULT_TAG }}'}
                count += 1
    assert count >= 10


def test_candidates_keep_signature_and_boot_gates_but_never_promote():
    jobs = workflow('reusable-build-image.yml')['jobs']
    for name in ('sign', 'verify_boot', 'verify_desktop', 'verify_asahi'):
        assert 'inputs.publish' in jobs[name]['if']
        assert "github.ref == 'refs/heads/main'" not in jobs[name]['if']
    promotion = jobs['tag-image']
    assert "github.repository == 'tuna-os/tunaOS'" in promotion['if']
    assert "github.ref == 'refs/heads/main'" in promotion['if']
    assert 'inputs.publish' in promotion['if']
    assert set(promotion['needs']) == {'manifest', 'sign', 'verify_desktop', 'verify_boot', 'verify_asahi'}
    for name in ('sign', 'verify_desktop', 'verify_boot', 'verify_asahi'):
        assert 'needs.' + name + '.result' in promotion['if']


def test_boot_desktop_and_asahi_verify_immutable_manifest():
    jobs = workflow('reusable-build-image.yml')['jobs']
    gate = next(step for step in jobs['verify_boot']['steps'] if step.get('name') == 'Build qcow2 from testing image')
    assert gate['env']['TEST_IMAGE'] == PIN
    for step in jobs['verify_desktop']['steps']:
        if 'TEST_IMAGE' in step.get('env', {}):
            assert step['env']['TEST_IMAGE'] == PIN
    assert jobs['verify_asahi']['with']['image'] == PIN
    promote = next(step for step in jobs['tag-image']['steps'] if 'SOURCE_IMAGE=' in step.get('run', ''))
    assert 'SOURCE_IMAGE="${IMAGE_REGISTRY}/${IMAGE_NAME}@${INDEX_DIGEST}"' in promote['run']
    assert promote['env']['INDEX_DIGEST'] == '${{ needs.manifest.outputs.digest }}'


def test_pr_cannot_publish_even_if_caller_passes_publish_true():
    jobs = workflow('reusable-build-image.yml')['jobs']
    step = next(step for step in jobs['build_push']['steps'] if 'sudo podman push' in step.get('run', ''))
    assert 'inputs.publish' in step['if']
    assert "github.event_name != 'pull_request'" in step['if']
    manifest = next(step for step in jobs['manifest']['steps'] if step.get('name') == 'Push Manifest')
    assert 'inputs.publish' in manifest['if'] and "github.event_name != 'pull_request'" in manifest['if']


def test_unified_nonmain_dispatch_cannot_publish_production_media():
    jobs = workflow('build-variant.yml')['jobs']
    media = [job for job in jobs.values() if job.get('uses', '').endswith('reusable-build-artifacts.yml')]
    assert len(media) == 3
    for job in media:
        assert "github.ref == 'refs/heads/main'" in job['if']
        assert "github.repository == 'tuna-os/tunaOS'" in job['if']
        assert "github.ref == 'refs/heads/main'" in job['with']['upload-r2']


def test_outputs_do_not_claim_candidate_media_or_production_promotion():
    outputs = workflow('reusable-build-image.yml')[True]['workflow_call']['outputs']
    assert outputs['production_promoted']['value'] == "${{ jobs.tag-image.result == 'success' }}"
    assert 'candidate-iso-not-run' in outputs['iso_scope']['value']
    assert "format('{0}@{1}'" in outputs['candidate_reference']['value']


def test_candidate_overlay_parent_is_current_run_platform_child():
    steps = workflow('reusable-build-image.yml')['jobs']['build_push']['steps']
    resolve = next(step for step in steps if step.get('id') == 'candidate-parent')
    assert 'RUN_ATTEMPT' in resolve['run'] and 'SAFE_PLATFORM' in resolve['run']
    assert 'resolve-flavor.sh' in resolve['run'] and 'PARENT_FLAVOR' in resolve['run']
    download = next(step for step in steps if step.get('name') == 'Download current run candidate parent')
    assert download['with']['name'] == '${{ steps.candidate-parent.outputs.artifact }}'
    assert 'run-id' not in download['with'] and 'github-token' not in download['with']
    bind = next(step for step in steps if step.get('id') == 'bound-parent')
    assert '^sha256:[0-9a-f]{64}$' in bind['run']
    assert '${IMAGE_REGISTRY}/${IMAGE_NAME}@${digest}' in bind['run']
    build = next(step for step in steps if step.get('id') == 'build-image')
    assert build['env']['CHAIN_BASE_IMAGE'] == '${{ steps.bound-parent.outputs.reference || inputs.chain-base-image }}'
