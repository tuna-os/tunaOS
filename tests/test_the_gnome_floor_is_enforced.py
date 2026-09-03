"""Nothing below GNOME 50 ships. The desktop contract enforces it.

Maintainer directive, 2026-09-03: tunaOS is moving off GNOME 49 -- nothing
below 50 ships as a GNOME image, and 51 is the target as it releases (51.0 is
due 2026-09-12). Measured the same day from the published `.packages`
artifacts (linux-amd64):

    yellowfin  gnome-shell 49.5-13.el10.alma.12   EL 10.2's own GNOME
    albacore   gnome-shell 49.4-8.el10_2.alma.1   EL 10.2's own GNOME
    skipjack   gnome-shell 49.5-13.el10            EL 10.2's own GNOME
    guppy      gnome-base/gnome-shell-49.7         ::gentoo tops out at 49.9
    bonito     50.4    sailfin 50.4    marlin 50.4    wahoo 51~beta

Three of those 49s were being called green under a manifest that declared
GNOME 50. The contract had no notion of a version at all: `require_command
gnome-shell` is satisfied by any gnome-shell. This test holds the floor in
three places at once:

  * the manifest states the policy (`minimum_version: 50`),
  * the contract script carries the same number as a constant (it runs inside
    the image with nothing but itself mounted, so it cannot read the manifest),
  * `require_gnome_at_least` fails a 49, passes a 50 and a 51, reads the
    version from the binary first and the package manager second, and refuses
    to guess when neither answers.

The helper is exercised by extracting it verbatim from the script and running
it against a fake `gnome-shell` on PATH, the way the #858 regression exercises
`require_glob`.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "build_scripts" / "checks" / "verify-desktop-experience.sh"
MANIFEST = ROOT / "manifests" / "desktops" / "gnome.yaml"


def _function_source(name: str) -> str:
    src = CHECK.read_text(encoding="utf-8")
    m = re.search(rf"^{name}\(\) \{{.*?^\}}(?:; \}})?[ \t]*$", src, re.S | re.M)
    assert m, f"{name} not found in {CHECK}"
    return m.group(0)


def _script_floor() -> int:
    m = re.search(r"^GNOME_MINIMUM_MAJOR=(\d+)$", CHECK.read_text(), re.M)
    assert m, "the contract script declares no GNOME_MINIMUM_MAJOR"
    return int(m.group(1))


def _manifest_floor() -> int:
    doc = yaml.safe_load(MANIFEST.read_text())
    assert "minimum_version" in doc, "gnome.yaml declares no minimum_version"
    return int(doc["minimum_version"])


def _fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run_floor(tmp_path: Path, floor: int, *, fakes: dict[str, str], env: dict | None = None):
    """Run require_gnome_at_least with only the given fake commands on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    # The helpers shell out to grep/head/printf; keep the real ones reachable
    # through explicit symlinks so a fake PATH still has a working toolbox.
    for tool in ("grep", "head", "bash", "env"):
        real = subprocess.run(
            ["bash", "-c", f"command -v {tool}"], capture_output=True, text=True
        ).stdout.strip()
        if real and not (bin_dir / tool).exists():
            os.symlink(real, bin_dir / tool)
    for name, body in fakes.items():
        _fake(bin_dir, name, body)
    script = "\n".join(
        [
            "set -uo pipefail",
            "waive() { echo WAIVED; }",
            _function_source("gnome_shell_major"),
            _function_source("require_gnome_at_least"),
            f"require_gnome_at_least {floor}",
        ]
    )
    run_env = {"PATH": str(bin_dir), **(env or {})}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=run_env)


# ── The policy and the enforcement agree ─────────────────────────────────────


def test_the_floor_is_fifty():
    assert _manifest_floor() == 50


def test_the_script_carries_the_same_floor_as_the_manifest():
    assert _script_floor() == _manifest_floor(), (
        "the contract enforces a different GNOME floor than gnome.yaml declares; "
        "change both or neither"
    )


def test_the_gnome_branch_calls_the_floor_check():
    src = CHECK.read_text()
    branch = src[src.index('case "$desktop" in\ngnome)') :]
    branch = branch[: branch.index(";;")]
    assert 'require_gnome_at_least "$GNOME_MINIMUM_MAJOR"' in branch, (
        "the gnome) branch does not enforce the floor"
    )


# ── The check itself ─────────────────────────────────────────────────────────


def test_a_gnome_49_image_fails_naming_the_floor(tmp_path):
    r = _run_floor(tmp_path, 50, fakes={"gnome-shell": 'echo "GNOME Shell 49.5"'})
    assert r.returncode != 0
    assert "GNOME 49 is below the floor" in r.stderr
    assert "nothing below GNOME 50 ships" in r.stderr


def test_a_gnome_50_image_passes(tmp_path):
    r = _run_floor(tmp_path, 50, fakes={"gnome-shell": 'echo "GNOME Shell 50.4"'})
    assert r.returncode == 0, r.stderr
    assert "GNOME 50 meets the floor of 50" in r.stdout


def test_a_gnome_51_release_candidate_passes(tmp_path):
    """wahoo reports `GNOME Shell 51.rc` (and 51.beta before it): the major is 51."""
    r = _run_floor(tmp_path, 50, fakes={"gnome-shell": 'echo "GNOME Shell 51.rc"'})
    assert r.returncode == 0, r.stderr
    assert "GNOME 51 meets the floor" in r.stdout


def test_the_package_manager_answers_when_the_binary_cannot(tmp_path):
    """A gnome-shell that cannot even print its version (no display, missing
    library in a stripped container) must not turn into a false pass or a
    false fail: rpm knows the version."""
    r = _run_floor(
        tmp_path,
        50,
        fakes={
            "gnome-shell": "exit 1",
            "rpm": 'echo "49.5"',
        },
    )
    assert r.returncode != 0
    assert "GNOME 49 is below the floor" in r.stderr


def test_no_answer_at_all_is_a_failure_not_a_pass(tmp_path):
    r = _run_floor(tmp_path, 50, fakes={"gnome-shell": "exit 1"})
    assert r.returncode != 0
    assert "cannot determine the installed GNOME version" in r.stderr


def test_the_hummingbird_bootstrap_waiver_still_applies(tmp_path):
    """Hummingbird's contract is waived line by line while its repos are
    incomplete; the floor follows the same rule so it does not become the one
    check that hard-fails a bootstrap the others let through."""
    r = _run_floor(
        tmp_path,
        50,
        fakes={"gnome-shell": 'echo "GNOME Shell 49.5"'},
        env={"IS_HUMMINGBIRD": "true"},
    )
    assert r.returncode == 0, r.stderr
    assert "WAIVED" in r.stdout
