"""Failure injection: base image digest garbage-collected upstream.

Incident: tunaOS#1788 (three variants died at once, 2026-08-16).
Where to assert: `scripts/check-base-image-pins.sh` against a stub registry returning 404.

Asserts all five invariant properties:
  (1) Fails: check-base-image-pins.sh exits non-zero (exit code 1).
  (2) Says why: output contains HTTP 404 error and names the failing ref.
  (3) Does not call the cell green: composite status scoring evaluates the cell as not green.
  (4) Does not promote: build_push failure prevents tag-image promotion job from running.
  (5) Keeps enough evidence to diagnose: output logs the failing digest and registry response.
"""

from __future__ import annotations

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

DEAD_DIGEST = "b" * 64
SAMPLE_DEAD_REF = f"quay.io/fedora/fedora-bootc:44@sha256:{DEAD_DIGEST}"
SAMPLE_HEALTHY_REF = "quay.io/fedora/fedora-bootc:44@sha256:" + "a" * 64


def _run_check_with_injected_registry(tmp_path: Path, refs: list[str], http_code: int = 404):
    """Run check-base-image-pins.sh with a stub registry returning http_code."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    make_executable(
        bin_dir / "yq",
        "#!/usr/bin/env bash\n" + "".join(f'echo "{r}"\n' for r in refs),
    )

    curl_stub = f"""#!/usr/bin/env bash
url=""
for a in "$@"; do case "$a" in https://*) url="$a" ;; esac; done
echo "$url" >> "{tmp_path}/urls.txt"
case "$url" in
  *"/token"*|*"/v2/auth"*) echo '{{"token":"faketoken"}}'; exit 0 ;;
esac
code=200
case "$url" in
  *{DEAD_DIGEST}*) code={http_code} ;;
esac
for a in "$@"; do
  if [ "$a" = "%{{http_code}}" ]; then printf '%s' "$code"; exit 0; fi
done
exit 0
"""
    make_executable(bin_dir / "curl", curl_stub)

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


@pytest.mark.parametrize("status_code", [404, 410, 500])
def test_property_1_and_2_gc_digest_fails_and_says_why(tmp_path, status_code):
    """(1) Fails and (2) says why: check exits 1 and names the HTTP status & digest."""
    proc = _run_check_with_injected_registry(tmp_path, [SAMPLE_DEAD_REF], http_code=status_code)

    # (1) Fails
    assert proc.returncode == 1, "check-base-image-pins.sh must fail when base digest is GC'd"

    # (2) Says why
    assert f"FAIL  {status_code}" in proc.stdout, f"stdout must report FAIL {status_code}"
    assert "::error::" in proc.stdout, "stdout must emit a GitHub Actions error annotation"
    assert SAMPLE_DEAD_REF in proc.stdout, "stdout must name the exact unresolvable base image ref"
    assert "1 unresolvable" in proc.stdout


def test_property_3_gc_digest_does_not_call_cell_green():
    """(3) Does not call the cell green: cell with failing base build is not composite-green."""
    # When base digest fails to resolve, the build step fails
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
    assert green == 0, "cell with failing base build must NOT be scored as composite green"

    # In provenance payload, builds verdict is untested/fail
    bonito_entry = prov.get("bonito:gnome", {})
    assert bonito_entry.get("builds", {}).get("verdict") in ("fail", "untested")


def test_property_4_gc_digest_does_not_promote():
    """(4) Does not promote: promote job (tag-image) condition is not satisfied."""
    # When base image 404s, build_push fails -> manifest & sign fail/skipped
    needs_results = {
        "build_push": "failure",
        "manifest": "skipped",
        "sign": "skipped",
        "verify_boot": "skipped",
    }
    can_promote = evaluate_promote_condition(needs_results)
    assert can_promote is False, "Promote job must NOT run when base build fails"


def test_property_5_gc_digest_keeps_diagnostic_evidence(tmp_path):
    """(5) Keeps enough evidence to diagnose: logged URLs, status code, and count retained."""
    proc = _run_check_with_injected_registry(
        tmp_path, [SAMPLE_HEALTHY_REF, SAMPLE_DEAD_REF], http_code=404
    )

    # Stderr/stdout preserves full breakdown
    assert "checked 2 digest-pinned base image(s); 1 unresolvable" in proc.stdout
    assert "ok    200" in proc.stdout
    assert "FAIL  404" in proc.stdout
    urls_file = tmp_path / "urls.txt"
    assert urls_file.exists()
    assert DEAD_DIGEST in urls_file.read_text()
