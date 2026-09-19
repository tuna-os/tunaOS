"""tunaOS#979: failed installed LUKS boots must keep the systemd journal.

The serial console survives failures that also take down D-Bus, logind, and
networking. Both LUKS install paths must therefore add journald's console
forwarding karg, rather than leaving the useful unit error behind unreachable
SSH.

Falsification: structural — removing the forwarding karg from either the
fisherman BLS patch or the generic bootc install makes this test fail.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts" / "iso-e2e.sh").read_text(encoding="utf-8")
KARG = "systemd.journald.forward_to_console=1"


def _between(start: str, end: str) -> str:
    return SCRIPT.split(start, 1)[1].split(end, 1)[0]


def test_fisherman_installs_forward_the_journal_to_the_captured_serial_console():
    bls_patch = _between(
        "append_installed_serial_kargs() {", "# Wait up to $2 seconds"
    )
    assert KARG in bls_patch
    # Each karg is checked separately. An existing console=ttyS0 must not stop
    # a later repair from adding journal forwarding to an older BLS entry.
    assert "for karg in" in bls_patch
    assert 'grep -Fqw -- "$karg"' in bls_patch


def test_generic_bootc_installs_forward_the_journal_too():
    generic_install = _between("run_install_generic() {", "run_install() {")
    assert f"--karg {KARG}" in generic_install
