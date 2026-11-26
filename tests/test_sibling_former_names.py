"""The former name of a BuildStream sibling appears only as a declared alias.

tuna-os/xfce-linux became tuna-os/brussels. `ghcr.io/tuna-os/xfce-linux` stays
a same-digest alias, and `xfce-linux:xfce` stays a deprecated cell name. Any
other use of the old name is a stale reference: a base row, a doc table, an
evidence record. This test lists each tracked file that mentions the old name
and demands that the line says it is the former name.
"""
from __future__ import annotations

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
