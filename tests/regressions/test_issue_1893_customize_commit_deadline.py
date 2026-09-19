"""tunaOS#1893: ISO builds failed after a 600.0-second customize commit.

The skipjack:xfce and marlin:{gnome,kde} CI logs measured `podman commit`
ending at exactly 600 seconds even with native overlay storage. This test holds
the TunaOS adapter's longer deadline and verifies that the container execution
path actually receives it.

Falsification: behavioural invocation of the real adapter fails if the default
is absent or is not forwarded; the structural pin check fails on the old
Tacklebox revision that had a literal 600-second deadline.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
OLD_LITERAL_DEADLINE_PIN = "f3dd168bf15b235b554e497e7192a64a6563c4a4"


def test_tacklebox_pin_has_configurable_commit_deadline() -> None:
    downloads = yaml.safe_load((ROOT / "image-versions.yaml").read_text())["downloads"]
    pin = downloads["tacklebox"]

    assert len(pin) == 40
    assert pin != OLD_LITERAL_DEADLINE_PIN


def test_container_tacklebox_receives_longer_commit_deadline(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    podman_log = tmp_path / "podman.log"
    podman = bin_dir / "podman"
    podman.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PODMAN_LOG"\n')
    podman.chmod(0o755)

    recipe = tmp_path / "recipe.json"
    recipe.write_text("{}\n")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    iso = output_dir / "test.iso"

    script = f"""
set -euo pipefail
source {ROOT / 'scripts/lib/tacklebox.sh'}
tunaos_run_tacklebox {recipe} {output_dir} {iso}
"""
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PODMAN_LOG": str(podman_log),
        "TUNAOS_TACKLEBOX_TIMEOUT_SECONDS": "30",
    }
    env.pop("TBOX_CUSTOMIZE_COMMIT_TIMEOUT", None)
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    invocation = podman_log.read_text()
    assert "--env TBOX_CUSTOMIZE_COMMIT_TIMEOUT=1800" in invocation
