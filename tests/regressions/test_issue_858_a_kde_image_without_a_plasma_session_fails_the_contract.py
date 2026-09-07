"""tunaOS#858: marlin:kde built, promoted, and shipped no desktop.

The image had plasmashell packages but no `/usr/share/wayland-sessions/`
entry at all, so SDDM offered nothing to log into. "Green" at the time meant
the image built and promoted, which is the weakest claim the pipeline can
make — the incident is the reason `.github/green-criteria.yml` exists and
the reason its `desktop` criterion is blocking.

What must not recur: a KDE image with no Plasma session file passing the
desktop contract. The contract (build_scripts/checks/verify-desktop-experience.sh)
requires the session glob in its `kde)` branch; these tests run the real
`require_glob` from that script against a filesystem with no session file
and hold that it fails, loudly, with the path named — and that the
hummingbird bootstrap waiver, the one legitimate way through, is not in
effect for a stable variant.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "build_scripts" / "checks" / "verify-desktop-experience.sh"
SESSION_GLOB = "/usr/share/wayland-sessions/*plasma*.desktop"


def _function_source(name: str) -> str:
    """Extract one shell function body from the contract script verbatim."""
    src = CHECK.read_text(encoding="utf-8")
    # The helpers close with either `}` or `}; }` (one-liner with an inner
    # block); match to the end of that line so the body is a complete unit.
    m = re.search(rf"^{name}\(\) \{{.*?^\}}(?:; \}})?[ \t]*$", src, re.S | re.M)
    assert m, f"{name} not found in {CHECK}"
    return m.group(0)


def _run_require_glob(pattern: str, env_extra: str = "") -> subprocess.CompletedProcess:
    script = "\n".join([
        "set -uo pipefail",
        "TUNAOS_CONTRACT_WAIVED=0",
        "waive() { TUNAOS_CONTRACT_WAIVED=$((TUNAOS_CONTRACT_WAIVED + 1)); }",
        env_extra,
        _function_source("require_glob"),
        f"require_glob '{pattern}'",
        "echo reached-the-end",
    ])
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_the_kde_contract_requires_a_plasma_wayland_session():
    """The line that would have caught #858. Anchored on the kde branch, not
    the whole file, so moving it under a different desktop does not pass."""
    src = CHECK.read_text(encoding="utf-8")
    kde = src[src.index("\nkde)"):]
    kde = kde[: re.search(r"\n\t?;;", kde).start()]
    assert f"require_glob '{SESSION_GLOB}'" in kde, kde


def test_a_missing_session_file_fails_the_contract(tmp_path):
    p = _run_require_glob(str(tmp_path / "wayland-sessions" / "*plasma*.desktop"))
    assert p.returncode == 1, p.stdout + p.stderr
    assert "reached-the-end" not in p.stdout, "require_glob returned instead of exiting"
    assert "missing required path" in p.stderr, p.stderr
    assert "plasma" in p.stderr, "the failure must name what is missing"


def test_a_present_session_file_passes(tmp_path):
    sessions = tmp_path / "wayland-sessions"
    sessions.mkdir()
    (sessions / "plasma.desktop").write_text("[Desktop Entry]\n")
    p = _run_require_glob(str(sessions / "*plasma*.desktop"))
    assert p.returncode == 0, p.stderr
    assert "reached-the-end" in p.stdout


def test_the_bootstrap_waiver_does_not_apply_to_a_stable_variant(tmp_path):
    """IS_HUMMINGBIRD is the only exemption, and it is per-variant. With it
    unset (marlin, every stable variant) the old failure mode is fatal."""
    p = _run_require_glob(str(tmp_path / "*plasma*.desktop"), "unset IS_HUMMINGBIRD")
    assert p.returncode == 1
    waived = _run_require_glob(str(tmp_path / "*plasma*.desktop"), "IS_HUMMINGBIRD=true")
    assert waived.returncode == 0, "the hummingbird waiver is deliberate and must still work"
    assert "reached-the-end" in waived.stdout
