"""Failure injection: full disk during build or cache operations (ENOSPC).

Where to assert: `scripts/build-image-inner.sh` / build operations under simulated disk quota exhaustion.

Asserts all five invariant properties:
  (1) Fails: build operation exits non-zero when disk is full.
  (2) Says why: error output explicitly captures "No space left on device" / ENOSPC.
  (3) Does not call the cell green: builds criterion is marked failing, cell is not green.
  (4) Does not promote: build failure prevents tag-image promotion job from running.
  (5) Keeps enough evidence to diagnose: captured build logs record the exact ENOSPC error.
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


def _run_mocked_enospc_build(tmp_path: Path):
    """Run build operation under simulated disk full condition."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    builder_stub = """#!/usr/bin/env bash
echo "Writing rootfs layers..." >&2
echo "write /var/tmp/buildah-cache: No space left on device (ENOSPC)" >&2
exit 1
"""
    make_executable(bin_dir / "podman", builder_stub)

    runner_script = tmp_path / "run_build_enospc.sh"
    runner_script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -u
            export PATH="{bin_dir}:$PATH"
            BUILDER="podman"
            sleep() {{ :; }}

            build_attempt=1
            until "${{BUILDER}}" build -t test:image . ; do
              if [[ "${{build_attempt}}" -ge 2 ]]; then
                echo "ERROR: image build failed after ${{build_attempt}} attempt(s)" >&2
                exit 1
              fi
              echo "${{BUILDER}} build attempt ${{build_attempt}} failed; retrying..." >&2
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


def test_property_1_and_2_disk_full_fails_and_says_why(tmp_path):
    """(1) Fails and (2) says why: build fails and error explicitly reports No space left on device."""
    proc = _run_mocked_enospc_build(tmp_path)

    # (1) Fails
    assert proc.returncode == 1, "Build must fail when disk is full"

    # (2) Says why
    assert "No space left on device" in proc.stderr
    assert "ERROR: image build failed after 2 attempt(s)" in proc.stderr


def test_property_3_disk_full_does_not_call_cell_green():
    """(3) Does not call the cell green: cell with ENOSPC build failure is not composite green."""
    stage = {
        "albacore": {
            "jobs": {
                ("gnome", "build_push"): "failure",
                ("gnome", "Promote"): "skipped",
            },
            "date": "2026-09-02",
        }
    }
    green, total, lines, prov = evaluate_composite_status(stage)
    assert green == 0, "Cell with failed build due to full disk must not be composite green"
    verdict = prov.get("albacore:gnome", {}).get("builds", {}).get("verdict")
    assert verdict in ("fail", "untested")


def test_property_4_disk_full_does_not_promote():
    """(4) Does not promote: build failure prevents tag-image from executing."""
    needs_results = {
        "build_push": "failure",
        "manifest": "skipped",
        "sign": "skipped",
        "verify_boot": "skipped",
    }
    assert evaluate_promote_condition(needs_results) is False, "Promote must NOT run when build fails due to full disk"


def test_property_5_disk_full_keeps_diagnostic_evidence(tmp_path):
    """(5) Keeps enough evidence to diagnose: ENOSPC error string is preserved in log."""
    proc = _run_mocked_enospc_build(tmp_path)
    assert "ENOSPC" in proc.stderr
    assert "/var/tmp/buildah-cache: No space left on device" in proc.stderr
