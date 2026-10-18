"""Build-matrix and architecture contract for the X13s W1 profile (#3377)."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
RESOLVER = ROOT / "scripts" / "resolve-flavor.sh"
OVERLAY = ROOT / "build_scripts" / "overlay" / "x13s.sh"


def resolve(variant: str, flavor: str) -> dict[str, str]:
    proc = subprocess.run(
        [str(RESOLVER), variant, flavor],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    values = {}
    for line in proc.stdout.splitlines():
        key, raw = line.split("=", 1)
        values[key] = shlex.split(raw)[0]
    return values


def test_bonito_x13s_is_an_arm64_only_non_artifact_cell():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    bonito = next(v for v in config["variants"] if v["id"] == "bonito")
    profile = next(f for f in bonito["flavors"] if f["id"] == "gnome-x13s")

    assert profile["platforms"] == ["linux/arm64"]
    assert profile["stage"] == 3
    assert profile["build_image"] is True
    assert profile["build_iso"] is False
    assert profile["build_qcow2"] is False
    assert profile["luks_e2e"] is False


def test_bonito_x13s_routes_to_the_gnome_hardware_overlay():
    values = resolve("bonito", "gnome-x13s")

    assert values["CONTAINERFILE"] == "Containerfile.overlay"
    assert values["OVERLAY_TYPE"] == "x13s"
    assert values["DESKTOP_FLAVOR"] == "desktop"
    assert values["PARENT_FLAVOR"] == "gnome"


def test_x13s_suffix_is_not_admitted_on_another_variant():
    values = resolve("albacore", "gnome-x13s")

    assert values["CONTAINERFILE"] == "Containerfile.el10"
    assert values["OVERLAY_TYPE"] == ""
    assert values["DESKTOP_FLAVOR"] == "gnome-x13s"
    assert values["PARENT_FLAVOR"] == ""


def test_x13s_overlay_rejects_a_wrong_architecture(tmp_path: Path):
    uname = tmp_path / "uname"
    uname.write_text("#!/usr/bin/env bash\necho x86_64\n", encoding="utf-8")
    uname.chmod(0o755)
    env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}

    proc = subprocess.run(
        [str(OVERLAY)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert proc.returncode != 0
    assert "only applies to aarch64 builds" in proc.stderr
