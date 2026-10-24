"""#3380: preserve GRUB diagnostics without qualifying an altered boot.

The standalone helper's opt-in GRUB editor remains tested separately. Strict
qualification must instead observe the unchanged installed boot path.

Falsification: a nonempty GRUB override must exit 2 before guest work and
remove a stale aggregate receipt; either strict call retaining the override
fails the source boundary assertion.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts/iso-e2e.sh").read_text()


def _function(name):
    if name == "verify_strict_installed_boot":
        return SCRIPT[SCRIPT.index(name + "() {") : SCRIPT.index("emit_qualification_evidence() {")]
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SCRIPT, re.MULTILINE | re.DOTALL)
    assert match, name
    return match.group(0)


def test_standalone_diagnostic_grub_editor_is_preserved():
    helper = (ROOT / "scripts/luks-first-boot.py").read_text()
    assert "def edit_grub_entry(" in helper
    assert "TUNAOS_LUKS_GRUB_APPEND" in helper
    assert "grub_edited = not grub_append" in helper


def test_strict_cold_and_warm_explicitly_disable_grub_input():
    body = _function("verify_strict_installed_boot")
    assert body.count('TUNAOS_LUKS_GRUB_APPEND=""') == 2
    assert 'TUNAOS_LUKS_GRUB_APPEND="$STRICT_LUKS_GRUB_APPEND"' not in body
    assert "installed_${mode}_grub_append=" not in body
    assert not re.search(r"(?m)^STRICT_LUKS_GRUB_APPEND=", SCRIPT)
    assert not re.search(r"(?m)^\s*append_installed_serial_kargs\b", body)


@pytest.mark.parametrize("variable", ["TUNAOS_LUKS_GRUB_APPEND", "STRICT_LUKS_GRUB_APPEND"])
def test_strict_override_refused_before_guest_or_receipt(tmp_path, variable):
    receipt = tmp_path / "qualification.json"
    receipt.write_text("stale")
    shell = _function("run_strict_offline_gui") + "\nrun_strict_offline_gui\n"
    result = subprocess.run(
        ["bash", "-euc", shell],
        capture_output=True,
        check=False,
        timeout=5,
        env={**os.environ, variable: "console=ttyS0", "QUAL_EVIDENCE_JSON": str(receipt)},
    )
    assert result.returncode == 2
    assert not receipt.exists()
    assert b"refuses per-boot GRUB argument overrides" in result.stderr
