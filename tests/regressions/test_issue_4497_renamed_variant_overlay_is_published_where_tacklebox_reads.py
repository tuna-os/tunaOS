"""tunaOS#4497: a renamed variant's overlay is published where tacklebox reads it.

Browser and strict ISO builds of flounder-sid:gnome and bonito-rawhide:gnome
failed with `live-source receipt: no verified live overlay was applied`.
tacklebox (internal/purefs/liveoverlay.go, LiveOverlayRef) looks the overlay
up as `live-overlay:<repo>-<tag>` of the image it builds, and the browser builds
the published image, `tuna-os/flounder:gnome-sid`. live-overlay.yml published
the overlay as `live-overlay:<variant>-<flavor>` (`flounder-sid-gnome`).
Measured 2026-11-11: `live-overlay:flounder-gnome-sid` was `manifest unknown`,
while `live-overlay:flounder-sid-gnome` carried the correct base binding
(sha256:13f23283..., the current amd64 manifest of flounder:gnome-sid).

The test runs the real cell selection on the real build config and the real
publish-compatible-index step against stub skopeo/podman, and requires the
pushed tag to be the one tacklebox derives from the cell's published image.

Falsification: behavioural. With the step's `live-overlay:${variant}-${flavor}`
restored, the renamed cells push `flounder-sid-gnome` / `bonito-rawhide-gnome`
and the assertion fails; skipjack-style cells push the same tag either way.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
LIVE_OVERLAY = ROOT / ".github/workflows/live-overlay.yml"
BASE = "sha256:" + "a" * 64
OVERLAY = "sha256:" + "e" * 64


def tacklebox_overlay_tag(image: str) -> str:
    """purefs.LiveOverlayRef: tuna-os/<repo>:<tag> -> live-overlay:<repo>-<tag>."""
    repo, tag = image.split(":", 1)
    return f"{repo}-{tag}"


def stub(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


def amd64_row(variant: str, flavor: str) -> dict:
    out = subprocess.run(
        ["bash", str(ROOT / "scripts/live-overlay-matrix.sh"), variant, flavor],
        text=True, capture_output=True, check=True,
    ).stdout
    rows = [r for r in json.loads(out)["include"] if r["platform"] == "linux/amd64"]
    assert len(rows) == 1, out
    return rows[0]


def pushed_tags(tmp_path: Path, row: dict) -> list[str]:
    job = yaml.safe_load(LIVE_OVERLAY.read_text())["jobs"]["publish-compatible-index"]
    step = next(s for s in job["steps"] if s.get("name") == "Publish complete current-run platform groups")
    base_index = json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [{"mediaType": "application/vnd.oci.image.manifest.v1+json",
                       "digest": BASE, "size": 1,
                       "platform": {"os": "linux", "architecture": "amd64"}}],
    })
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "podman-calls"
    stub(bin_dir, "skopeo", f"cat <<'EOF'\n{base_index}\nEOF\n")
    stub(bin_dir, "podman", f"printf '%s\\n' \"$*\" >> {calls}\n")
    stub(bin_dir, "sleep", "exit 0\n")
    work = tmp_path / "work"
    (work / "receipts").mkdir(parents=True)
    (work / "scripts/lib").mkdir(parents=True)
    (work / "scripts/lib/platform-digest.sh").write_text(
        (ROOT / "scripts/lib/platform-digest.sh").read_text())
    (work / "receipts/amd64.json").write_text(json.dumps({
        "variant": row["variant"], "flavor": row["flavor"], "platform": "linux/amd64",
        "repository": "ghcr.io/tuna-os/live-overlay", "digest": OVERLAY,
        "base_digest": BASE, "installer": "app@" + "0" * 64,
    }))
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MATRIX": json.dumps({"include": [row]}),
        "PUBLISH_DEST": "ghcr.io/tuna-os",
    }
    proc = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=work, env=env,
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    return [c.split()[-1].removeprefix("docker://ghcr.io/tuna-os/live-overlay:")
            for c in calls.read_text().splitlines() if c.startswith("manifest push")]


@pytest.mark.parametrize("variant,image", [
    ("flounder-sid", "flounder:gnome-sid"),
    ("bonito-rawhide", "bonito:gnome-rawhide"),
    ("skipjack", "skipjack:gnome"),
])
def test_the_overlay_is_pushed_at_the_tag_tacklebox_looks_up(tmp_path, variant, image):
    row = amd64_row(variant, "gnome")
    assert row["image"] == image
    assert pushed_tags(tmp_path, row) == [tacklebox_overlay_tag(image)]
