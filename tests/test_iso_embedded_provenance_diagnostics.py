"""Run actual workflow shell with tiny local stubs; no image build or download.

Falsification: execute missing, malformed and conflicting embedded metadata and
an unexported overlay digest; each must fail before qualification or lose the
exact child environment that the positive case requires.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/iso-e2e.yml'
DIGEST = 'sha256:' + 'a' * 64
BASE = 'sha256:' + 'b' * 64
FIELDS = ('base_image', 'base_digest', 'overlay_digest', 'engine_digest', 'platform')
SOURCE = {'base_image': 'ghcr.io/tuna-os/yellowfin:gnome', 'base_digest': BASE,
          'overlay_digest': DIGEST, 'engine_digest': 'sha256:' + 'c' * 64,
          'platform': 'linux/amd64/v2'}
INSTALLER = 'INSTALLER_BUNDLE_SHA256=' + 'd' * 64 + '\n'


def step(name):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return next(item['run'] for item in workflow['jobs']['e2e']['steps'] if item.get('name') == name)


def executable(path, body):
    path.write_text('#!' + sys.executable + '\n' + body)
    path.chmod(0o755)


def run_resolver(tmp_path, payloads, *, platform='linux/amd64/v2'):
    """Stub only extraction; execute the exact workflow parser, comparisons/gates."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'python3').symlink_to(sys.executable)
    fixture = tmp_path / 'payloads.json'
    fixture.write_text(json.dumps(payloads))
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/extract-iso-payloads.py').write_text(
        'import json, os\n'
        'for index, _ in enumerate(json.load(open(os.environ["PAYLOAD_FIXTURE"]))):\n'
        '    print("payload-" + str(index))\n'
    )
    executable(bin_dir / 'unsquashfs', '''import json, os, sys
payloads = json.load(open(os.environ['PAYLOAD_FIXTURE']))
payload = payloads[int(sys.argv[2].removeprefix('payload-'))]
key = 'source' if sys.argv[3].endswith('live-source.json') else 'installer'
if key not in payload:
    raise SystemExit(1)
value = payload[key]
print(value if isinstance(value, str) else json.dumps(value))
''')
    iso = tmp_path / 'tiny.iso'
    iso.write_bytes(b'tiny synthetic ISO bytes')
    output = tmp_path / 'github-env'
    output.write_text('')
    env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ['PATH'],
               PAYLOAD_FIXTURE=str(fixture), ISO_PATH=str(iso), GITHUB_ENV=str(output),
               PLATFORM=platform, PUBLISHED_MEDIA='false')
    result = subprocess.run(['/bin/bash', '-c', step('Resolve immutable ISO qualification inputs')],
                            cwd=tmp_path, env=env, text=True, capture_output=True, timeout=15)
    return result, output.read_text()


@pytest.mark.parametrize('field', FIELDS)
@pytest.mark.parametrize('mutation,label', [('absent', 'missing'), ('empty', 'missing'),
                                           ('unknown', 'unknown'), ('wrong-type', 'invalid')])
def test_each_required_field_gets_its_own_error_without_masking_source(tmp_path, field, mutation, label):
    source = copy.deepcopy(SOURCE)
    if mutation == 'absent':
        del source[field]
    else:
        source[field] = {'empty': '', 'unknown': 'unknown', 'wrong-type': None}[mutation]
    result, output = run_resolver(tmp_path, [{'source': source, 'installer': INSTALLER}])
    assert result.returncode != 0
    assert f'embedded provenance field {field} is {label}' in result.stderr
    assert 'does not contain a valid embedded source digest' not in result.stdout + result.stderr
    assert output == ''


@pytest.mark.parametrize('field,value', [
    ('base_digest', 'sha256:bad'), ('overlay_digest', 'sha256:bad'),
    ('engine_digest', 'latest'), ('platform', 'windows/amd64'), ('platform', 'linux/arm64/v2'),
    ('base_image', 'ref\tinjected'), ('base_image', ' ref'), ('base_image', 'ref\nnext'),
])
def test_invalid_required_value_fails_with_named_field(tmp_path, field, value):
    source = copy.deepcopy(SOURCE)
    source[field] = value
    result, output = run_resolver(tmp_path, [{'source': source, 'installer': INSTALLER}])
    assert result.returncode != 0
    assert f'field {field} is invalid' in result.stderr
    assert output == ''


@pytest.mark.parametrize('source', ['not json', '[]', 'null', '123'])
def test_malformed_provenance_document_is_not_reported_as_missing_source_digest(tmp_path, source):
    result, output = run_resolver(tmp_path, [{'source': source, 'installer': INSTALLER}])
    assert result.returncode != 0
    assert 'live-source.json is invalid' in result.stderr
    assert output == ''


def test_absent_provenance_file_has_a_distinct_error(tmp_path):
    result, output = run_resolver(tmp_path, [{'installer': INSTALLER}])
    assert result.returncode != 0
    assert 'does not contain embedded provenance (etc/tunaos/live-source.json)' in result.stdout
    assert output == ''


def test_complete_provenance_preserves_all_exact_outputs(tmp_path):
    result, output = run_resolver(tmp_path, [{'source': SOURCE, 'installer': INSTALLER}])
    assert result.returncode == 0, result.stdout + result.stderr
    values = dict(line.split('=', 1) for line in output.splitlines())
    assert values['TUNAOS_QUAL_SOURCE_REF'] == SOURCE['base_image']
    assert values['TUNAOS_QUAL_SOURCE_DIGEST'] == BASE
    assert values['TUNAOS_QUAL_OVERLAY_DIGEST'] == DIGEST
    assert values['TUNAOS_QUAL_ENGINE_DIGEST'] == SOURCE['engine_digest']
    assert values['TUNAOS_QUAL_PLATFORM'] == SOURCE['platform']
    assert values['TUNAOS_QUAL_INSTALLER_DIGEST'] == 'sha256:' + 'd' * 64
    assert values['STRICT_PUBLISHED_MEDIA'] == '0'


