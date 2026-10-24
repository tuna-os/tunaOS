"""Public signal accounting must not turn metadata or dogfooding into adoption."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("adoption_snapshot", ROOT / "scripts/adoption-snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def asset(name, count, ident=1):
    return {"id": ident, "name": name, "download_count": count, "browser_download_url": "https://example.org/asset"}


def test_metadata_and_drafts_cannot_inflate_iso_downloads():
    result = snapshot.release_counts([
        {"draft": False, "assets": [asset("tuna.iso", 7), asset("tuna.iso.sha256", 200), asset("sbom.json", 300)]},
        {"draft": True, "assets": [asset("unpublished.iso", 1000)]},
        {"draft": False, "assets": []},
    ])
    assert result["iso_downloads_lifetime"] == 7
    assert result["non_iso_downloads_lifetime"] == 500
    assert result["published_releases"] == 2
    assert result["iso_assets"][0]["id"] == 1
    assert snapshot.release_counts([])["iso_downloads_lifetime"] == 0


def test_dogfooding_and_ecosystem_are_excluded():
    text = """## Production Users
| Organization | Use Case | Variant(s) | Since |
|---|---|---|---|
| Example | Desktop | Yellowfin | 2026-10 |
## Development & Evaluation
| Organization | Use Case | Variant(s) | Since |
|---|---|---|---|
| [@hanthor](https://github.com/hanthor) | Test | Yellowfin | 2026-04 |
| [Hive](https://hive.tunaos.org) | CI | Yellowfin | 2026-05 |
| Evaluator | Pilot | Albacore | 2026-10 |
## Upstream & Ecosystem Dependencies
| Fedora | Base OS | Link |
"""
    assert snapshot.adopter_counts(text) == {"production": 1, "evaluation": 1, "internal_excluded": 2}
    with pytest.raises(ValueError, match="sections changed"):
        snapshot.adopter_counts("renamed sections")


def test_every_page_is_counted_with_read_only_api(monkeypatch):
    calls = []

    def gh(args):
        calls.append(args)
        return json.dumps([[{"id": 1}], [{"id": 2}]])

    monkeypatch.setattr(snapshot, "gh", gh)
    assert snapshot.api("repos/example/repo/releases", pages=True) == [{"id": 1}, {"id": 2}]
    assert calls == [["api", "--method", "GET", "repos/example/repo/releases", "--paginate", "--slurp"]]


def test_api_failure_does_not_publish_zero_or_partial_report(monkeypatch, tmp_path):
    def failed_api(*args, **kwargs):
        raise RuntimeError("API unavailable")

    monkeypatch.setattr(snapshot, "api", failed_api)
    monkeypatch.setattr(sys, "argv", ["adoption-snapshot.py", "--output-dir", str(tmp_path / "report")])
    with pytest.raises(RuntimeError, match="API unavailable"):
        snapshot.main()
    assert not (tmp_path / "report").exists()


def test_discussion_comments_exclude_replies(monkeypatch):
    discussions = [
        {"number": 93, "html_url": "https://example.org/discussions/93"},
        {"number": 652, "html_url": "https://example.org/discussions/652"},
    ]
    def fake_api(endpoint, pages=False):
        if "93/comments" in endpoint:
            return []
        if "652/comments" in endpoint:
            return [
                {"id": 1, "parent_id": None},
                {"id": 2, "parent_id": 1},
                {"id": 3, "parent_id": 1},
                {"id": 4, "parent_id": None},
                {"id": 5, "parent_id": None},
            ]
        raise ValueError(endpoint)
    monkeypatch.setattr(snapshot, "api", fake_api)
    assert snapshot.top_level_discussion_comments(discussions) == 3


def test_live_collection_path_writes_matching_report_and_receipt(monkeypatch, tmp_path):
    (tmp_path / "ADOPTERS.md").write_text("## Production Users\n## Development & Evaluation\n")
    responses = iter([
        {"stargazers_count": 60, "forks_count": 7},
        [{"draft": False, "assets": [asset("tuna.iso", 7)]}],
        [{"number": 1, "comments": 2, "html_url": "https://example.org/discussions/1"}],
        [{"id": 10, "parent_id": None}, {"id": 11, "parent_id": 10}],
    ])
    monkeypatch.setattr(snapshot, "ROOT", tmp_path)
    monkeypatch.setattr(snapshot, "api", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(snapshot.subprocess, "check_output", lambda *args, **kwargs: "a" * 40 + "\n")
    output = tmp_path / "report"
    monkeypatch.setattr(sys, "argv", ["adoption-snapshot.py", "--output-dir", str(output)])
    snapshot.main()
    receipt = json.loads(next(output.glob("*.json")).read_text())
    assert next(output.glob("*.md")).read_text() == snapshot.render(receipt)
    assert receipt["releases"]["iso_downloads_lifetime"] == 7
    assert receipt["discussions"]["top_level_comments"] == 1
    assert "r2_iso_downloads" in receipt["unavailable"]
    assert "not monthly downloads" in snapshot.render(receipt)
