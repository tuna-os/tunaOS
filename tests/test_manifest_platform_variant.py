"""The published index must carry OCI platform fields, not the raw platform string.

`linux/amd64/v2` is architecture amd64 with variant v2. The Populate Manifest
step used to pass `--arch "${platform#linux/}"`, publishing
`{"architecture": "amd64/v2"}`, which no spec-following client (tacklebox's
exact os/arch/variant match, containers/image) can resolve.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/reusable-build-image.yml").read_text())
STEP = next(step for step in WORKFLOW["jobs"]["manifest"]["steps"] if step.get("name") == "Populate Manifest")

DIGESTS = {
    "linux-amd64": "sha256:" + "1" * 64,
    "linux-amd64-v2": "sha256:" + "2" * 64,
    "linux-arm64": "sha256:" + "3" * 64,
}


def test_each_platform_is_added_with_os_arch_and_only_a_real_variant(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    podman = bindir / "podman"
    podman.write_text('#!/bin/bash\n[[ "$1 $2" == "manifest add" ]] || exit 0\nprintf "%s\\n" "$*" >> "$PODMAN_LOG"\n')
    podman.chmod(0o755)
    log = tmp_path / "podman.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "PODMAN_LOG": str(log),
        "MANIFEST": "ghcr.io/tuna-os/yellowfin:gnome",
        "IMAGE_REGISTRY": "ghcr.io/tuna-os",
        "IMAGE_NAME": "yellowfin",
        "DIGESTS_JSON": json.dumps(DIGESTS),
        "LABELS": "",
        "PLATFORMS": "linux/amd64,linux/amd64/v2,linux/arm64",
    }
    proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", STEP["run"]],
                          cwd=tmp_path, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    added = {line.split()[3].rsplit("@", 1)[1]: line.split()[4:] for line in log.read_text().splitlines()}
    assert added == {
        DIGESTS["linux-amd64"]: ["--os", "linux", "--arch", "amd64"],
        DIGESTS["linux-amd64-v2"]: ["--os", "linux", "--arch", "amd64", "--variant", "v2"],
        DIGESTS["linux-arm64"]: ["--os", "linux", "--arch", "arm64"],
    }
