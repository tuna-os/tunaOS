"""PACKAGE-SOURCING.md lists every R2 URL that an image build reads.

The R2 inventory section of PACKAGE-SOURCING.md says which builds still depend
on https://repo.tunaos.org (epic #3470). A table that nobody checks is stale
the day it merges (AGENTS.md, PR quality contract rule 3), so this test derives
the URLs and the config tables that read them with scripts/r2-dependency-report.py
and compares them with the first two columns of the table, in both directions:

- a URL with no row means a new R2 dependency entered without a decision;
- a row with no URL means a cutover landed and the table still claims R2;
- a reader that differs means a config moved and the row names the old one.

Rows match their URL EXACTLY. A keyring URL has its own row, so retiring a
package repository cannot be hidden by the keyring that sits below it.

Measured state (counts, sizes, OCI tags) is not in the table at all: the report
script emits it, tests/test_r2_dependency_report.py runs that script's parsers.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "PACKAGE-SOURCING.md"
SPEC = importlib.util.spec_from_file_location(
    "r2_report", ROOT / "scripts" / "r2-dependency-report.py"
)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)

SECTION = re.compile(
    r"<!-- r2-inventory:start -->\n(?P<table>.*?)<!-- r2-inventory:end -->", re.S
)


def reader_names(readers: list[str]) -> set[str]:
    """`tunaos.toml [desktops.x.packages.el10.repos]` -> `desktops.x.packages.el10`."""
    names = set()
    for reader in readers:
        match = re.fullmatch(r"tunaos\.toml \[(.+?)(?:\.repos)?\]", reader)
        names.add(match.group(1) if match else reader)
    return names


def documented_rows(text: str | None = None) -> dict[str, set[str]]:
    match = SECTION.search(DOC.read_text() if text is None else text)
    assert match, "PACKAGE-SOURCING.md lost its r2-inventory markers"
    rows: dict[str, set[str]] = {}
    for row in match.group("table").splitlines():
        if not row.startswith("| `"):
            continue
        cells = row.split("|")
        prefixes = re.findall(r"`([^`]+)`", cells[1])
        assert len(prefixes) == 1, f"one prefix per row, got {prefixes}"
        rows[prefixes[0]] = set(re.findall(r"`([^`]+)`", cells[2]))
    assert rows, "the r2-inventory table has no rows"
    return rows


def problems(found: dict[str, list[str]], rows: dict[str, set[str]]) -> list[str]:
    result = [f"URL without a row: {p}" for p in sorted(set(found) - set(rows))]
    result += [f"row without a URL: {p}" for p in sorted(set(rows) - set(found))]
    for prefix in sorted(set(found) & set(rows)):
        derived = reader_names(found[prefix])
        if derived != rows[prefix]:
            result.append(
                f"readers of {prefix} are {sorted(derived)}, the row says {sorted(rows[prefix])}"
            )
    return result


def test_the_table_matches_what_the_builds_read():
    assert problems(report.scan(ROOT), documented_rows()) == []


def test_a_keyring_cannot_keep_a_retired_repository_row_alive():
    found = report.scan(ROOT)
    del found["tideforge/ubuntu/"]  # the package repository moved to OCI
    assert found["tideforge/ubuntu/tideforge.gpg"], "the keyring is still read"
    assert "row without a URL: tideforge/ubuntu/" in problems(found, documented_rows())


def test_a_new_url_a_missing_row_and_a_moved_reader_are_each_reported():
    found = report.scan(ROOT)
    found["new/prefix/"] = ["tunaos.toml [desktops.x.packages.el10.repos]"]
    del found["xfce/44-x86_64/"]
    found["rpm/eln/x86_64/"] = ["tunaos.toml [desktops.tuna.packages.el10.repos]"]
    reported = problems(found, documented_rows())
    assert "URL without a row: new/prefix/" in reported
    assert "row without a URL: xfce/44-x86_64/" in reported
    assert any(line.startswith("readers of rpm/eln/x86_64/") for line in reported)


def test_the_scan_sees_the_known_dependencies():
    """Guard the guard: an empty scan would pass the tests above."""
    urls = report.scan(ROOT)
    assert "public.gpg" in urls
    assert "hummingbird/20251124-$basearch/" in urls
    assert any(path.startswith("tideforge/") for path in urls)
    assert "tunaos.toml [desktops.gnome.packages.hummingbird.repos]" in urls[
        "hummingbird/20251124-$basearch/"
    ]


def test_the_table_carries_no_hand_kept_measurement():
    """Counts, sizes and OCI state come from the report, not from this table."""
    match = SECTION.search(DOC.read_text())
    header = match.group("table").splitlines()[0]
    assert [c.strip() for c in header.strip("|").split("|")] == [
        "Prefix",
        "Read by",
        "Smallest next step",
    ]
