"""Failure injection: declared architecture missing from base manifest.

Incident: tunaOS#1755 §3 (hummingbird arm64 declared against single-arch source).
Where to assert: `scripts/check-base-image-pins.sh` arch check against a manifest lacking declared arch.

Asserts all five invariant properties:
  (1) Fails: check-base-image-pins.sh exits non-zero (exit code 1).
  (2) Says why: output names the variant, declared platform, and base available architectures.
  (3) Does not call the cell green: composite status scoring evaluates the cell as not green.
  (4) Does not promote: manifest requires all declared platforms, blocking tag-image promotion.
  (5) Keeps enough evidence to diagnose: diagnostic output prints declared vs available architectures.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.injection.helpers import (
    ROOT,
    evaluate_composite_status,
    evaluate_promote_condition,
    make_executable,
)

SCRIPT = ROOT / "scripts" / "check-base-image-pins.sh"


def _run_arch_check(tmp_path: Path, variant: str, platforms: list[str], available_archs: list[str]):
    """Run check-base-image-pins.sh with a stubbed multi-arch or single-arch manifest."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    digest = "a" * 64
    base_ref = f"quay.io/fedora/fedora-bootc:44@sha256:{digest}"
    platforms_str = ",".join(platforms)

    # Mock yq to return:
    # 1. Base image list
    # 2. Tab-separated [id, base_image, platforms]
    yq_script = f"""#!/usr/bin/env bash
if [[ "$*" == *".base_image // empty"* ]]; then
  echo "{base_ref}"
elif [[ "$*" == *"@tsv"* ]]; then
  printf "%s\\t%s\\t%s\\n" "{variant}" "{base_ref}" "{platforms_str}"
else
  echo ""
fi
"""
    make_executable(bin_dir / "yq", yq_script)

    # Mock curl returning an OCI manifest list / index
    manifests_json = [
        {"platform": {"architecture": arch, "os": "linux"}} for arch in available_archs
    ]
    index_payload = json.dumps({"manifests": manifests_json})

    curl_script = f"""#!/usr/bin/env bash
url=""
for a in "$@"; do case "$a" in https://*) url="$a" ;; esac; done
case "$url" in
  *"/token"*|*"/v2/auth"*) echo '{{"token":"faketoken"}}'; exit 0 ;;
esac
for a in "$@"; do
  if [ "$a" = "%{{http_code}}" ]; then printf '200'; exit 0; fi
done
echo '{index_payload}'
exit 0
"""
    make_executable(bin_dir / "curl", curl_script)

    config_file = tmp_path / "config.yml"
    config_file.write_text("variants: []\n", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["YQ"] = str(bin_dir / "yq")
    env["CONFIG"] = str(config_file)

    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
    )


def test_property_1_and_2_missing_arch_fails_and_says_why(tmp_path):
    """(1) Fails and (2) says why: check-base-image-pins.sh fails and names missing arch."""
    variant = "hummingbird"
    declared_platforms = ["linux/amd64", "linux/arm64"]
    available_archs = ["amd64"]  # arm64 missing!

    proc = _run_arch_check(tmp_path, variant, declared_platforms, available_archs)

    # (1) Fails
    assert proc.returncode == 1, "check-base-image-pins.sh must fail when declared arch is missing"

    # (2) Says why
    assert f"ARCH  FAIL {variant}: linux/arm64 — base quay.io/fedora/fedora-bootc provides only [amd64]" in proc.stdout
    assert "::error::" in proc.stdout
    assert "arch_honesty" in proc.stdout
    assert "1 unsatisfiable" in proc.stdout


def test_property_3_missing_arch_does_not_call_cell_green():
    """(3) Does not call the cell green: cell with missing arch build is not composite-green."""
    # arm64 build failed / skipped while amd64 succeeded
    stage = {
        "hummingbird": {
            "jobs": {
                ("gnome", "build_push"): "failure",
                ("gnome", "Promote"): "skipped",
            },
            "date": "2026-09-02",
        }
    }
    green, total, lines, prov = evaluate_composite_status(stage)
    assert green == 0, "Cell with missing architecture build must not be composite green"
    verdict = prov.get("hummingbird:gnome", {}).get("builds", {}).get("verdict")
    assert verdict in ("fail", "untested")


def test_property_4_missing_arch_does_not_promote():
    """(4) Does not promote: missing platform blocks manifest and tag-image promotion."""
    # When one platform fails, manifest all_platforms_built is False and tag-image is blocked
    needs_results = {
        "manifest": "failure",
        "sign": "skipped",
        "verify_boot": "skipped",
    }
    assert evaluate_promote_condition(needs_results) is False, "Promote must not execute when multi-arch build fails"


def test_property_5_missing_arch_keeps_diagnostic_evidence(tmp_path):
    """(5) Keeps enough evidence to diagnose: output logs declared platforms vs base platforms."""
    variant = "hummingbird"
    declared_platforms = ["linux/amd64", "linux/arm64"]
    available_archs = ["amd64"]

    proc = _run_arch_check(tmp_path, variant, declared_platforms, available_archs)

    # Verify diagnostic evidence
    assert "checked 2 declared platform(s); 1 unsatisfiable" in proc.stdout
    assert "arch   ok  hummingbird: linux/amd64 (base has: amd64)" in proc.stdout
    assert "ARCH  FAIL hummingbird: linux/arm64" in proc.stdout
