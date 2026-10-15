"""tunaOS#2113: Bonito's full matrix ran after its Fedora 44 pin had expired.

The repository-wide check passed on 2026-08-25 (run 32907984619), but Quay
removed the digest before Bonito run 32965043165 started. Both base
architectures then failed with ``manifest unknown``. In addition, build-config.yml
lacked Renovate digest automation. Build workflows must probe their base image pin
immediately before invoking the build matrix, and Renovate must track build-config.yml.

Falsification: structural — remove the preflight step from build-variant.yml,
its scoped command from check-base-image-pins.sh, or the build-config manager
from renovate.json, and this test fails as the affected tree did.
"""

from pathlib import Path
import json
import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "build-variant.yml"
SCRIPT = ROOT / "scripts" / "check-base-image-pins.sh"
RENOVATE = ROOT / "renovate.json"

yaml = pytest.importorskip("yaml")


def test_variant_build_preflight_verifies_base_pin_before_matrix() -> None:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    generate_matrix = data["jobs"]["generate_matrix"]
    step_commands = [step.get("run", "") for step in generate_matrix.get("steps", [])]

    assert any("./scripts/check-base-image-pins.sh" in cmd for cmd in step_commands), (
        "generate_matrix in build-variant.yml must verify the base image pin "
        "before emitting the build matrix"
    )


def test_pin_checker_supports_a_validated_variant_scope() -> None:
    body = SCRIPT.read_text(encoding="utf-8")
    assert 'VARIANT_FILTER="${1:-}"' in body
    assert "select(.id ==" in body
    assert "^[a-z0-9-]+$" in body, "a workflow argument must not become yq code"


def test_renovate_tracks_build_config_base_images() -> None:
    config = json.loads(RENOVATE.read_text(encoding="utf-8"))
    managers = config.get("customManagers", [])
    build_config_mgr = next(
        (m for m in managers if any("build-config" in pat for pat in m.get("managerFilePatterns", []))),
        None
    )
    assert build_config_mgr is not None, "renovate.json must have a customManager for build-config.yml"
    assert build_config_mgr.get("datasourceTemplate") == "docker"
    assert any("base_image" in s for s in build_config_mgr.get("matchStrings", []))
