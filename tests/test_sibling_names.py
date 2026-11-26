"""Names of the BuildStream siblings are written one way in every tracked file.

1. The former name appears only as a declared alias. tuna-os/xfce-linux became
   tuna-os/brussels. `ghcr.io/tuna-os/xfce-linux` stays a same-digest alias, and
   `xfce-linux:xfce` stays a deprecated cell name. Any other use of the old
   name is a stale reference: a base row, a doc table, an evidence record. Each
   line that mentions the old name must say that it is the former name.
2. The brand is Tromsø in prose. The ASCII spelling `tromso` belongs to the
   repository, the image and the cell id, and never starts with a capital.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORMER = "xfce-linux"

# Files that must mention the old name: the alias machinery and its tests,
# frozen snapshots, and dated records with commit links (GitHub redirects them).
EXEMPT = (
    "scripts/lib/installer_medium.py",
    "tests/",
    ".spektacular/",
    "docs/WORKFLOW-PERMISSIONS-AUDIT.md",
)
SAYS_FORMER = ("alias", "former", "then named", "earlier name", "deprecated", "was `xfce-linux`")


def tracked_text_files() -> list[str]:
    names = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    return [n for n in names if n and not n.startswith(EXEMPT) and (ROOT / n).is_file()]


def mentions() -> list[tuple[str, int, str]]:
    found = []
    for name in tracked_text_files():
        try:
            text = (ROOT / name).read_text()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if FORMER in line:
                found.append((name, number, line))
    return found


@pytest.mark.parametrize("name,number,line", mentions(), ids=lambda v: str(v)[:60])
def test_every_mention_of_the_former_name_says_it_is_the_former_name(name, number, line):
    assert any(word in line.lower() for word in SAYS_FORMER), (
        f"{name}:{number} uses {FORMER!r} as if it were the current name: {line.strip()[:120]}"
    )


def brand_misspellings() -> list[tuple[str, int, str]]:
    found = []
    for name in tracked_text_files():
        try:
            text = (ROOT / name).read_text()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if re.search(r"\bTromso\b", line):
                found.append((name, number, line))
    return found


def test_the_brand_is_spelled_tromso_with_the_slashed_o_in_prose():
    assert not brand_misspellings(), "write Tromsø, not Tromso: " + "; ".join(
        f"{n}:{i}" for n, i, _ in brand_misspellings()[:10]
    )
