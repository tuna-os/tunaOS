"""The evidence bundle is a stable, cell-addressed contract for every gate."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evidence-bundle.sh"


def run_bundle(tmp_path: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {
        "EVIDENCE_ROOT": str(tmp_path / "evidence"),
        "EVIDENCE_ARCH": "amd64",
        "EVIDENCE_STATUS": "success",
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_REPOSITORY": "tuna-os/tunaOS",
        "GITHUB_SHA": "abc123",
    }
    return subprocess.run(
        [str(SCRIPT), *args], text=True, capture_output=True, env=env, check=False
    )


def test_bundle_normalizes_boot_evidence_and_metadata(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "serial.log").write_text("TUNAOS_DESKTOP_CONTRACT_OK\n")
    (run_dir / "screen.png").write_bytes(b"png")

    result = run_bundle(tmp_path, "yellowfin:gnome", "boots", str(run_dir))
    assert result.returncode == 0, result.stderr

    bundle = tmp_path / "evidence/yellowfin/gnome/amd64"
    metadata = json.loads((bundle / "metadata.json").read_text())
    assert set(metadata) == {
        "schema_version", "cell", "variant", "flavor", "architecture",
        "criteria", "status", "run", "git_sha", "timestamp",
    }
    assert metadata["schema_version"] == 1
    assert metadata["cell"] == "yellowfin:gnome"
    assert metadata["criteria"] == ["boots"]
    assert metadata["run"] == {
        "id": "42",
        "attempt": "2",
        "repository": "tuna-os/tunaOS",
    }
    assert (bundle / "boot.log").read_text().startswith("TUNAOS_")
    assert (bundle / "screen.png").read_bytes() == b"png"


def test_contract_result_splits_desktop_and_omissions_axes(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "contract"
    run_dir.mkdir()
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "cell": "albacore:kde",
                "variant": "albacore",
                "desktop": "kde",
                "status": "pass",
                "reason": "contract satisfied",
                "exit": "0",
                "omissions_status": "pass",
                "omissions_reason": "TUNAOS_WISHLIST_OK misses=0",
            }
        )
    )

    result = run_bundle(
        tmp_path, "albacore:kde", "desktop,no_silent_omissions", str(run_dir)
    )
    assert result.returncode == 0, result.stderr
    bundle = tmp_path / "evidence/albacore/kde/amd64"
    assert json.loads((bundle / "desktop-contract.json").read_text())["status"] == "pass"
    assert json.loads((bundle / "omissions.json").read_text()) == {
        "cell": "albacore:kde",
        "status": "pass",
        "reason": "TUNAOS_WISHLIST_OK misses=0",
    }


def test_every_collect_evidence_step_uses_the_bundle_builder() -> None:
    workflows = ROOT / ".github/workflows"
    found = []
    for path in workflows.glob("*.yml"):
        document = yaml.safe_load(path.read_text()) or {}
        for job_name, job in (document.get("jobs") or {}).items():
            for step in job.get("steps", []):
                if step.get("name") == "Collect evidence":
                    found.append(f"{path.name}:{job_name}")
                    assert "scripts/evidence-bundle.sh" in step.get("run", ""), (
                        f"{path.name}:{job_name} still emits an ad-hoc evidence shape"
                    )
    assert found, "the test must inspect real evidence-producing jobs"


def test_green_axes_without_an_evidence_url_fail_validation() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gms", ROOT / "scripts/gen-matrix-status.py"
    )
    assert spec and spec.loader
    gms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gms)

    provenance = {
        "yellowfin:gnome": {
            "boots": {"verdict": "pass", "evidence": ""},
            "desktop": {"verdict": "fail", "evidence": ""},
        }
    }
    assert gms.green_axes_without_evidence(provenance) == [
        "yellowfin:gnome:boots"
    ]
    provenance["yellowfin:gnome"]["boots"]["evidence"] = (
        "https://github.com/tuna-os/tunaOS/actions/runs/42#artifacts"
    )
    assert gms.green_axes_without_evidence(provenance) == []


def test_bundle_rejects_path_traversal_in_cell(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = run_bundle(tmp_path, "../outside:gnome", "boots", str(run_dir))
    assert result.returncode == 2
    assert "invalid cell" in result.stderr
    assert not (tmp_path / "outside").exists()
