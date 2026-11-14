"""Workflow-level `paths` filters on pull requests must never hide a real input.

A skipped *job* reports Skipped, which still costs a workflow run per head. A
workflow-level `paths` filter keeps the run from starting at all, which is only
safe for a workflow that no required check and no merge-queue entry depends on.
`Lint` and `Unit Tests` are the only required checks, so lint.yml and test.yml
must keep running on every pull request and merge-queue entry; the filters
below belong to workflows nothing waits on.

A filter that is narrower than the logic behind it silently drops coverage, so
each test checks the filter against the repository's own files and against the
detector or recipe it mirrors.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
TUNA_DETECTOR = ROOT / ".github/scripts/tuna-pr-build-inputs.sh"
CANARY_DETECTOR = ROOT / ".github/scripts/canary-cell-inputs.sh"


def _on(name: str) -> dict:
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML resolves the bare key `on:` to the boolean True.
    return doc.get("on", doc.get(True))


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """GitHub filter syntax: `**` crosses `/`, `*` and `?` do not."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _selected(patterns: list[str], path: str) -> bool:
    """Patterns apply in order; a `!` pattern removes what came before it."""
    chosen = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        if _glob_to_regex(pattern.lstrip("!")).match(path):
            chosen = not negated
    return chosen


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
        ).stdout.decode("utf-8", "surrogateescape")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    files = [f for f in out.split("\0") if f and "\n" not in f]
    if not files:
        pytest.skip("no tracked files")
    return files


def test_the_glob_translation_matches_github_semantics():
    assert _selected(["Containerfile**"], "Containerfile.arch")
    assert _selected(["scripts/**"], "scripts/lib/x.sh")
    assert not _selected(["scripts/*"], "scripts/lib/x.sh")
    assert _selected(["**.sh"], "build_scripts/a/b.sh")
    assert _selected(["**.sh"], "a.sh")
    assert not _selected(["scripts/**", "!scripts/iso_*.py"], "scripts/iso_x.py")
    assert _selected(["scripts/**", "!scripts/iso_*.py"], "scripts/other.py")


@pytest.mark.parametrize("name", ["lint.yml", "test.yml"])
def test_required_check_workflows_are_never_path_filtered(name):
    """`Lint` and `Unit Tests` must report on every PR and merge-queue entry."""
    on = _on(name)
    for event in ("pull_request", "merge_group"):
        config = on[event] or {}
        assert not {"paths", "paths-ignore"} & set(config), (
            f"{name}: a {event} path filter would leave a required check "
            "that never reports"
        )


@pytest.mark.parametrize("name", ["tuna-pr-images.yml", "just-fix.yml", "actions-security.yml"])
def test_filtered_workflows_are_not_merge_queue_consumers(name):
    on = _on(name)
    assert "merge_group" not in on
    assert on["pull_request"]["paths"], f"{name}: pull_request lost its filter"


# -- Tuna PR images -----------------------------------------------------------


@pytest.fixture(scope="module")
def tuna_paths() -> list[str]:
    return _on("tuna-pr-images.yml")["pull_request"]["paths"]


def test_tuna_pr_images_keeps_its_pull_request_types():
    types = _on("tuna-pr-images.yml")["pull_request"]["types"]
    assert set(types) == {"opened", "synchronize", "reopened", "ready_for_review"}


def test_tuna_pr_images_filter_is_a_superset_of_the_detector(tracked, tuna_paths):
    """Every tracked file the filter skips must be inert to the detector.

    The detector keeps the last word on relevance and variant selection; the
    filter only decides whether the run starts. Anything the filter drops that
    the detector would have built is a pull request that silently loses its
    image cells.
    """
    skipped = [f for f in tracked if not _selected(tuna_paths, f)]
    assert skipped, "the filter selects every file"
    result = subprocess.run(
        ["bash", str(TUNA_DETECTOR)],
        input="\n".join(skipped) + "\n",
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    assert result.returncode == 1, (
        "the workflow `paths` filter hides inputs the detector selects: "
        + result.stdout.strip()
        + "\nOffenders:\n"
        + "\n".join(
            f
            for f in skipped
            if subprocess.run(
                ["bash", str(TUNA_DETECTOR)], input=f + "\n", text=True,
                capture_output=True, cwd=ROOT,
            ).returncode
            == 0
        )
    )


def test_tuna_pr_images_filter_covers_every_canary_input(tracked, tuna_paths):
    skipped = [f for f in tracked if not _selected(tuna_paths, f)]
    result = subprocess.run(
        ["bash", str(CANARY_DETECTOR)],
        input="\n".join(skipped) + "\n",
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    assert result.returncode == 1, result.stdout


@pytest.mark.parametrize(
    "path",
    [
        "Containerfile.arch",
        "build_scripts/install-uupd.sh",
        "system_files_overrides/bonito/etc/foo",
        "scripts/config.py",
        "tunaos.toml",
        "image-versions.yaml",
        ".github/workflows/build-variant.yml",
        ".github/workflows/tuna-pr-images.yml",
    ],
)
def test_tuna_pr_images_starts_for_known_inputs(tuna_paths, path):
    assert _selected(tuna_paths, path)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "docs/TESTING.md",
        "live-iso/common/src/x.sh",
        "scripts/iso_builder.py",
        "tests/test_x.py",
        ".github/workflows/ste.yml",
    ],
)
def test_tuna_pr_images_does_not_start_for_inert_changes(tuna_paths, path):
    assert not _selected(tuna_paths, path)


# -- Just Fix -----------------------------------------------------------------


def test_just_fix_keeps_main_push_and_filters_pull_requests():
    on = _on("just-fix.yml")
    assert on["push"]["branches"] == ["main"]
    assert "paths" not in on["push"], "main must always be formatted"


def test_just_fix_filter_covers_everything_the_fix_recipe_rewrites(tracked):
    """`just fix` runs shfmt on every `*.sh` and `just --fmt` on every `*.just`
    plus the Justfile, case-insensitively; it reads .editorconfig and verifies
    the pinned tool versions first."""
    paths = _on("just-fix.yml")["pull_request"]["paths"]
    missed = [
        f
        for f in tracked
        if f.lower().endswith((".sh", ".just")) and not _selected(paths, f)
    ]
    assert not missed, f"`just fix` rewrites these but the filter skips them: {missed}"
    for required in ("Justfile", ".editorconfig", "scripts/lint_tools.py",
                     "toolchain/lint-tools.json", ".github/workflows/just-fix.yml"):
        assert _selected(paths, required), required
    for inert in ("README.md", "Containerfile.el10", "tests/test_x.py"):
        assert not _selected(paths, inert), inert


# -- actions-security ---------------------------------------------------------


def test_actions_security_filter_covers_everything_it_reads(tracked):
    """Both jobs read workflows, local composite actions, the lock file and
    dependabot/zizmor config -- all under .github/. A composite action or a
    zizmor config anywhere else would escape the filter, so there must be none.
    """
    on = _on("actions-security.yml")
    assert on["pull_request"]["paths"] == [".github/**"]
    assert on["push"]["branches"] == ["main"]
    assert "paths" not in on["push"]
    assert "workflow_dispatch" in on
    stray = [
        f
        for f in tracked
        if not f.startswith(".github/")
        and re.search(r"(^|/)(action\.ya?ml|\.?zizmor\.ya?ml)\Z", f)
        and not f.startswith("_upstream-snapshots/")
    ]
    assert not stray, f"outside the actions-security filter: {stray}"
