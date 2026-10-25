"""PACKAGE-SOURCING.md lists every R2 URL that an image build reads.

The R2 inventory section of PACKAGE-SOURCING.md says which builds still depend
on https://repo.tunaos.org (epic #3470). A status table that nobody checks is
stale the day it merges (AGENTS.md, PR quality contract rule 3), so this test
derives the set of URLs from the build inputs and compares it with the first
column of the table in both directions:

- a URL with no row means a new R2 dependency entered without a decision;
- a row with no URL means a cutover landed and the table still claims R2.

Comment lines are skipped: they name prefixes without reading them.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "PACKAGE-SOURCING.md"
URL = re.compile(r"https://repo\.tunaos\.org/([^\s\"'`)>,]+)")
SECTION = re.compile(
    r"<!-- r2-inventory:start -->\n(?P<table>.*?)<!-- r2-inventory:end -->", re.S
)


def build_input_files() -> list[Path]:
    files = [ROOT / "tunaos.toml", ROOT / "image-versions.yaml"]
    files += sorted(ROOT.glob("Containerfile*"))
    files += sorted(p for p in (ROOT / "build_scripts").rglob("*") if p.is_file())
    return [p for p in files if p.is_file()]


def urls_read_by_builds() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in build_input_files():
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            if line.lstrip().startswith("#"):
                continue
            for match in URL.finditer(line):
                # printf-style escapes end the URL in Containerfile.arch.
                prefix = match.group(1).removesuffix("\\n")
                found.setdefault(prefix, []).append(f"{path.name}:{number}")
    return found


def documented_prefixes() -> list[str]:
    match = SECTION.search(DOC.read_text())
    assert match, "PACKAGE-SOURCING.md lost its r2-inventory markers"
    prefixes: list[str] = []
    for row in match.group("table").splitlines():
        if not row.startswith("| `"):
            continue
        first_cell = row.split("|")[1]
        prefixes += re.findall(r"`([^`]+)`", first_cell)
    assert prefixes, "the r2-inventory table has no rows"
    return prefixes


def covers(documented: str, url_path: str) -> bool:
    """A row covers its own prefix and any file below it (a keyring)."""
    return url_path == documented or (
        documented.endswith("/") and url_path.startswith(documented)
    )


def test_every_r2_url_a_build_reads_has_a_row():
    rows = documented_prefixes()
    missing = {
        path: where
        for path, where in urls_read_by_builds().items()
        if not any(covers(row, path) for row in rows)
    }
    assert not missing, (
        "These repo.tunaos.org URLs are read by a build and have no row in the "
        f"R2 build dependency inventory of PACKAGE-SOURCING.md: {missing}"
    )


def test_every_row_still_has_a_url():
    urls = urls_read_by_builds()
    stale = [
        row
        for row in documented_prefixes()
        if not any(covers(row, path) for path in urls)
    ]
    assert not stale, (
        "These rows of the R2 build dependency inventory no longer match any "
        f"URL in the build inputs; delete them with the cutover: {stale}"
    )


def test_the_scan_sees_the_known_dependencies():
    """Guard the guard: an empty scan would pass both tests above."""
    urls = urls_read_by_builds()
    assert "public.gpg" in urls
    assert "hummingbird/20251124-$basearch/" in urls
    assert any(path.startswith("tideforge/") for path in urls)
