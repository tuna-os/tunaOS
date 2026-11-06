"""Current documentation must not point at the archived installer repositories.

`fisherman` and `bootc-installer` moved from `projectbluefin/*` to `tuna-os/*`
and the old repositories are archived (tunaOS#3690). Documentation kept linking
to them as if they were the active source.

This is a scoped gate, not a link checker: it rejects the two archived
repository names in Markdown. The failure catalog in docs/ci-troubleshooting.md
may name them where a numbered row describes the incident the move fixed; the
exception is that one row shape, not the whole file.

The expected map stays in this test, so a future rename fails here and gets a
deliberate documentation update.

Falsification: structural -- put `github.com/projectbluefin/fisherman` back in
docs/USER-GUIDE.md and `test_current_docs_name_the_active_installer_repositories`
fails.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Archived repository -> the active repository that replaces it.
ARCHIVED_TO_ACTIVE = {
    "projectbluefin/fisherman": "tuna-os/fisherman",
    "projectbluefin/bootc-installer": "tuna-os/bootc-installer",
}

_ARCHIVED = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(name) for name in ARCHIVED_TO_ACTIVE) + r")(?![\w-])"
)
# A numbered row of the failure catalog in docs/ci-troubleshooting.md.
_HISTORICAL_ROW = re.compile(r"^\| \d+ \|")
_CATALOG = "docs/ci-troubleshooting.md"


def _markdown_files() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    # Vendored upstream trees are not our documentation.
    return [path for path in tracked if not path.startswith("_upstream-snapshots/")]


def _stale_references() -> list[str]:
    found = []
    for relative in _markdown_files():
        path = ROOT / relative
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if relative == _CATALOG and _HISTORICAL_ROW.match(line):
                continue
            for match in _ARCHIVED.finditer(line):
                found.append(
                    f"{relative}:{number}: {match.group(1)} is archived; "
                    f"use {ARCHIVED_TO_ACTIVE[match.group(1)]}"
                )
    return found


def test_current_docs_name_the_active_installer_repositories() -> None:
    assert not _stale_references()


def test_the_gate_catches_an_archived_reference_outside_the_catalog_rows() -> None:
    assert _ARCHIVED.search("see https://github.com/projectbluefin/fisherman for it")
    assert _ARCHIVED.search("from `projectbluefin/bootc-installer`")
    assert not _ARCHIVED.search("https://github.com/tuna-os/fisherman")
    assert not _ARCHIVED.search("_upstream-snapshots/fisherman/")
    assert _HISTORICAL_ROW.match("| 30 | `marlin:cosmic` installs fail")
    assert not _HISTORICAL_ROW.match("| **fisherman** | Disk installer")
