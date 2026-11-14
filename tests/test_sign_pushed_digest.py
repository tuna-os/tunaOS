"""Sign must sign the index digest GHCR serves, not the local manifest digest.

``podman manifest push --digestfile`` records the digest of the manifest as
podman built it locally. The push runs with ``--force-compression``, and the
transport adds a per-manifest
``io.github.containers.compression.zstd: true`` annotation on upload, so the
bytes GHCR serves under ``:<flavor>-testing`` hash differently.

Measured live against Build Marlin run 42600699394 (tuna, 2026-11-09):
Sign signed index ``sha256:412f...`` (the digestfile value; its signatures
verify), while ``marlin:tuna-testing`` and the promoted ``marlin:tuna``
resolve to ``sha256:2002ae...``. The two raw indexes differ only by that one
annotation block; the single platform manifest inside is byte-identical and
its own signature verifies. Promote copies the testing tag, so no published
index digest ever carries a signature, and ``cosign verify`` on anything a
user can pull fails with ``no signatures found``.

The manifest job must therefore output the digest read back from the
registry after the push. These tests pin that: contract checks on the
workflow text, plus a behavioural run of the Push Manifest step itself
under stub ``podman``/``skopeo`` binaries whose digests deliberately
disagree.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"

LOCAL_DIGEST = "sha256:" + "1" * 64
SERVED_DIGEST = "sha256:" + "2" * 64

STUB_PODMAN = f"""#!/bin/sh
echo "podman $*" >> "$STUB_DIR/calls"
if [ "$1" = "manifest" ] && [ "$2" = "push" ]; then
  printf '%s' '{LOCAL_DIGEST}' > /tmp/digestfile
  exit 0
fi
exit 99
"""

STUB_SKOPEO = f"""#!/bin/sh
echo "skopeo $*" >> "$STUB_DIR/calls"
printf '%s\\n' '{SERVED_DIGEST}'
exit 0
"""


@pytest.fixture(scope="module")
def manifest_job():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["manifest"]


def _step(job, name):
    return next(s for s in job["steps"] if s.get("name") == name)


def test_push_manifest_reads_the_served_digest_back(manifest_job):
    body = _step(manifest_job, "Push Manifest")["run"]
    assert "skopeo inspect" in body, (
        "the Push Manifest step never reads the pushed tag back from the "
        "registry, so outputs.digest is the local (unsigned) digest again"
    )
    assert "${DEFAULT_TAG}-testing" in body, (
        "the read-back must resolve the testing tag this step just pushed"
    )


def test_manifest_job_installs_skopeo(manifest_job):
    body = _step(manifest_job, "Install dependencies")["run"]
    install_line = next(
        line for line in body.splitlines() if line.strip().startswith("apk_install ")
    )
    assert "skopeo" in install_line, (
        "the Manifest job cannot read the served digest back without skopeo"
    )


def test_outputs_digest_still_comes_from_push_manifest(manifest_job):
    assert manifest_job["outputs"]["digest"] == "${{ steps.push_manifest.outputs.DIGEST }}"


def test_step_outputs_the_served_digest_not_the_local_one(manifest_job, tmp_path):
    body = _step(manifest_job, "Push Manifest")["run"]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, stub in (("podman", STUB_PODMAN), ("skopeo", STUB_SKOPEO)):
        (bindir / name).write_text(stub)
        (bindir / name).chmod(0o755)
    output_file = tmp_path / "github_output"
    env = dict(os.environ)
    env.update(
        PATH=f"{bindir}:{env['PATH']}",
        STUB_DIR=str(tmp_path),
        MANIFEST="testmanifest",
        TAGS="tuna",
        IMAGE_REGISTRY="ghcr.io/tuna-os",
        IMAGE_NAME="marlin",
        DEFAULT_TAG="tuna",
        GITHUB_OUTPUT=str(output_file),
    )
    digestfile = Path("/tmp/digestfile")
    digestfile.unlink(missing_ok=True)
    try:
        proc = subprocess.run(
            ["bash", "-e", "-c", body],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
    finally:
        digestfile.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    outputs = output_file.read_text(encoding="utf-8")
    assert f"DIGEST={SERVED_DIGEST}" in outputs, (
        f"the step output the local digestfile digest instead of the served "
        f"one; GITHUB_OUTPUT was: {outputs!r}"
    )
    calls = (tmp_path / "calls").read_text(encoding="utf-8")
    assert "docker://ghcr.io/tuna-os/marlin:tuna-testing" in calls, (
        f"skopeo never resolved the pushed testing tag; calls were: {calls!r}"
    )
