"""GNOME 51 is the minimum for every TunaOS GNOME image.

The authoritative TOML policy, generated adapter, and in-image constant must
agree. Exercise the installed-version check with fake package tools; neither
GNOME 50 nor an unknown version can pass through a bootstrap waiver.
"""

from __future__ import annotations

from functools import cache
import importlib.util
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
@cache
def _primary_config():
    spec = importlib.util.spec_from_file_location(
        "gnome_floor_tunaos_config", ROOT / "scripts/lib/tunaos_config.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/lib/tunaos_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load(ROOT / "tunaos.toml")


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


def test_the_floor_is_fifty_one():
    primary = _primary_config()
    assert primary["desktops"]["gnome"]["minimum_version"] == 51
    assert _manifest_floor() == 51


def test_the_script_and_generated_manifest_match_the_primary_config():
    primary_floor = _primary_config()["desktops"]["gnome"]["minimum_version"]
    assert _script_floor() == _manifest_floor() == primary_floor, (
        "the GNOME floor drifted from authoritative tunaos.toml; regenerate "
        "the desktop manifest and update the image contract together"
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
    r = _run_floor(tmp_path, 51, fakes={"gnome-shell": 'echo "GNOME Shell 49.5"'})
    assert r.returncode != 0
    assert "GNOME 49 is below the floor" in r.stderr
    assert "nothing below GNOME 51 ships" in r.stderr


def test_a_gnome_50_image_fails(tmp_path):
    r = _run_floor(tmp_path, 51, fakes={"gnome-shell": 'echo "GNOME Shell 50.4"'})
    assert r.returncode != 0
    assert "GNOME 50 is below the floor" in r.stderr


def test_a_gnome_51_release_candidate_passes(tmp_path):
    """wahoo reports `GNOME Shell 51.rc` (and 51.beta before it): the major is 51."""
    r = _run_floor(tmp_path, 51, fakes={"gnome-shell": 'echo "GNOME Shell 51.rc"'})
    assert r.returncode == 0, r.stderr
    assert "GNOME 51 meets the floor" in r.stdout


def test_the_package_manager_answers_when_the_binary_cannot(tmp_path):
    """A gnome-shell that cannot even print its version (no display, missing
    library in a stripped container) must not turn into a false pass or a
    false fail: rpm knows the version."""
    r = _run_floor(
        tmp_path,
        51,
        fakes={
            "gnome-shell": "exit 1",
            "rpm": 'echo "49.5"',
        },
    )
    assert r.returncode != 0
    assert "GNOME 49 is below the floor" in r.stderr


def test_no_answer_at_all_is_a_failure_not_a_pass(tmp_path):
    r = _run_floor(tmp_path, 51, fakes={"gnome-shell": "exit 1"})
    assert r.returncode != 0
    assert "cannot determine the installed GNOME version" in r.stderr


@pytest.mark.parametrize("version", ["49.5", "50.4", None])
def test_hummingbird_cannot_waive_the_gnome_floor(tmp_path, version):
    fake = f'echo "GNOME Shell {version}"' if version else "exit 1"
    r = _run_floor(
        tmp_path,
        51,
        fakes={"gnome-shell": fake},
        env={"IS_HUMMINGBIRD": "true"},
    )
    assert r.returncode != 0
    assert "WAIVED" not in r.stdout


def test_a_gnome_51_stable_image_passes(tmp_path):
    r = _run_floor(tmp_path, 51, fakes={"gnome-shell": 'echo "GNOME Shell 51.0"'})
    assert r.returncode == 0, r.stderr
