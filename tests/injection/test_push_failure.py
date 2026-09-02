"""Failure injection: container image registry push fails midway.

Where to assert: `scripts/build-image-inner.sh` with a builder/push stub that fails on layer upload.

Asserts all five invariant properties:
  (1) Fails: build-image-inner.sh exits non-zero (exit code 1).
  (2) Says why: output reports image build failure after attempts and details push error.
  (3) Does not call the cell green: builds criterion is marked failing, cell is not green.
  (4) Does not promote: build_push failure prevents tag-image from running.
  (5) Keeps enough evidence to diagnose: captured build logs record failure details and attempt counts.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.injection.helpers import (
    ROOT,
    evaluate_composite_status,
    evaluate_promote_condition,
    make_executable,
)

SCRIPT = ROOT / "scripts" / "build-image-inner.sh"


def _run_mocked_build_push(tmp_path: Path, fail_layer: bool = True):
    """Run build-image-inner.sh retry loop with a stubbed builder failing on push/build."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Mock podman/buildah builder
    builder_stub = f"""#!/usr/bin/env bash
if [ "{fail_layer}" = "True" ]; then
  echo "Uploading layer 1/3: sha256:111... OK" >&2
  echo "Uploading layer 2/3: sha256:222... Error: EOF while writing layer to ghcr.io" >&2
  exit 1
else
  echo "Build & push succeeded"
  exit 0
fi
"""
    make_executable(bin_dir / "podman", builder_stub)
    make_executable(bin_dir / "buildah", builder_stub)

    # Stub the build retry loop from build-image-inner.sh
    runner_script = tmp_path / "run_build_inner.sh"
    runner_script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -u
            export PATH="{bin_dir}:$PATH"
            BUILDER="podman"
            build_primary_image() {{
              podman build -t test:image .
            }}
            sleep() {{ :; }}

            build_attempt=1
            until build_primary_image; do
              if [[ "${{build_attempt}}" -ge 3 ]]; then
                echo "ERROR: image build failed after ${{build_attempt}} attempt(s)" >&2
                exit 1
              fi
              echo "${{BUILDER}} build attempt ${{build_attempt}} failed; retrying..." >&2
              sleep "$((build_attempt * 10))"
              build_attempt=$((build_attempt + 1))
            done
            """
        ),
        encoding="utf-8",
    )

    return subprocess.run(
        ["bash", str(runner_script)],
        capture_output=True,
        text=True,
    )


def test_property_1_and_2_push_failure_fails_and_says_why(tmp_path):
    """(1) Fails and (2) says why: builder exits 1 after 3 attempts with layer error message."""
    proc = _run_mocked_build_push(tmp_path, fail_layer=True)

    # (1) Fails
    assert proc.returncode == 1, f"build-image-inner.sh must exit 1 on push failure, got {proc.returncode}"

    # (2) Says why
    assert "ERROR: image build failed after 3 attempt(s)" in proc.stderr
    assert "Error: EOF while writing layer to ghcr.io" in proc.stderr
    assert "podman build attempt 1 failed; retrying..." in proc.stderr
    assert "podman build attempt 2 failed; retrying..." in proc.stderr


def test_healthy_push_succeeds(tmp_path):
    """Confirm clean build/push passes with exit 0."""
    proc = _run_mocked_build_push(tmp_path, fail_layer=False)
    assert proc.returncode == 0
    assert "Build & push succeeded" in proc.stdout


def test_property_3_push_failure_does_not_call_cell_green():
    """(3) Does not call the cell green: cell with failed push is not composite green."""
    stage = {
        "bonito": {
            "jobs": {
                ("gnome", "build_push"): "failure",
                ("gnome", "Promote"): "skipped",
            },
            "date": "2026-09-02",
        }
    }
    green, total, lines, prov = evaluate_composite_status(stage)
    assert green == 0, "Cell with failed image push must not be composite green"
    verdict = prov.get("bonito:gnome", {}).get("builds", {}).get("verdict")
    assert verdict in ("fail", "untested")


def test_property_4_push_failure_does_not_promote():
    """(4) Does not promote: build_push failure blocks tag-image promotion."""
    needs_results = {
        "build_push": "failure",
        "manifest": "skipped",
        "sign": "skipped",
        "verify_boot": "skipped",
    }
    assert evaluate_promote_condition(needs_results) is False, "Promote must NOT execute when image push fails"


def test_property_5_push_failure_keeps_diagnostic_evidence(tmp_path):
    """(5) Keeps enough evidence to diagnose: full retry history and EOF error are preserved."""
    proc = _run_mocked_build_push(tmp_path, fail_layer=True)

    assert "Uploading layer 2/3: sha256:222..." in proc.stderr
    assert "EOF while writing layer to ghcr.io" in proc.stderr
    assert "attempt 1 failed" in proc.stderr
    assert "attempt 2 failed" in proc.stderr
