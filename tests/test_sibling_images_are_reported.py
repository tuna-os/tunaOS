"""BuildStream image family entries appear in the README image matrix.

Published images report their latest completed main-branch workflow. Athens
has only a local BuildStream target, so it must be listed without inventing
an image build status.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "tunaos.toml"
SCRIPT = ROOT / ".github" / "scripts" / "sibling-images-status.sh"
GENERATOR = ROOT / ".github" / "scripts" / "update-build-status.sh"
README = ROOT / "README.md"
SPEC = importlib.util.spec_from_file_location(
    "sibling_primary_config_under_test",
    ROOT / "scripts" / "lib" / "tunaos_config.py",
)
primary_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(primary_config)

REQUIRED = {"id", "emoji", "description", "repo", "desktops", "mark", "availability"}


def siblings() -> list[dict]:
    return primary_config.load(CONFIG)["sibling_images"]

# ── the declaration ────────────────────────────────────────────────────────


def test_all_three_buildstream_images_are_declared():
    assert {s["id"] for s in siblings()} == {"athens", "tromso", "xfce-linux"}


@pytest.mark.parametrize("sibling", siblings(), ids=lambda s: s["id"])
def test_every_family_image_has_one_honest_output_kind(sibling):
    missing = REQUIRED - set(sibling)
    assert not missing, f"{sibling['id']}: missing {sorted(missing)}"
    assert sibling["repo"] == f"tuna-os/{sibling['id']}"
    assert sibling["desktops"], "declare the desktop this image carries"
    assert bool(sibling.get("image")) != bool(sibling.get("target"))
    if sibling.get("image"):
        assert sibling["image"] == f"ghcr.io/tuna-os/{sibling['id']}"
        assert sibling["workflow"].endswith(".yml")
    else:
        assert sibling["id"] == "athens"
        assert sibling["target"] == "oci/athens.bst"
        assert "workflow" not in sibling

def test_family_images_are_not_distro_variants():
    variants = set(primary_config.load(CONFIG)["variants"])
    assert not variants & {s["id"] for s in siblings()}


def test_the_readme_lists_brand_and_output_for_every_family_image():
    text = README.read_text()
    for sibling in siblings():
        output = sibling.get("image", sibling.get("target"))
        assert f"`{output}`" in text, f"{sibling['id']} is missing from Choose your image"
        assert f"https://github.com/{sibling['repo']}" in text
        assert sibling["mark"] in text


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
    if config.suffix == ".toml":
        config_data = primary_config.matrix(primary_config.load(config))
        rendered_config = tmp_path / "build-config.json"
        rendered_config.write_text(json.dumps(config_data, ensure_ascii=False))
        config = rendered_config
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


def test_renders_published_runs_and_local_target_without_fabricating_status(tmp_path):
    proc = render(tmp_path, CANNED)
    assert proc.returncode == 0, proc.stderr
    rows = [l for l in proc.stdout.splitlines() if l.startswith("| ") and ("ghcr.io" in l or "oci/athens.bst" in l)]
    assert len(rows) == 3, proc.stdout
    tromso = next(r for r in rows if "tromso" in r)
    xfce = next(r for r in rows if "xfce-linux" in r)
    athens = next(r for r in rows if "athens" in r)
    assert "[✅ 2026-09-01](https://github.com/tuna-os/tromso/actions/runs/2)" in tromso
    assert "[❌ 2026-09-01](https://github.com/tuna-os/xfce-linux/actions/runs/8)" in xfce
    assert "| KDE |" in tromso and "| XFCE |" in xfce
    assert "[tromso](https://github.com/tuna-os/tromso)" in tromso
    assert '<img width="28" alt="" src="https://tunaos.org/img/buildstream/tromso/tromso-logo.svg" />' in tromso
    assert '<img width="28" alt="" src="https://tunaos.org/img/buildstream/brussels/brussels-logo.svg" />' in xfce
    assert '<img width="28" alt="" src="https://tunaos.org/img/buildstream/athens/athens-logo.svg" />' in athens
    assert "Experimental · local-only; no public image" in athens
    assert "graph checks only; no image build" in athens
    assert "[athens](https://github.com/tuna-os/athens)" in athens
    header = [l for l in proc.stdout.splitlines() if l.startswith("| Brand")]
    assert header == ["| Brand | Image or target | Project | Desktop | Availability | Latest main build |"]


def test_a_fetch_failure_is_not_fetched_not_a_verdict(tmp_path):
    """A cross-repo read the token cannot make must not become a verdict."""
    proc = render(tmp_path, 'echo "HTTP 403" >&2; exit 1\n')
    assert proc.returncode == 0, proc.stderr
    rows = [l for l in proc.stdout.splitlines() if "`ghcr.io" in l]
    assert len(rows) == 2
    for row in rows:
        assert "⬜ not fetched" in row and "❌" not in row and "✅" not in row
    athens = next(l for l in proc.stdout.splitlines() if "oci/athens.bst" in l)
    assert "graph checks only; no image build" in athens


def test_no_family_images_means_no_table(tmp_path):
    empty = tmp_path / "build-config.json"
    empty.write_text('{"config": {}, "variants": [], "sibling_images": []}')
    proc = render(tmp_path, "exit 1\n", config=empty)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
