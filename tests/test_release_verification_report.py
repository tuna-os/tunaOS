"""Release notes carry the public factory evidence from matrix provenance."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/render-release-verification.py"
SPEC = importlib.util.spec_from_file_location("release_verification", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def payload():
    result = lambda verdict, date="2026-10-15": {  # noqa: E731
        "verdict": verdict,
        "date": date,
        "run": "https://example.test/run",
        "evidence": "https://example.test/evidence",
    }
    return {
        "summary": {
            "factory_health": {"green": 1, "total": 2},
            "builds": {"passed": 1, "tested": 2, "total": 2},
            "boots": {"passed": 1, "tested": 1, "total": 2},
            "desktop": {"passed": 1, "tested": 2, "total": 2},
            "install": {"passed": 1, "tested": 2, "total": 2},
            "lifecycle": {"passed": 1, "tested": 2, "total": 2},
            "never_tested": 1,
            "known_regressions": {"blocking": 1, "advisory": 1},
            "last_full_sweep": "2026-10-15",
        },
        "cells": {
            "yellowfin:gnome": {
                "builds": result("pass"),
                "boots": result("pass"),
                "desktop": result("pass"),
                "install": result("pass"),
                "lifecycle": result("fail"),
            },
            "marlin:kde": {
                "builds": result("fail"),
                "boots": result("untested", ""),
                "desktop": result("fail"),
                "install": result("fail"),
                "lifecycle": result("pass"),
            },
        },
    }


def test_report_covers_release_and_runtime_verification_axes():
    report = MODULE.render(
        payload(), "ghcr.io/tuna-os/yellowfin:gnome", "sha256:abc", 123
    )
    for heading in ("Images", "Runtime", "Lifecycle", "Supply chain", "Regressions"):
        assert f"### {heading}" in report
    assert "Built and promoted: **1/2**" in report
    assert "SBOM: ✅ SPDX inventory contains 123 packages" in report
    assert "Booted: **1/2 pass (1/2 tested)**" in report
    assert "**1 blocking**, **1 advisory**" in report
    assert report.count(MODULE.BEGIN) == report.count(MODULE.END) == 1


def test_cli_accepts_the_workflow_digest_argument(tmp_path):
    provenance = tmp_path / "matrix-provenance.json"
    output = tmp_path / "release-body.md"
    provenance.write_text(json.dumps(payload()))
    digest = "sha256:" + "b" * 64
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--provenance",
            str(provenance),
            "--image",
            "ghcr.io/tuna-os/yellowfin:gnome",
            "--digest",
            digest,
            "--sbom-packages",
            "123",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert f"Digest: `{digest}`" in output.read_text()

def test_stored_release_identity_uses_original_immutable_reference():
    digest = "sha256:" + "a" * 64
    body = "\n".join([
        "release notes",
        f"  ghcr.io/tuna-os/yellowfin@{digest}",
        f"  ghcr.io/tuna-os/yellowfin@{digest} \\",
    ])
    assert MODULE.stored_image_identity(body) == (
        "ghcr.io/tuna-os/yellowfin", digest
    )


def test_stored_release_identity_rejects_missing_or_ambiguous_evidence():
    first = "sha256:" + "a" * 64
    second = "sha256:" + "b" * 64
    for body in (
        "release without immutable identity",
        f"ghcr.io/tuna-os/yellowfin@{first}\nghcr.io/tuna-os/yellowfin@{second}",
    ):
        try:
            MODULE.stored_image_identity(body)
        except ValueError:
            pass
        else:
            raise AssertionError("ambiguous stored evidence was accepted")
