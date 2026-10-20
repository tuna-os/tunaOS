"""tunaOS#3380: installed qualification must trust only matching guest evidence.

Falsification: behavioral -- feed a wrong desktop, digest, session, or failure marker to the validator; an unfixed validator reaches result writing and the corresponding assertion fails.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/lib/qualification-evidence.sh"
E2E = ROOT / "scripts/iso-e2e.sh"

EXPECTED_DESKTOP = "gnome"
EXPECTED_DIGEST = "sha256:source"
PROCESS_PATTERN = "gnome-shell"
MATCHING_MARKER = (
    "TUNAOS_DESKTOP_CONTRACT_OK desktop=gnome "
    "source_image_digest=sha256:source session_class=user "
    "session_type=wayland session_process=gnome-shell\n"
)


def _run_validator(tmp_path: Path, serial: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    serial_path = tmp_path / "installed-serial.log"
    serial_path.write_text(serial, encoding="utf-8")
    result_path = tmp_path / "qualification-result.json"
    helper = shlex.quote(str(HELPER))
    serial_file = shlex.quote(str(serial_path))
    result_file = shlex.quote(str(result_path))
    command = f"""
set -euo pipefail
source {helper}
if validate_installed_boot_evidence {serial_file} {shlex.quote(EXPECTED_DESKTOP)} {shlex.quote(EXPECTED_DIGEST)} {shlex.quote(PROCESS_PATTERN)}; then
    touch {result_file}
else
    exit 4
fi
"""
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", command],
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )
    return result, result_path


def test_matching_guest_marker_reaches_result_writing(tmp_path: Path):
    result, result_path = _run_validator(tmp_path, MATCHING_MARKER)

    assert result.returncode == 0, result.stderr
    assert result_path.is_file()


def test_wrong_desktop_or_digest_cannot_reach_result_writing(tmp_path: Path):
    wrong_desktop = MATCHING_MARKER.replace("desktop=gnome", "desktop=kde")
    wrong_digest = MATCHING_MARKER.replace(EXPECTED_DIGEST, "sha256:other")

    for serial in (wrong_desktop, wrong_digest):
        result, result_path = _run_validator(tmp_path, serial)
        assert result.returncode == 4
        assert not result_path.exists()


def test_missing_user_session_evidence_cannot_reach_result_writing(tmp_path: Path):
    serial = MATCHING_MARKER.replace("session_class=user ", "")

    result, result_path = _run_validator(tmp_path, serial)

    assert result.returncode == 4
    assert not result_path.exists()


def test_contract_fail_marker_cannot_reach_result_writing(tmp_path: Path):
    serial = MATCHING_MARKER + "TUNAOS_DESKTOP_CONTRACT_FAIL reason=dm_inactive\n"

    result, result_path = _run_validator(tmp_path, serial)

    assert result.returncode == 4
    assert not result_path.exists()


def test_iso_e2e_uses_validator_before_writing_result():
    script = E2E.read_text(encoding="utf-8")
    validate = script.index("validate_installed_boot_evidence")
    write = script.index("write_qualification_result()")

    assert script.index('. "${SCRIPT_DIR}/lib/qualification-evidence.sh"') < validate
    assert validate < write
