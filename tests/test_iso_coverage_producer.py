import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('coverage_producer', ROOT / 'scripts/iso-coverage-producer.py')
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)


def identity(tmp_path):
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'schemaVersion': 2, 'config': {'digest': 'sha256:' + 'a' * 64}, 'layers': []}))
    iso = tmp_path / 'media.iso'
    iso.write_bytes(b'exact ISO bytes')
    backend = tmp_path / 'fisherman'
    backend.write_bytes(b'actual injected binary')
    result = producer.capture(source, iso, backend, 'a' * 40, 'b' * 40)
    assert result['source_digest'] == 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()
    assert result['media_digest'] == producer.digest(iso)
    assert result['installer_digest'] == producer.digest(backend)
    return result


def emit(tmp_path, evidence, outcome='success'):
    return producer.emit(identity(tmp_path), evidence, 'skipjack:gnome:linux/amd64',
                         'a' * 40, 'b' * 40, 1, 1, outcome, '2026-10-23T12:00:00Z')


MARKERS = '\n'.join(['TUNAOS_LUKS_E2E_INSTALL_STARTED luks=1',
                     'TUNAOS_LUKS_E2E_ENCRYPTED_DISK_CONFIRMED',
                     'TUNAOS_LUKS_E2E_PASS encrypted=1 passphrase_unlock=1 installed_boot=1'])


def test_actual_files_and_stage_markers_bind_legacy_receipt(tmp_path):
    result = emit(tmp_path, MARKERS)
    assert result['status'] == 'pass'
    assert result['stage'] == 'legacy-luks' and result['mode'] == 'luks'
    assert 'artifact_digest' not in result  # API establishes transport identity later.
    assert set(result['checks']) == {'backend_install', 'installed_boot', 'passphrase_unlock'}


@pytest.mark.parametrize('evidence', ['', 'all steps success', MARKERS.replace('encrypted=1', 'encrypted=0'), 'prefix ' + MARKERS])
def test_workflow_success_or_near_matches_cannot_promote(tmp_path, evidence):
    assert emit(tmp_path, evidence)['status'] != 'pass'


def test_later_failure_cannot_promote_earlier_marker(tmp_path):
    assert emit(tmp_path, MARKERS, 'failure')['status'] == 'fail'


def test_index_or_empty_payload_is_not_a_source_digest(tmp_path):
    source = tmp_path / 'index.json'
    source.write_text('{"schemaVersion":2,"manifests":[]}')
    with pytest.raises(ValueError, match='platform image manifest'):
        producer.capture(source, source, source, 'a' * 40, 'b' * 40)


def test_capture_is_explicit_opt_in_and_receipt_retention_long_enough():
    script = (ROOT / 'scripts/iso-e2e.sh').read_text()
    workflow = (ROOT / '.github/workflows/luks-e2e.yml').read_text()
    assert '"${TUNAOS_COVERAGE_CAPTURE:-0}" == "1"' in script
    assert 'skopeo inspect --raw' in script
    assert '--installer "$FISHERMAN_OVERRIDE"' in script
    assert 'retention-days: 90' in workflow
    assert 'id: luks_install' in workflow
    assert 'INSTALL_OUTCOME: ${{ steps.luks_install.outcome }}' in workflow
