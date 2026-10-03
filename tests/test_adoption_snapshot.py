"""Regression coverage for the public adoption snapshot collector."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/generate-adoption-snapshot.py"
SPEC = importlib.util.spec_from_file_location("adoption_snapshot", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


def test_release_downloads_do_not_mislabel_sboms_or_cards_as_isos():
    releases = [
        {
            "assets": [
                {"name": "yellowfin-gnome.iso", "download_count": 7},
                {"name": "sbom-yellowfin-gnome.spdx.json", "download_count": 11},
                {"name": "release-card.png", "download_count": 13},
            ]
        }
    ]

    classes = module.classify_release_assets(releases)

    assert classes["iso"] == {"assets": 1, "downloads": 7}
    assert classes["sbom"] == {"assets": 1, "downloads": 11}
    assert classes["release_card"] == {"assets": 1, "downloads": 13}


def test_external_nonbot_contributions_exclude_members_and_known_automation():
    pulls = [
        {"number": 1, "merged_at": "2026-09-02T00:00:00Z", "author_association": "NONE", "user": {"login": "new-user", "type": "User"}},
        {"number": 2, "merged_at": "2026-09-03T00:00:00Z", "author_association": "MEMBER", "user": {"login": "maintainer", "type": "User"}},
        {"number": 3, "merged_at": "2026-09-04T00:00:00Z", "author_association": "CONTRIBUTOR", "user": {"login": "renovate[bot]", "type": "Bot"}},
        {"number": 4, "merged_at": None, "author_association": "NONE", "user": {"login": "not-merged", "type": "User"}},
    ]

    result = module.external_nonbot_prs(pulls, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")

    assert result == [{"number": 1, "author": "new-user", "merged_at": "2026-09-02T00:00:00Z"}]


def test_internal_dogfooding_is_not_counted_as_external_adoption():
    markdown = """## Production Users

| Organization | Use Case |
|---|---|
| Example Corp | Production |

## Development & Evaluation

| Organization | Use Case |
|---|---|
| [@hanthor](https://github.com/hanthor) | Daily driver |
| [TunaOS Hive Agents](https://hive.tunaos.org) | CI |
| Lab User | Evaluation |
"""

    assert module.count_adopters(markdown) == {
        "production": 1,
        "evaluation": 1,
        "external_total": 2,
    }


def test_report_names_missing_r2_data_instead_of_substituting_release_assets():
    snapshot = {
        "as_of": "2026-10-03",
        "window": {"start": "2026-09-01", "end_exclusive": "2026-10-01"},
        "repository": {"stars": 57, "forks": 5, "watchers": 1},
        "release_assets": {"classes": {"iso": {"assets": 0, "downloads": 0}, "sbom": {"assets": 10, "downloads": 20}}},
        "community": {"discussions_created": 0, "external_nonbot_prs_merged": 0, "external_nonbot_contributors": []},
        "adopters": {"external_total": 0},
        "unavailable": {"r2_iso_downloads": "not connected", "docs_visits": "not connected", "installs": "not collected"},
    }

    report = module.render(snapshot)

    assert "0 ISO assets" in report
    assert "Variant and desktop rankings remain unavailable" in report
    assert "SBOM and release-card downloads do not count as ISO downloads" in report
