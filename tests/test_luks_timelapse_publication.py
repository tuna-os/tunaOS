"""Keep the public LUKS timelapse publication wired to the E2E artifacts."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "luks-e2e.yml"
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
DOCS = ROOT / "docs" / "TESTING.md"
PAGES_INDEX = ROOT / "pages" / "e2e" / "luks" / "latest" / "index.html"


def _publication_job() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["publish-latest-timelapse"]


def _run_steps() -> str:
    return "\n".join(
        step.get("run", "")
        for step in _publication_job()["steps"]
        if "run" in step
    )


def test_publication_waits_for_a_fully_passing_luks_matrix():
    job = _publication_job()
    assert job["needs"] == ["generate-matrix", "luks"]
    assert job["if"] == (
        "needs.luks.result == 'success' && "
        "needs.generate-matrix.outputs.publish_latest == 'true'"
    )


def test_publication_selects_the_uploaded_webm_and_publishes_a_player():
    text = _run_steps()
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    assert "pattern: luks-e2e-*" in workflow_text
    assert workflow_text.index("Checkout Pages template") < workflow_text.index(
        "Download passing-cell artifacts"
    )
    assert "base_desktops" in workflow_text
    assert "base_cells" in WORKFLOW.read_text(encoding="utf-8")
    assert "base_flavors" in text
    assert "expected_cells" in text
    assert "timelapse/timelapse.webm" in text
    assert "luks-evidence.log" in text
    assert "pages/e2e/luks/latest" in text
    assert '"${videos[$cell]}"' in text
    assert 'git push -f origin HEAD:pages-assets' in text
    assert "source-run.txt" in text


def test_publication_excludes_overlay_flavors_from_the_base_desktop_set():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'test("-(hwe|nvidia|asahi|t2|zfs|cachyos)$")' in text
    assert 'select(. != "base")' in text
    assert 'echo "publish_latest=true"' in text
    assert 'echo "publish_latest=false"' in text


def test_docs_link_to_the_same_stable_latest_pointer():
    docs = DOCS.read_text(encoding="utf-8")
    pages = PAGES_WORKFLOW.read_text(encoding="utf-8")
    assert "https://tuna-os.github.io/tunaOS/e2e/luks/latest/" in docs
    assert "repository_dispatch" in pages
    assert "pages-assets" in pages
    assert "actions/deploy-pages@" in pages
    assert PAGES_INDEX.is_file()