@pytest.mark.parametrize('field', FIELDS)
def test_conflicting_payloads_still_fail(tmp_path, field):
    other = copy.deepcopy(SOURCE)
    other[field] = {'base_image': 'ghcr.io/tuna-os/other:gnome', 'platform': 'linux/arm64'}.get(field, 'sha256:' + 'e' * 64)
    result, output = run_resolver(tmp_path, [{'source': SOURCE, 'installer': INSTALLER},
                                           {'source': other, 'installer': INSTALLER}])
    assert result.returncode != 0
    assert 'ISO payloads disagree on embedded provenance' in result.stdout + result.stderr
    assert output == ''


def test_incomplete_second_payload_is_not_silently_discarded(tmp_path):
    incomplete = copy.deepcopy(SOURCE)
    del incomplete['overlay_digest']
    result, output = run_resolver(tmp_path, [{'source': SOURCE, 'installer': INSTALLER},
                                           {'source': incomplete, 'installer': INSTALLER}])
    assert result.returncode != 0
    assert 'field overlay_digest is missing' in result.stderr
    assert output == ''


def test_identical_payloads_remain_supported(tmp_path):
    payload = {'source': SOURCE, 'installer': INSTALLER}
    result, output = run_resolver(tmp_path, [payload, payload])
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'TUNAOS_QUAL_OVERLAY_DIGEST={DIGEST}' in output


@pytest.mark.parametrize('case', ['wrong-platform', 'missing-installer'])
def test_existing_platform_and_installer_gates_remain_closed(tmp_path, case):
    payload = {'source': SOURCE, 'installer': INSTALLER}
    if case == 'missing-installer':
        del payload['installer']
    result, output = run_resolver(tmp_path, [payload], platform='linux/arm64' if case == 'wrong-platform' else SOURCE['platform'])
    assert result.returncode != 0
    assert ('does not match matrix target' if case == 'wrong-platform' else 'live-installer-info receipt') in result.stdout
    assert output == ''


def run_local_build_identity(tmp_path, overlay_digest):
    """Run the source/export/customization segment, with external command stubs.

    The sudo stub is a real child process preserving only inherited environment;
    unexported shell variables cannot leak into the separate customization child.
    """
    body = step('Build the ISO on this runner')
    start = body.index('case "$PLATFORM" in')
    end = body.index('ISO="$(find ', start)
    body = 'set -euo pipefail\n' + body[start:end]
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    executable(bin_dir / 'skopeo', 'import os\nprint(os.environ["FAKE_OVERLAY_DIGEST"])\n')
    executable(bin_dir / 'podman', 'import os\nprint(os.environ["FAKE_BASE_DIGEST"])\n')
    executable(bin_dir / 'sudo', '''import os, sys
args = sys.argv[1:]
if args[0] == '-E':
    args = args[1:]
os.execvp(args[0], args)
''')
    executable(bin_dir / 'just', '''import json, os, sys
if sys.argv[1] == 'iso':
    with open(os.environ['CUSTOMIZE_ENV'], 'w') as output:
        json.dump({key: value for key, value in os.environ.items() if key.startswith('TUNA_LIVE_')}, output)
''')
    (tmp_path / 'image-versions.yaml').write_text('tacklebox: "' + '1' * 40 + '"\n')
    result_path = tmp_path / 'customization-env.json'
    env = {key: value for key, value in os.environ.items() if not key.startswith('TUNA_LIVE_')}
    env.update(PATH=str(bin_dir) + os.pathsep + os.environ['PATH'], VARIANT='yellowfin', FLAVOR='gnome',
               PLATFORM='linux/amd64/v2', FAKE_OVERLAY_DIGEST=overlay_digest,
               FAKE_BASE_DIGEST=BASE, CUSTOMIZE_ENV=str(result_path))
    result = subprocess.run(['/bin/bash', '-c', body], cwd=tmp_path, env=env,
                            text=True, capture_output=True, timeout=15)
    return result, json.loads(result_path.read_text()) if result_path.exists() else None


def test_customization_child_receives_exact_verified_overlay_digest(tmp_path):
    result, child_env = run_local_build_identity(tmp_path, DIGEST)
    assert result.returncode == 0, result.stdout + result.stderr
    assert child_env['TUNA_LIVE_OVERLAY_DIGEST'] == DIGEST
    assert child_env['TUNA_LIVE_OVERLAY_REF'] == 'ghcr.io/tuna-os/live-overlay:yellowfin-gnome-linux-amd64-v2@' + DIGEST
    assert child_env['TUNA_LIVE_BASE_DIGEST'] == BASE
    assert child_env['TUNA_LIVE_OVERLAY_DIGEST'] != child_env['TUNA_LIVE_BASE_DIGEST']


@pytest.mark.parametrize('digest', ['', 'unknown', 'sha256:bad', 'sha256:' + 'A' * 64])
def test_missing_or_invalid_overlay_digest_never_reaches_customization(tmp_path, digest):
    result, child_env = run_local_build_identity(tmp_path, digest)
    assert result.returncode != 0
    assert 'invalid live overlay digest' in result.stdout
    assert child_env is None
