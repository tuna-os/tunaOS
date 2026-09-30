"""Unit tests for scripts/generate-release-verification.py (tunaOS#2262)."""

import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate-release-verification.py"

spec = importlib.util.spec_from_file_location("generate_release_verification", SCRIPT)
grv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grv)


def test_script_exists():
    assert SCRIPT.exists()
    assert SCRIPT.stat().st_mode & 0o111, f"{SCRIPT} must be executable"


def test_generate_report_sections():
    report = grv.generate_report(
        stream="gnome",
        variant="yellowfin",
        tag="gnome-20260910",
        digest="sha256:123456",
        sbom_packages=1450,
        provenance_path=ROOT / "docs" / "matrix-provenance.json",
        criteria_path=ROOT / ".github" / "green-criteria.yml",
        config_path=ROOT / ".github" / "build-config.yml",
    )
    assert "## Release Verification Report" in report
    assert "### Factory Health" in report
    assert "Factory health:" in report
    assert "Install-tested:" in report
    assert "Lifecycle-tested:" in report
    assert "Never tested:" in report
    assert "Known regressions:" in report
    assert "Last full sweep:" in report
    assert "### Stream Verification: `gnome`" in report
    assert "Images built" in report
    assert "Signature & Supply Chain" in report
    assert "SPDX SBOM" in report
    assert "1450 packages" in report
    assert "Boot Verification (Gate)" in report
    assert "Desktop Contract" in report
    assert "Installer Smoke" in report
    assert "Bootc Lifecycle" in report
    assert "### Quality & Regressions Summary" in report


def test_generate_report_fallback_when_files_missing(tmp_path):
    empty_prov = tmp_path / "prov.json"
    empty_crit = tmp_path / "crit.yml"
    empty_cfg = tmp_path / "cfg.yml"
    report = grv.generate_report(
        stream="kde",
        variant="albacore",
        tag="kde-20260910",
        provenance_path=empty_prov,
        criteria_path=empty_crit,
        config_path=empty_cfg,
    )
    assert "## Release Verification Report" in report
    assert "Factory health:" in report
    assert "Stream Verification: `kde`" in report


def test_format_age():
    import datetime as dt
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    five_days_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5)).strftime("%Y-%m-%d")
    assert grv.format_age(today) == "today"
    assert grv.format_age(yesterday) == "1 day ago"
    assert grv.format_age(five_days_ago) == "5 days ago"
    assert grv.format_age(None) == "unknown"


def test_cli_execution():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--stream", "gnome", "--variant", "yellowfin", "--sbom-packages", "1450"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "## Release Verification Report" in proc.stdout
    assert "1450 packages cataloged in SPDX SBOM" in proc.stdout
