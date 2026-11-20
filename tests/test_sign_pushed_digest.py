"""Sign must sign the index the Manifest job pushed, as GHCR serves it.

``podman manifest push --digestfile`` records the digest of the manifest as
podman built it locally. The Manifest job outputs the digest it reads back
from the registry for the ``:<flavor>-candidate`` tag it pushed, so Sign
signs the bytes the gates test and Promote copies.

It must read back ``-candidate``, never ``-testing``. Only Promote writes
``-testing``, so before Promote that tag names the previous promotion. Build
Marlin run 44720498099 (tuna, 2026-11-20) read ``:tuna-testing`` back as
``sha256:f99f966b...``, the previous index. Sign signed that index again and
left the new candidate ``sha256:cc3ed762...`` unsigned (tunaOS#4831). The
annotation difference that #4474 attributed to the push comes from Promote's
``skopeo copy --all``. Promote signs the index it writes
(tests/regressions/test_issue_4831_every_promoted_index_is_signed.py).

These tests check the workflow text and run the Push Manifest step under
stub ``podman`` and ``skopeo`` binaries. The stub digests deliberately
differ.

The read-back hashes the raw index (``skopeo inspect --raw`` then
``skopeo manifest-digest``). Plain ``skopeo inspect`` first picks the
instance for the runner's platform; an index with no linux/amd64 entry has
none, so arm64-only flavors failed Manifest with "no image found in image
index for architecture amd64" (bonito:gnome-x13s, Build Bonito run
44786342148). The skopeo stub serves such an index.

Falsification: behavioural -- restore ``skopeo inspect --format
'{{.Digest}}'`` in the Push Manifest step and
test_step_outputs_the_served_digest_not_the_local_one fails, because the
stub refuses a platform-resolving inspect as skopeo does on an arm64-only
index.
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
case "$1 $2" in
"inspect --raw")
  printf '%s' '{{"manifests":[{{"platform":{{"architecture":"arm64","os":"linux"}}}}]}}'
  exit 0 ;;
"inspect "*)
  echo 'level=fatal msg="Error parsing manifest for image: choosing image instance: no image found in image index for architecture \\"amd64\\", variant \\"\\", OS \\"linux\\""' >&2
  exit 1 ;;
"manifest-digest "*)
  grep -q '"arm64"' "$2" || exit 1
  printf '%s\\n' '{SERVED_DIGEST}'
  exit 0 ;;
esac
exit 99
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
    assert "${DEFAULT_TAG}-candidate" in body, (
        "the read-back must resolve the candidate tag this step just pushed"
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
    assert "docker://ghcr.io/tuna-os/marlin:tuna-candidate" in calls, (
        f"skopeo never resolved the pushed candidate tag; calls were: {calls!r}"
    )
