"""Disk-image variants (Ubuntu Core Desktop) are declared, validated and reported.

A disk image comes from another project and is not an OCI image: it has no
`image`, `target` or `installer_tag`, it is not a matrix cell, and the TunaOS
installer medium does not read it. The README reports the latest conclusive
run of the workflow of each desktop on the release branch of the project.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "tunaos.toml"
SCRIPT = ROOT / ".github" / "scripts" / "sibling-images-status.sh"
README = ROOT / "README.md"
SPEC = importlib.util.spec_from_file_location("disk_image_config_under_test", ROOT / "scripts" / "lib" / "tunaos_config.py")
primary_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(primary_config)


def disk() -> dict:
    return primary_config.load(CONFIG)["disk_images"][0]


def test_ubuntu_core_desktop_is_declared_with_one_workflow_for_each_desktop():
    record = disk()
    assert record["id"] == "ubuntu-core-desktop"
    assert record["repo"] == "canonical/ubuntu-core-desktop"
    assert record["branch"] == "desktop/26"
    assert record["desktops"] == ["GNOME", "KDE"]
    assert record["releases"] == ["gnome-latest", "kde-latest"]
    assert record["workflows"] == ["build-image.yaml", "build-image-kde.yaml"]
    for key in ("image", "target", "installer_tag"):
        assert key not in record, f"a disk image has no {key}"


def test_a_disk_image_is_not_a_variant_a_sibling_or_a_matrix_cell():
    source = primary_config.load(CONFIG)
    assert "ubuntu-core-desktop" not in source["variants"]
    assert "ubuntu-core-desktop" not in {s["id"] for s in source["sibling_images"]}
    cells = {c["cell"] for c in source["installer_medium"]["cells"]}
    assert not any(cell.startswith("ubuntu-core-desktop") for cell in cells)


def mutated(change) -> dict:
    source = copy.deepcopy(primary_config.load(CONFIG))
    change(source)
    return source


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda s: s["disk_images"][0]["releases"].pop(), "one entry each"),
        (lambda s: s["disk_images"][0]["workflows"].append("x.yaml"), "one entry each"),
        (lambda s: s["disk_images"][0].update(image="ghcr.io/x/y"), "image"),
        (lambda s: s["disk_images"][0].pop("branch"), "branch"),
        (lambda s: s["disk_images"].append(copy.deepcopy(s["disk_images"][0])), "duplicate"),
        (lambda s: s["disk_images"][0].update(id="tromso"), "duplicate"),
    ],
)
def test_the_validator_rejects_a_bad_disk_image(change, message):
    with pytest.raises(primary_config.ConfigError, match=message):
        primary_config.validate(mutated(change))


def test_the_projected_config_carries_the_disk_images_and_only_when_declared():
    assert primary_config.matrix(primary_config.load(CONFIG))["disk_images"][0]["id"] == "ubuntu-core-desktop"
    source = mutated(lambda s: s.pop("disk_images"))
    primary_config.validate(source)
    assert "disk_images" not in primary_config.matrix(source)


# ── the renderer, run for real ─────────────────────────────────────────────


def render(tmp_path: Path, behaviour: str) -> subprocess.CompletedProcess:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text("#!/usr/bin/env bash\n" + behaviour)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    config = tmp_path / "build-config.json"
    config.write_text(json.dumps(primary_config.matrix(primary_config.load(CONFIG)), ensure_ascii=False))
    return subprocess.run(
        ["bash", str(SCRIPT), str(config)],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "SIBLING_STATUS_TODAY": "2026-11-26"},
    )


def disk_row(stdout: str) -> str:
    return next(line for line in stdout.splitlines() if line.startswith("| `ubuntu-core-desktop`"))


# Each workflow gets its own newest runs, and only the release branch is asked.
CANNED = r'''
repo=""; workflow=""; branch=""
for ((i = 1; i <= $#; i++)); do
  case "${!i}" in --repo) j=$((i+1)); repo="${!j}" ;; --workflow) j=$((i+1)); workflow="${!j}" ;; --branch) j=$((i+1)); branch="${!j}" ;; esac
done
case "$repo" in
  canonical/ubuntu-core-desktop)
    [[ "$branch" == desktop/26 ]] || { echo "wrong branch $branch" >&2; exit 1; }
    case "$workflow" in
      build-image.yaml)
        echo '[{"databaseId":3,"conclusion":null,"createdAt":"2026-11-26T20:00:00Z","url":"https://github.com/canonical/ubuntu-core-desktop/actions/runs/3","status":"in_progress"},
               {"databaseId":2,"conclusion":"success","createdAt":"2026-11-26T18:04:00Z","url":"https://github.com/canonical/ubuntu-core-desktop/actions/runs/2","status":"completed"}]' ;;
      build-image-kde.yaml)
        echo '[{"databaseId":5,"conclusion":"failure","createdAt":"2026-11-25T05:13:00Z","url":"https://github.com/canonical/ubuntu-core-desktop/actions/runs/5","status":"completed"}]' ;;
      *) echo "unexpected workflow $workflow" >&2; exit 1 ;;
    esac ;;
  *) echo '[]' ;;
esac
'''


def test_each_desktop_gets_the_verdict_of_its_own_workflow_on_the_release_branch(tmp_path):
    proc = render(tmp_path, CANNED)
    assert proc.returncode == 0, proc.stderr
    row = disk_row(proc.stdout)
    assert "GNOME [✅ 2026-11-26](https://github.com/canonical/ubuntu-core-desktop/actions/runs/2)" in row
    assert "KDE [❌ 2026-11-25](https://github.com/canonical/ubuntu-core-desktop/actions/runs/5)" in row
    assert "`gnome-latest`, `kde-latest`" in row
    assert "[canonical/ubuntu-core-desktop](https://github.com/canonical/ubuntu-core-desktop)" in row


def test_an_old_green_disk_image_build_is_flagged_with_its_age(tmp_path):
    old = CANNED.replace("2026-11-26T18:04:00Z", "2026-11-20T18:04:00Z")
    row = disk_row(render(tmp_path, old).stdout)
    assert "GNOME [⚠️ 2026-11-20, 6 days old](" in row


def test_a_fetch_failure_is_not_fetched_for_every_desktop(tmp_path):
    proc = render(tmp_path, 'echo "HTTP 403" >&2; exit 1\n')
    assert proc.returncode == 0, proc.stderr
    row = disk_row(proc.stdout)
    assert "GNOME ⬜ not fetched · KDE ⬜ not fetched" in row
    assert "✅" not in row and "❌" not in row


def test_the_readme_reports_the_disk_image_with_a_run_link_of_the_project_for_each_desktop():
    row = next(line for line in README.read_text().splitlines() if line.startswith("| `ubuntu-core-desktop`"))
    status = row.rstrip("| ").rsplit("|", 1)[1].strip()
    run = r"\[(✅|❌|⬜|⚠️) [^\]]+\]\(https://github\.com/canonical/ubuntu-core-desktop/actions/runs/\d+\)"
    assert re.fullmatch(rf"GNOME {run} · KDE {run}", status) or status == "GNOME ⬜ not fetched · KDE ⬜ not fetched", status
    assert "not built or installed by it" in row
