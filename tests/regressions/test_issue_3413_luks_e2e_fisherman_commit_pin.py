"""tunaOS#3413: luks-e2e.yml must build a commit-pinned fisherman, not `dev`.

The workflow builds fisherman from a separate repository and runs the binary
as root during the privileged LUKS gate. Following the mutable `dev` branch
let a moved or compromised branch replace that binary. The checkout is now
commit-addressed, the commit is a 40-hex pin in image-versions.yaml (where
Renovate proposes bumps), the Go builder image is tag+digest pinned, and the
matrix cells run with a read-only contents token.

Falsification: structural — reintroducing `--branch dev`, a non-hex pin, an
unpinned golang image, or `contents: write` on the build job fails here.
"""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_TEXT = (ROOT / ".github" / "workflows" / "luks-e2e.yml").read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)
VERSIONS = yaml.safe_load((ROOT / "image-versions.yaml").read_text(encoding="utf-8"))


def _step(name_prefix: str) -> dict:
    for step in WORKFLOW["jobs"]["luks"]["steps"]:
        if step.get("name", "").startswith(name_prefix):
            return step
    raise AssertionError(f"no step named {name_prefix!r}")


def test_fisherman_checkout_does_not_follow_a_branch():
    run = _step("Clone fisherman")["run"]
    assert "--branch" not in run
    assert "git clone" not in run
    assert not re.search(r"\bdev\b", run.replace("under-test", ""))
    assert 'fetch --depth 1 origin "${FISHERMAN_SHA}"' in run
    assert "checkout -q --detach FETCH_HEAD" in run
    # The fetched commit must be the pinned one, not whatever FETCH_HEAD is.
    assert 'rev-parse HEAD)" == "$FISHERMAN_SHA"' in run
    assert "[0-9a-f]{40}" in run


def test_fisherman_pin_is_a_40_hex_commit_in_image_versions():
    pin = VERSIONS["downloads"]["fisherman"]
    assert re.fullmatch(r"[0-9a-f]{40}", pin)
    text = (ROOT / "image-versions.yaml").read_text(encoding="utf-8")
    # Renovate watches it through the git-refs marker the other source pins use.
    assert re.search(
        r"# renovate: datasource=git-refs depName=tuna-os/fisherman ref=dev\n"
        r'\s*fisherman: "[0-9a-f]{40}"',
        text,
    )
    assert "image-versions.yaml" in _step("Clone fisherman")["run"]


def test_a_fisherman_bump_is_reviewed_not_automerged():
    import json

    renovate = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
    holds = [
        r
        for r in renovate["packageRules"]
        if r.get("automerge") is False and "tuna-os/fisherman" in (r.get("matchDepNames") or [])
    ]
    assert holds


def test_go_builder_image_is_tag_and_digest_pinned():
    (entry,) = [i for i in VERSIONS["images"] if i["name"] == "fisherman-golang"]
    assert entry["image"] == "docker.io/library/golang"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", entry["digest"])
    build = _step("Build fisherman")["run"]
    assert "golang:${GOVER}" not in build
    assert '"${GOIMG}"' in build
    assert "GOTOOLCHAIN=local" in build


def test_matrix_cells_do_not_get_a_write_token():
    top = WORKFLOW.get("permissions") or {}
    assert top.get("contents") == "read"
    assert "write" not in top.values()
    for job_id in ("generate-matrix", "luks"):
        assert "permissions" not in WORKFLOW["jobs"][job_id], job_id
    # The pages-assets publisher is the only job that pushes.
    publisher = WORKFLOW["jobs"]["publish-latest-timelapse"]
    assert publisher["permissions"]["contents"] == "write"
    writers = [
        j
        for j, body in WORKFLOW["jobs"].items()
        if "write" in (body.get("permissions") or {}).values()
    ]
    assert writers == ["publish-latest-timelapse"]
