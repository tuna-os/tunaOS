"""tunaOS#2513: hummingbird:COSMIC promoted without a usable session.

Hummingbird's repositories are still bootstrapping, so most desktop contract
failures are waived and the boot Gate supplies the final safety net. COSMIC's
boot Gate cannot currently make that assertion. Applying both exceptions let
an image with cosmic-comp but no cosmic-session, greetd, or greeter reach the
published tag.

Keep the bootstrap waiver for the other desktops, but never apply it to
COSMIC's minimum session contract.

Falsification: behavioural -- drop the `desktop != cosmic` guard from any
waiver branch of verify-desktop-experience.sh and the missing-session run for
COSMIC passes again, which fails this test as the unfixed tree did.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "build_scripts" / "checks" / "verify-desktop-experience.sh"


def _function_source(name: str) -> str:
    src = CHECK.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{.*?^\}}(?:; \}})?[ \t]*$", src, re.S | re.M)
    assert match, f"{name} not found in {CHECK}"
    return match.group(0)


def _run_missing_session(desktop: str, pattern: str) -> subprocess.CompletedProcess:
    script = "\n".join(
        [
            "set -uo pipefail",
            f"desktop={desktop}",
            "IS_HUMMINGBIRD=true",
            "TUNAOS_CONTRACT_WAIVED=0",
            "waive() { TUNAOS_CONTRACT_WAIVED=$((TUNAOS_CONTRACT_WAIVED + 1)); }",
            _function_source("require_glob"),
            f"require_glob '{pattern}'",
            "echo reached-the-end waived=$TUNAOS_CONTRACT_WAIVED",
        ]
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_hummingbird_cosmic_without_a_session_fails_the_contract(tmp_path):
    result = _run_missing_session(
        "cosmic", str(tmp_path / "wayland-sessions" / "*cosmic*.desktop")
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "reached-the-end" not in result.stdout
    assert "missing required path" in result.stderr
    assert "cosmic" in result.stderr


def test_other_hummingbird_desktops_keep_the_bootstrap_waiver(tmp_path):
    result = _run_missing_session(
        "gnome", str(tmp_path / "wayland-sessions" / "*gnome*.desktop")
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "reached-the-end waived=1" in result.stdout
