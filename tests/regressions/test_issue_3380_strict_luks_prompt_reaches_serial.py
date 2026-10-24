"""#3380: the strict LUKS installed boots must put the cryptsetup prompt on serial.

Run 40074592548 (job 120829636286) passed the LUKS GUI install, then the
detached cold boot sat 15 minutes and failed with "passphrase prompt never
appeared". The GUI-installed BLS entry has `rhgb quiet` and no serial console,
so the prompt went to Plymouth. The strict harness now has luks-first-boot.py
type serial/text-prompt kargs into GRUB for each LUKS boot. It does not edit
the installed disk.

The GRUB key sequence itself is covered in tests/test_luks_first_boot.py.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts/iso-e2e.sh").read_text()


def _function(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SCRIPT, re.M | re.S)
    assert match, name
    return match.group(0)


def test_append_set_matches_the_cli_luks_gate_text_prompt_kargs():
    value = re.search(r'^STRICT_LUKS_GRUB_APPEND="([^"]+)"$', SCRIPT, re.M).group(1)
    assert value.split() == ["console=ttyS0,115200n8", "rd.plymouth=0", "plymouth.enable=0"]
    cli = _function("append_installed_serial_kargs")
    for karg in value.split():
        assert karg in cli


def test_both_luks_boots_pass_the_grub_append_to_luks_first_boot():
    body = _function("verify_strict_installed_boot")
    calls = re.findall(
        r'TUNAOS_LUKS_GRUB_APPEND="\$STRICT_LUKS_GRUB_APPEND" \\\n\s*python3 "\$\{SCRIPT_DIR\}/luks-first-boot.py"',
        body,
    )
    assert len(calls) == 2, "cold and warm LUKS boots"
    assert body.count("luks-first-boot.py") == 2


def test_strict_path_never_rewrites_the_installed_entries():
    for name in ("run_strict_gui_install", "verify_strict_installed_boot", "run_strict_offline_gui"):
        # Calls only; the comment that explains the choice names the function.
        assert not re.search(r"(?m)^\s*append_installed_serial_kargs\b", _function(name))


def test_the_per_boot_edit_is_recorded_in_strict_evidence():
    body = _function("verify_strict_installed_boot")
    assert 'strict_offline_evidence "installed_${mode}_grub_append=' in body
    assert "disk_modified=no" in body
