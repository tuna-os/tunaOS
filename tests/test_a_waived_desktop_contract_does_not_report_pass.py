"""A waived desktop contract must not report itself as passed.

hummingbird is exempted from every require_* in
build_scripts/checks/verify-desktop-experience.sh so it can bootstrap against
incomplete repos. That exemption is deliberate and these tests do not
challenge it. What they hold is the REPORT.

On tunaOS run 32813037866 the check printed, in order:

    missing required command: gnome-shell
    missing unit: none of [gdm gdm3] exist
    missing required command: nautilus
    ... ten of them ...
    desktop experience contract passed: gnome (projectbluefin/bluefin-lts)

The image had 410 packages: gnome-backgrounds and gnome-user-docs, no
gnome-shell, no gdm, no mutter, no gtk4. It was pushed to GHCR, and the first
thing to notice was the boot gate failing 15 minutes later on a marker that
could never be emitted. The packages were dropped upstream
(tunaos-packages#519); the reason it went unnoticed for weeks is this line.

The report block is tested by RUNNING it, because "passed" was printed by
code that had already seen the failures.
"""

import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "build_scripts" / "checks" / "verify-desktop-experience.sh"


def _run_report(tmp_path, waived):
    """Execute the real report block with a given waiver count."""
    src = CHECK.read_text()
    start = src.index("\tinstall -d /usr/share/tunaos/experience-contracts")
    end = src.index("\nfi", start)
    block = src[start:end]

    contracts = tmp_path / "contracts"
    block = block.replace("/usr/share/tunaos/experience-contracts", str(contracts))

    script = tmp_path / "report.sh"
    script.write_text(
        textwrap.dedent(f"""\
        set -euo pipefail
        desktop=gnome
        experience=projectbluefin/bluefin-lts
        TUNAOS_CONTRACT_WAIVED={waived}
        """)
        + block
        + "\n"
    )
    p = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    written = (contracts / "gnome").read_text()
    return p.stdout + p.stderr, written


def test_a_clean_contract_still_reports_passed(tmp_path):
    out, written = _run_report(tmp_path, 0)
    assert "contract passed" in out, out
    assert "validated_at_build=true" in written, written
    assert "WAIVED" not in out, out


def test_a_waived_contract_never_says_passed(tmp_path):
    out, written = _run_report(tmp_path, 10)
    assert "contract passed" not in out, (
        "ten unmet requirements were reported as a pass — the exact defect "
        f"that shipped a GNOME image with no GNOME:\n{out}"
    )
    assert "WAIVED" in out, out
    assert "10 requirement(s) unmet" in out, out


def test_a_waived_contract_is_recorded_as_unverified_on_the_image(tmp_path):
    """Downstream scoring reads this file; it must not claim verification."""
    _, written = _run_report(tmp_path, 10)
    assert "validated_at_build=false" in written, written
    assert "validated_at_build=true" not in written, written
    assert "waived_requirements=10" in written, written


def test_a_waived_contract_emits_a_greppable_marker(tmp_path):
    out, _ = _run_report(tmp_path, 3)
    assert "TUNAOS_DESKTOP_CONTRACT_WAIVED desktop=gnome missing=3" in out, out


def test_every_hummingbird_exemption_counts_what_it_waives():
    """An exemption that doesn't count is invisible again."""
    src = CHECK.read_text()
    exemptions = src.count('IS_HUMMINGBIRD:-false}" == "true" ]]; then')
    counted = src.count('== "true" ]]; then waive; return 0; fi')
    assert exemptions > 0, "the exemption shape changed; this test is stale"
    assert counted == exemptions, (
        f"{exemptions} require_* exemptions but only {counted} call waive() — "
        "an uncounted exemption can still report a pass over a broken image"
    )
