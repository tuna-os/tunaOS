"""Failure injection: package repository 404 / 503 mid-build or during nightly checks.

Incident: tunaOS#391 (COPR single point of failure; snapshot bucket cleanup).
Where to assert: `scripts/check-package-repo-pins.py` + `build_scripts/lib.sh` `dnf_retry` against a stub HTTP server.

Asserts all five invariant properties:
  (1) Fails: check-package-repo-pins.py exits 1; dnf_retry exits non-zero upon exhaustion.
  (2) Says why: output names the HTTP status code (404/503), the failed URL, and retry exhaustion.
  (3) Does not call the cell green: composite status scoring evaluates the cell as not green.
  (4) Does not promote: build/package install failure blocks tag-image promotion job.
  (5) Keeps enough evidence to diagnose: logged URLs, status codes, and attempt counts are preserved.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

from tests.injection.helpers import (
    ROOT,
    StubHttpServer,
    evaluate_composite_status,
    evaluate_promote_condition,
    make_executable,
)

CHECK_PINS_SCRIPT = ROOT / "scripts" / "check-package-repo-pins.py"
LIB_SCRIPT = ROOT / "build_scripts" / "lib.sh"


@pytest.fixture
def http_stub():
    server = StubHttpServer()
    base_url = server.start()
    yield server, base_url
    server.stop()


@pytest.mark.parametrize("status_code", [404, 503, 500])
def test_property_1_and_2_repo_outage_fails_pin_check_and_says_why(tmp_path, http_stub, status_code):
    """(1) Fails and (2) says why: check-package-repo-pins.py fails and names HTTP code & URL."""
    server, base_url = http_stub
    repo_path = f"/repo/{status_code}/repodata/repomd.xml"
    repo_url = f"{base_url}{repo_path}"
    server.add_route(repo_path, status_code=status_code, body=b"Error")

    manifest_dir = tmp_path / "manifests" / "desktops"
    manifest_dir.mkdir(parents=True)
    manifest_file = manifest_dir / "test.yaml"
    manifest_file.write_text(
        yaml.dump({"fedora": {"repos": [{"baseurl": f"{base_url}/repo/{status_code}/"}]}}),
        encoding="utf-8",
    )

    spec = importlib.util.spec_from_file_location("crpp", CHECK_PINS_SCRIPT)
    crpp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crpp)
    crpp.MANIFEST_GLOB = str(manifest_dir / "*.yaml")

    import io
    import sys
    captured = io.StringIO()
    old_stdout = sys.stdout
    try:
        sys.stdout = captured
        exit_code = crpp.main()
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()

    # (1) Fails
    assert exit_code == 1, "check-package-repo-pins.py must exit 1 on repository HTTP failure"

    # (2) Says why
    assert f"FAIL  dnf   {status_code}" in output
    assert f"::error::package-repo pin no longer resolves (HTTP {status_code}): {repo_url}" in output
    assert "1 unresolvable" in output


@pytest.mark.parametrize("error_type", ["404_not_found", "503_unavailable"])
def test_property_1_and_2_dnf_retry_fails_and_says_why(tmp_path, error_type):
    """(1) Fails and (2) says why: dnf_retry in lib.sh exhausts attempts and reports failure."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Mock dnf that simulates curl / mirror failures
    mock_dnf = f"""#!/usr/bin/env bash
echo "Error: Failed to download metadata for repo 'copr': Cannot download repomd.xml: Cannot find a valid baseurl for repo: {error_type}" >&2
exit 1
"""
    make_executable(bin_dir / "dnf", mock_dnf)

    # Stub sleep so test executes instantly without sleeping
    probe_script = tmp_path / "run_dnf_retry.sh"
    probe_script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -u
            export PATH="{bin_dir}:$PATH"
            export DNF_RETRY_ATTEMPTS=3
            sleep() {{ :; }}
            source "{LIB_SCRIPT}"
            dnf_retry install -y test-package
            """
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["bash", str(probe_script)],
        capture_output=True,
        text=True,
    )

    # (1) Fails
    assert proc.returncode != 0, "dnf_retry must exit non-zero after exhausting retry attempts"

    # (2) Says why
    assert "dnf attempt 1/3 failed" in proc.stderr
    assert "dnf attempt 2/3 failed" in proc.stderr
    assert "dnf failed after 3 attempts" in proc.stderr


def test_property_3_repo_outage_does_not_call_cell_green():
    """(3) Does not call the cell green: cell with failing package install is not composite green."""
    stage = {
        "yellowfin": {
            "jobs": {
                ("gnome", "build_push"): "failure",
                ("gnome", "Promote"): "skipped",
            },
            "date": "2026-09-02",
        }
    }
    green, total, lines, prov = evaluate_composite_status(stage)
    assert green == 0, "Cell with failing build due to repo outage must not be composite green"
    verdict = prov.get("yellowfin:gnome", {}).get("builds", {}).get("verdict")
    assert verdict in ("fail", "untested")


def test_property_4_repo_outage_does_not_promote():
    """(4) Does not promote: build_push failure prevents tag-image from executing."""
    needs_results = {
        "build_push": "failure",
        "manifest": "skipped",
        "sign": "skipped",
        "verify_boot": "skipped",
    }
    assert evaluate_promote_condition(needs_results) is False, "Promote must not run when package repo fails"


def test_property_5_repo_outage_keeps_diagnostic_evidence(tmp_path, http_stub):
    """(5) Keeps enough evidence to diagnose: probe log records full URLs and retry history."""
    server, base_url = http_stub
    repo_path = "/repo/copr-fail/repodata/repomd.xml"
    server.add_route(repo_path, status_code=404, body=b"Missing COPR")

    manifest_dir = tmp_path / "manifests" / "desktops"
    manifest_dir.mkdir(parents=True)
    manifest_file = manifest_dir / "test.yaml"
    manifest_file.write_text(
        yaml.dump({"el10": {"repos": [{"baseurl": f"{base_url}/repo/copr-fail/"}]}}),
        encoding="utf-8",
    )

    spec = importlib.util.spec_from_file_location("crpp", CHECK_PINS_SCRIPT)
    crpp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crpp)
    crpp.MANIFEST_GLOB = str(manifest_dir / "*.yaml")

    import io
    import sys
    captured = io.StringIO()
    old_stdout = sys.stdout
    try:
        sys.stdout = captured
        crpp.main()
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()
    # The evidence contains full URL, 404 code, and repo type
    assert f"{base_url}{repo_path}" in output
    assert "FAIL  dnf   404" in output
    # Server recorded the probe requests (initial + retry)
    assert len(server.requests_log) >= 2, "check script must record initial and retry requests"
