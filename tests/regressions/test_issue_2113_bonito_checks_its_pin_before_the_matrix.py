"""tunaOS#2113: Bonito's full matrix ran after its Fedora 44 pin had expired.

The repository-wide check passed on 2026-08-25 (run 32907984619), but Quay
removed the digest before Bonito run 32965043165 started. Both base
architectures then failed with ``manifest unknown``. Bonito must probe only
its own pin immediately before invoking the reusable matrix workflow.

Falsification: structural — remove the preflight job, its scoped command, or
the build job's dependency on it and this test fails as the affected tree did.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "build-bonito.yml"
SCRIPT = ROOT / "scripts" / "check-base-image-pins.sh"

yaml = pytest.importorskip("yaml")


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def test_bonito_pin_preflight_blocks_the_matrix() -> None:
    jobs = _jobs()
    preflight = jobs["preflight-base-pin"]
    build = jobs["build"]

    assert build["needs"] == "preflight-base-pin"
    assert build["uses"] == "./.github/workflows/build-variant.yml"

    commands = [step.get("run", "") for step in preflight["steps"]]
    assert "./scripts/check-base-image-pins.sh bonito" in commands, (
        "the preflight must be scoped to Bonito so an unrelated variant's pin "
        "cannot prevent the Fedora matrix from starting"
    )


def test_pin_checker_supports_a_validated_variant_scope() -> None:
    body = SCRIPT.read_text(encoding="utf-8")
    assert 'VARIANT_FILTER="${1:-}"' in body
    assert "select(.id ==" in body
    assert "^[a-z0-9-]+$" in body, "a workflow argument must not become yq code"
