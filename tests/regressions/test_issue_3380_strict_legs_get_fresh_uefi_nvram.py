"""#3380: every strict GUI leg starts with fresh OVMF NVRAM.

Run 40068149541 (job 120806616493) passed the plain leg, then the LUKS live
boot read the NVRAM the plain install had written. Firmware tried the plain
disk's "CentOS Stream" shim entry on the new blank LUKS disk, fell to the EFI
Internal Shell, never booted the CD, and the walkthrough reported "GUI did
not transition from unknown to welcome".

These tests run the real `reset_uefi_vars` and `run_strict_offline_gui`
functions, extracted from scripts/iso-e2e.sh, with stubbed QEMU legs.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/iso-e2e.sh"


def _function(name: str) -> str:
    text = SCRIPT.read_text()
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.M | re.S)
    assert match, f"{name} not found in {SCRIPT}"
    return match.group(0)


def _run(tmp_path: Path, template: bool) -> subprocess.CompletedProcess:
    out = tmp_path / "out"
    out.mkdir()
    iso = tmp_path / "media.iso"
    iso.write_bytes(b"iso")
    src = tmp_path / "OVMF_VARS.template"
    src.write_bytes(b"pristine-template")
    harness = f"""
set -uo pipefail
OUTPUT_DIR={out}
OVMF_VARS={out}/UEFI_VARS.fd
UEFI_VARS_SRC={src if template else ""}
ISO_PATH={iso}
QEMU=/bin/true
STRICT_OFFLINE_GUI_MODES=plain,luks
QUAL_EVIDENCE_JSON={out}/qual.json
STRICT_EVIDENCE_LOG={out}/evidence.log
TUNAOS_QUAL_OVERLAY_DIGEST=sha256:{"a" * 64}
TUNAOS_QUAL_ENGINE_DIGEST=sha256:{"b" * 64}
e2e_phase() {{ :; }}
strict_offline_evidence() {{ :; }}
strict_require_digest() {{ :; }}
start_swtpm() {{ :; }}
emit_qualification_evidence() {{ echo emitted; }}
verify_strict_installed_boot() {{ :; }}
run_strict_gui_install() {{
    echo "leg=$1 nvram=$(sha256sum "$OVMF_VARS" | cut -c1-12)"
    # What the installer does: bootupd/efibootmgr prepend its own entry.
    printf 'Boot000A CentOS Stream from %s disk' "$1" >"$OVMF_VARS"
}}
{_function("reset_uefi_vars")}
reset_uefi_vars
echo "initial nvram=$(sha256sum "$OVMF_VARS" | cut -c1-12)"
{_function("run_strict_offline_gui")}
run_strict_offline_gui
"""
    return subprocess.run(
        ["bash", "-c", harness], check=False, capture_output=True, text=True
    )


def _nvram_by_leg(stdout: str) -> dict[str, str]:
    return dict(re.findall(r"^leg=(\w+) nvram=(\w+)$", stdout, re.M))


def test_both_legs_boot_with_the_pristine_template(tmp_path):
    result = _run(tmp_path, template=True)
    assert result.returncode == 0, result.stderr
    initial = re.search(r"^initial nvram=(\w+)$", result.stdout, re.M).group(1)
    legs = _nvram_by_leg(result.stdout)
    assert set(legs) == {"plain", "luks"}
    assert legs == {"plain": initial, "luks": initial}
    assert "emitted" in result.stdout


def test_combined_ovmf_fallback_also_drops_the_previous_legs_entries(tmp_path):
    # Without a vars template, `truncate -s 4M` alone would keep the plain
    # leg's bytes; the file must be recreated empty for the LUKS leg.
    result = _run(tmp_path, template=False)
    assert result.returncode == 0, result.stderr
    initial = re.search(r"^initial nvram=(\w+)$", result.stdout, re.M).group(1)
    assert _nvram_by_leg(result.stdout) == {"plain": initial, "luks": initial}
