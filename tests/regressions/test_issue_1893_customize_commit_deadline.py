"""tunaOS#1893: ISO builds failed in a customize commit capped at 600 seconds.

What shipped: the pinned tacklebox (f3dd168) wrapped its post-customize
`podman commit` in a literal `timeout --foreground 600`, and tunaOS had no
way to change it.

What was measured: skipjack:xfce (rootless and root) and marlin:gnome/kde
(native overlay storage) CI builds finished live-customize and then ended in
`podman commit` at exactly 600.0 seconds with exit 124. The discriminator was
the size of the desktop layer, not the runner or the storage driver.

What this holds: the real adapter, run on its container path against a stub
podman, hands tacklebox `TBOX_CUSTOMIZE_COMMIT_TIMEOUT=1800` when the caller
sets nothing, and the pin is not the literal-600 revision. tacklebox ae93e9b
(tuna-os/tacklebox#300) is the first revision that reads the setting.

Falsification: behavioural for the adapter test, which fails when the default
is removed or not forwarded (checked by deleting `:-1800`); structural for the
pin test, which fails when image-versions.yaml is reverted to f3dd168.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
OLD_LITERAL_DEADLINE_PIN = "f3dd168bf15b235b554e497e7192a64a6563c4a4"


def test_tacklebox_pin_has_configurable_commit_deadline() -> None:
    downloads = yaml.safe_load((ROOT / "image-versions.yaml").read_text())["downloads"]
    pin = downloads["tacklebox"]

    assert re.fullmatch(r"[0-9a-f]{40}", pin), pin
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
        "TACKLEBOX_FROM_SOURCE": "0",
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
    run_lines = [line for line in podman_log.read_text().splitlines() if line.startswith("run ")]
    assert len(run_lines) == 1, podman_log.read_text()
    assert "--env TBOX_CUSTOMIZE_COMMIT_TIMEOUT=1800 " in run_lines[0]
