"""Protect snapshot #3149 from false ISO counts and ambiguous variant attribution."""

import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("census", ROOT / "scripts/release-asset-census.py")
census = importlib.util.module_from_spec(spec)
spec.loader.exec_module(census)


def config():
    return {"variants": [{"id": name, "flavors": [{"id": "gnome", "build_iso": True}]}
                         for name in ("flounder", "flounder-sid")]}


def asset(number, name, count):
    return {"id": number, "name": name, "download_count": count,
            "created_at": "2026-07-01T00:00:00Z", "updated_at": "2026-07-02T00:00:00Z",
            "browser_download_url": f"https://github.com/example/{number}/{name}"}


def release(assets, **kwargs):
    return {"tag_name": "gnome-20260701", "draft": False, "prerelease": False,
            "assets": assets, **kwargs}


def test_only_iso_downloads_can_rank_and_longest_variant_wins():
    data = census.summarize([release([
        asset(1, "release-card.png", 1000), asset(2, "sbom-flounder-gnome.json", 300),
        asset(3, "flounder-sid-gnome-nvidia-13-x86_64.iso", 2),
        asset(4, "flounder-gnome-13-x86_64.iso.sha256", 50),
        asset(5, "flounder-gnome-13-x86_64.iso", 0),
        asset(6, "flounder-latest.iso", 7),
    ])], config())
    assert data["non_iso_lifetime_downloads"] == 1350
    assert len(data["iso_assets"]) == 3
    assert data["iso_assets"][0]["variant"] == "flounder-sid"
    assert data["iso_assets"][-1]["desktop"] is None
    cells = {(c["variant"], c["desktop"]): c for c in data["cells"]}
    assert cells["flounder", "gnome"]["lifetime_downloads"] == 0
    assert cells["flounder-sid", "gnome"]["lifetime_downloads"] == 2
    assert cells["flounder", "kde"]["iso_enabled"] is False


def test_drafts_and_prereleases_do_not_establish_presence():
    data = census.summarize([
        release([asset(1, "flounder-gnome-13.iso", 40)], draft=True),
        release([asset(2, "flounder-gnome-13.iso", 20)], prerelease=True),
    ], config())
    assert data["iso_assets"] == []
    assert data["public_non_prerelease_releases"] == 0


def test_missing_iso_flag_is_not_a_publication_promise():
    cfg = config()
    del cfg["variants"][0]["flavors"][0]["build_iso"]
    data = census.summarize([], cfg)
    assert not next(c for c in data["cells"] if c["variant"] == "flounder" and c["desktop"] == "gnome")["iso_enabled"]


def test_positive_iso_rank_excludes_other_downloads_and_zero_pairs():
    data = census.summarize([release([
        asset(1, "release-card.png", 1000),
        asset(2, "flounder-gnome-13.iso", 4),
        asset(3, "flounder-sid-gnome-13.iso", 8),
    ])], config())
    receipt = {"data": data, "started_at": "test", "finished_at": "test",
               "source_commit": "test", "repository": {"stargazers_count": 1, "forks_count": 1}}
    ranking = census.render(receipt).split("## Top ten")[1].split("## Asset evidence")[0]
    assert ranking.index("| flounder-sid | gnome | 8 |") < ranking.index("| flounder | gnome | 4 |")
    assert "1000" not in ranking
    assert "| kde |" not in ranking
    assert "monthly performance remains unmeasured" in ranking


def test_top_ten_is_bounded_with_a_stable_order_for_ties():
    cfg = {"variants": [{"id": f"variant{i:02}", "flavors": []} for i in range(12)]}
    data = census.summarize([release([
        asset(i, f"variant{i:02}-gnome-13.iso", 5) for i in reversed(range(12))
    ])], cfg)
    receipt = {"data": data, "started_at": "test", "finished_at": "test",
               "source_commit": "test", "repository": {"stargazers_count": 1, "forks_count": 1}}
    ranking = census.render(receipt).split("## Top ten")[1].split("## Asset evidence")[0]
    assert ranking.count("| gnome | 5 |") == 10
    assert ranking.index("variant00") < ranking.index("variant09")
    assert "variant10" not in ranking


def test_existing_receipt_cannot_be_overwritten(tmp_path):
    target = tmp_path / "receipt.json"
    target.write_text("keep this evidence")
    result = subprocess.run(["python3", str(ROOT / "scripts/release-asset-census.py"),
                             "--output", str(tmp_path / "receipt")],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "preserve the previous receipt" in result.stderr
    assert target.read_text() == "keep this evidence"
    assert not target.with_suffix(".md").exists()


def test_duplicate_ids_fail_instead_of_double_counting():
    row = release([asset(1, "flounder-gnome-13.iso", 1)])
    with pytest.raises(ValueError, match="Duplicate asset"):
        census.summarize([row, row], config())


@pytest.mark.parametrize("counter", [-1, None, True, "3"])
def test_invalid_counters_cannot_become_zero(counter):
    with pytest.raises(ValueError, match="Invalid download"):
        census.summarize([release([asset(1, "test.iso", counter)])], config())


def test_pagination_and_failed_api_are_not_empty_inventory():
    with patch.object(census.subprocess, "run") as run:
        run.return_value.stdout = '[[{"id": 1}], [{"id": 2}]]'
        assert census.gh_json("test", paginate=True) == [{"id": 1}, {"id": 2}]
        assert "--paginate" in run.call_args.args[0]
        run.side_effect = subprocess.CalledProcessError(1, "gh")
        with pytest.raises(subprocess.CalledProcessError):
            census.gh_json("test", paginate=True)


def test_committed_markdown_matches_receipt_and_totals_reconcile():
    import json
    path = ROOT / "docs/adoption-metrics/2026-10-23-release-census.json"
    receipt = json.loads(path.read_text())
    assert path.with_suffix(".md").read_text() == census.render(receipt)
    data = receipt["data"]
    mapped = [a for a in data["iso_assets"] if a["variant"] and a["desktop"]]
    assert sum(c["assets"] for c in data["cells"]) == len(mapped)
    assert sum(c["lifetime_downloads"] for c in data["cells"]) == sum(a["lifetime_downloads"] for a in mapped)
    assert "There is no measured rank" in census.render(receipt)
