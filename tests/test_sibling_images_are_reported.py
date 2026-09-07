"""tromso and xfce-linux are family images, and the README says so.

They are bootc images built in their own repositories with BuildStream on
freedesktop-sdk: whole-OS products, not package sources. That is why they
have no cells in the variant matrix and are not scored by green-criteria.yml
(their objects match one SDK and cannot be repackaged for the distro
variants here; tunaos-packages docs/experiments/tideforge-universal-
intermediate.md measured that). It is also why they were invisible: nothing
in this repository named them, so "what does the TunaOS family ship" had no
single answer.

`sibling_images:` in build-config.yml is that answer, and
.github/scripts/sibling-images-status.sh renders each one's latest completed
main-branch build into the README block next to the variant matrix. These
tests run the renderer for real against a fake `gh`, so the shape of the
table and the fetch-failure behaviour are held, not described.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
SCRIPT = ROOT / ".github" / "scripts" / "sibling-images-status.sh"
GENERATOR = ROOT / ".github" / "scripts" / "update-build-status.sh"
README = ROOT / "README.md"

REQUIRED = {"id", "emoji", "description", "image", "repo", "workflow", "desktops"}


def siblings() -> list[dict]:
    return yaml.safe_load(CONFIG.read_text())["sibling_images"]


# ── the declaration ────────────────────────────────────────────────────────


def test_the_two_buildstream_images_are_declared():
    assert {s["id"] for s in siblings()} == {"tromso", "xfce-linux"}


@pytest.mark.parametrize("sibling", siblings(), ids=lambda s: s["id"])
def test_every_sibling_is_fully_described(sibling):
    missing = REQUIRED - set(sibling)
    assert not missing, f"{sibling['id']}: missing {sorted(missing)}"
    assert sibling["image"] == f"ghcr.io/tuna-os/{sibling['id']}"
    assert sibling["repo"] == f"tuna-os/{sibling['id']}"
    assert sibling["workflow"].endswith(".yml")
    assert sibling["desktops"], "a sibling image ships a desktop; say which"


def test_siblings_are_not_variants():
    """The point: they are listed, not scored. A sibling that also appears as a
    variant would be counted twice, once with cells it does not have."""
    variants = {v["id"] for v in yaml.safe_load(CONFIG.read_text())["variants"]}
    assert not variants & {s["id"] for s in siblings()}


def test_the_readme_lists_them_as_images_to_choose():
    text = README.read_text()
    for s in siblings():
        assert f"`{s['image']}`" in text, f"{s['id']} is missing from Choose your image"
        assert f"https://github.com/{s['repo']}" in text


def test_the_generator_renders_them_inside_the_block():
    text = GENERATOR.read_text()
    assert "sibling-images-status.sh" in text
    # after the variant loop, before the totals: not a cell, not in the count
    assert text.index("sibling-images-status.sh") > text.index("done < <(yq -r '.variants[]")
    assert text.index("sibling-images-status.sh") < text.index("percent=$((100 * total_green / total_cells))")


# ── the renderer, run for real ─────────────────────────────────────────────


def fake_gh(bindir: Path, behaviour: str) -> None:
    """`gh run list --repo R --workflow W ...` answered per repo."""
    gh = bindir / "gh"
    gh.write_text("#!/usr/bin/env bash\n" + behaviour)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def render(tmp_path: Path, behaviour: str, config: Path = CONFIG) -> subprocess.CompletedProcess:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake_gh(bindir, behaviour)
    return subprocess.run(
        ["bash", str(SCRIPT), str(config)],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"},
    )


CANNED = r'''
repo=""; for ((i = 1; i <= $#; i++)); do [[ "${!i}" == --repo ]] && j=$((i+1)) && repo="${!j}"; done
case "$repo" in
  tuna-os/tromso)
    # newest run is cancelled and must be skipped; the next concluded one counts
    echo '[{"databaseId":3,"conclusion":"cancelled","createdAt":"2026-09-02T00:30:00Z","url":"https://github.com/tuna-os/tromso/actions/runs/3","status":"completed"},
           {"databaseId":2,"conclusion":"success","createdAt":"2026-09-01T00:30:00Z","url":"https://github.com/tuna-os/tromso/actions/runs/2","status":"completed"}]' ;;
  tuna-os/xfce-linux)
    echo '[{"databaseId":9,"conclusion":null,"createdAt":"2026-09-02T23:30:00Z","url":"https://github.com/tuna-os/xfce-linux/actions/runs/9","status":"in_progress"},
           {"databaseId":8,"conclusion":"failure","createdAt":"2026-09-01T23:30:00Z","url":"https://github.com/tuna-os/xfce-linux/actions/runs/8","status":"completed"}]' ;;
  *) echo "unexpected repo $repo" >&2; exit 1 ;;
esac
'''


def test_renders_one_row_per_sibling_from_the_newest_concluded_run(tmp_path):
    proc = render(tmp_path, CANNED)
    assert proc.returncode == 0, proc.stderr
    rows = [l for l in proc.stdout.splitlines() if l.startswith("| ") and "`ghcr.io" in l]
    assert len(rows) == 2, proc.stdout
    tromso = next(r for r in rows if "tromso" in r)
    xfce = next(r for r in rows if "xfce-linux" in r)
    # the cancelled run was skipped; the success behind it is the verdict
    assert "[✅ 2026-09-01](https://github.com/tuna-os/tromso/actions/runs/2)" in tromso
    # the in-flight run was skipped; the failure behind it is the verdict
    assert "[❌ 2026-09-01](https://github.com/tuna-os/xfce-linux/actions/runs/8)" in xfce
    assert "| KDE |" in tromso and "| XFCE |" in xfce
    assert "[tromso](https://github.com/tuna-os/tromso)" in tromso
    header = [l for l in proc.stdout.splitlines() if l.startswith("| Image")]
    assert header == ["| Image | Built by | Desktop | Latest main build |"]


def test_a_fetch_failure_is_not_fetched_not_a_verdict(tmp_path):
    """A cross-repo read the token cannot make must not become a ❌ (that is
    a lie about their build) or stop the README refresh (that hides ours)."""
    proc = render(tmp_path, 'echo "HTTP 403" >&2; exit 1\n')
    assert proc.returncode == 0, proc.stderr
    rows = [l for l in proc.stdout.splitlines() if "`ghcr.io" in l]
    assert len(rows) == 2
    for row in rows:
        assert "⬜ not fetched" in row and "❌" not in row and "✅" not in row


def test_no_siblings_means_no_table(tmp_path):
    empty = tmp_path / "build-config.yml"
    empty.write_text("config: {}\nvariants: []\n")
    proc = render(tmp_path, "exit 1\n", config=empty)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
