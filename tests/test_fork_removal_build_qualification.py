"""Build orchestration contracts only; stubs are not native image evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('removal_build', ROOT / 'scripts/qualify-fork-removal-build.py')
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


@pytest.fixture
def proof(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(MOD.PREPARE.COMPILER, 'source_receipt', lambda root: {'sha256': 'a' * 64})
    def build(variant, remove, output, source, root):
        calls.append('removal-build' if remove else 'stock-build')
        context = output / 'context'
        (context / 'manifests').mkdir(parents=True)
        (context / 'manifests/fork-config.json').write_text('{}')
        return context, 'sha256:' + ('c' if remove else 'b') * 64, 'registry/base@sha256:' + 'd' * 64
    monkeypatch.setattr(MOD, 'build', build)
    monkeypatch.setattr(MOD.OPTIONAL, 'qualify', lambda *args: calls.append('child-proof'))
    monkeypatch.setattr(MOD, 'verify_built', lambda *args: calls.append('final-verification'))
    return tmp_path / 'proof', calls


def test_stock_then_child_then_actual_build_and_native_verification(proof):
    output, calls = proof
    report = MOD.qualify('grouper', output)
    assert calls == ['stock-build', 'child-proof', 'removal-build', 'final-verification']
    assert report['status'] == 'passed'
    assert report['boot'] == report['identity'] == report['installer'] == 'not-run'
    assert report['publishing'] is False
    assert report['stock_image_id'] != report['removal_image_id']


@pytest.mark.parametrize('phase', ['stock', 'child', 'removal', 'verify'])
def test_failure_stops_later_steps_and_records_terminal_evidence(proof, monkeypatch, phase):
    output, calls = proof
    original = MOD.build
    def fail(*args, **kwargs):
        raise ValueError('injected native failure')
    if phase in {'stock', 'removal'}:
        def build(variant, remove, *args):
            if remove == (phase == 'removal'):
                fail()
            return original(variant, remove, *args)
        monkeypatch.setattr(MOD, 'build', build)
    elif phase == 'child':
        monkeypatch.setattr(MOD.OPTIONAL, 'qualify', fail)
    else:
        monkeypatch.setattr(MOD, 'verify_built', fail)
    with pytest.raises(ValueError, match='injected'):
        MOD.qualify('yellowfin', output)
    report = json.loads((output / 'qualification.json').read_text())
    assert report['status'] == 'failed'
    assert 'running' not in report.values()
    assert 'final-verification' not in calls
    if phase in {'stock', 'child'}:
        assert 'removal-build' not in calls


def test_base_drift_is_not_a_comparable_removal_build(proof, monkeypatch):
    output, _ = proof
    original = MOD.build
    def build(variant, remove, *args):
        context, image, base = original(variant, remove, *args)
        return context, image, base + ('changed' if remove else '')
    monkeypatch.setattr(MOD, 'build', build)
    with pytest.raises(ValueError, match='base image changed'):
        MOD.qualify('grouper', output)
    assert json.loads((output / 'qualification.json').read_text())['status'] == 'failed'


def test_output_is_never_reused(proof):
    output, calls = proof
    output.mkdir()
    with pytest.raises(ValueError, match='new'):
        MOD.qualify('grouper', output)
    assert calls == []


def test_native_verifier_uses_completed_path_not_remove_again():
    assert 'helper.verify_complete' in MOD.VERIFY
    assert 'helper.apply' not in MOD.VERIFY
    assert "overall.get('remove') != ['fastfetch']" in MOD.VERIFY
    assert 'identity[\'manifest_sha256\']' in MOD.VERIFY


def test_workflow_is_bounded_independent_and_nonpublishing():
    config = yaml.safe_load((ROOT / '.github/workflows/fork-removal-build-qualification.yml').read_text())
    job = config['jobs']['native-build']
    assert job['strategy']['matrix']['variant'] == ['yellowfin', 'grouper']
    assert job['strategy']['fail-fast'] is False
    assert job['timeout-minutes'] == 180
    assert config['concurrency']['cancel-in-progress'] is False
    assert config['permissions'] == {'contents': 'read', 'packages': 'read'}
    runs = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'qualify-fork-removal-build.py' in runs
    assert 'podman push' not in runs and 'qualify-fork-login.py' not in runs
    assert 'qualify-fork-installer.py' not in runs
    assert 'source-receipt.json' in runs and 'native-evidence.json' in runs


def test_final_native_timeout_cleans_only_its_labelled_child(tmp_path, monkeypatch):
    name = None
    alive = True
    def run(args, **kwargs):
        nonlocal name, alive
        if args[:2] == ['podman', 'run']:
            assert '--pull=never' in args and '--network=none' in args
            name = args[args.index('--name') + 1]
            raise subprocess.TimeoutExpired(args, 1200)
        if args[:3] == ['podman', 'container', 'exists']:
            return subprocess.CompletedProcess(args, 0 if alive else 1)
        assert args == ['podman', 'rm', '--force', name]
        alive = False
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(MOD.subprocess, 'run', run)
    monkeypatch.setattr(MOD.subprocess, 'check_output', lambda *args, **kwargs: json.dumps([
        {'Config': {'Labels': {'org.tunaos.removal-build-proof': name}}}]))
    with pytest.raises(subprocess.TimeoutExpired):
        MOD.verify_built(tmp_path, 'sha256:' + 'a' * 64, tmp_path)
    assert not alive


@pytest.mark.parametrize('remove', [False, True])
def test_real_build_entry_uses_compiled_intent_and_sanitized_environment(tmp_path, monkeypatch, remove):
    calls = []
    def prepare(config_path, destination, root):
        config = yaml.safe_load(config_path.read_text())
        assert config['global'] == {'packages': {'remove': ['fastfetch'] if remove else []}}
        assert config['catalog'] == {'sha256': 'a' * 64}
        context = destination / 'grouper--gnome--linux-amd64'
        (context / 'manifests').mkdir(parents=True)
        (context / 'manifests/fork-config.json').write_text(json.dumps({'sources': {'sha256': 'a' * 64}}))
        return [{'context': context.name, 'base_digest_pinned': True, 'environment': {
            'IMAGE_TAG': 'localhost/' + config['image']['namespace'] + '/grouper:gnome-linux-amd64',
            'USE_CACHE': '0', 'IS_CI': '0', 'SKIP_RECHUNK': '1', 'BASE_IMAGE': 'base@sha256:' + 'b' * 64}}]
    monkeypatch.setattr(MOD.PREPARE, 'prepare', prepare)
    monkeypatch.setattr(MOD, 'inspect', lambda image: 'sha256:' + 'c' * 64)
    monkeypatch.setattr(MOD.subprocess, 'run', lambda args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setenv('TUNAOS_BUILD_CONFIG', 'untrusted-inherited-override')
    context, image, base = MOD.build('grouper', remove, tmp_path / 'build', 'a' * 64, ROOT)
    assert image == 'sha256:' + 'c' * 64 and '@sha256:' in base
    assert len(calls) == 1
    assert calls[0][0] == ['bash', 'scripts/build-image-inner.sh']
    assert calls[0][1]['cwd'] == context and calls[0][1]['check'] is True
    assert 'TUNAOS_BUILD_CONFIG' not in calls[0][1]['env']
    assert calls[0][1]['env']['USE_CACHE'] == '0'
