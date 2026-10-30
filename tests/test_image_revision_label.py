"""Every built image carries org.opencontainers.image.revision (RFC 018 phase 4).

scripts/promote-stable.py reads the label from the image config to find the
commits an image contains and their Soak-After trailers. Images built before
this label existed carry only the short SHA in org.opencontainers.image.version.

scripts/build-image-inner.sh adds the label to BUILD_ARGS, which both the
primary build and the Containerfile.final relabel build consume. The workflow
passes the commit as SOURCE_REVISION through sudo. These tests run the label
block extracted from the script, so a change to the block is what they test.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build-image-inner.sh"
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"

LABEL = "org.opencontainers.image.revision"
REVISION_EXPR = "${{ github.event.pull_request.head.sha || github.sha }}"


def label_block() -> str:
    text = SCRIPT.read_text()
    match = re.search(r'^SOURCE_REVISION="\$\{SOURCE_REVISION:-\}"\n.*?--label.*?\nfi\n',
                      text, re.M | re.S)
    assert match, "the revision label block is missing from build-image-inner.sh"
    return match.group(0)


def labels_for(repo: Path, source_revision: str | None) -> list[str]:
    env = {"PATH": "/usr/bin:/bin"}
    if source_revision is not None:
        env["SOURCE_REVISION"] = source_revision
    out = subprocess.run(
        ["bash", "-euo", "pipefail", "-c",
         f'BUILD_ARGS=()\n{label_block()}printf "%s\\n" "${{BUILD_ARGS[@]}}"'],
        cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.split()
    return [arg for arg in out if arg.startswith(LABEL)]


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t",
                               "-c", "user.email=t@t", *args],
                              check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "base")
    return tmp_path, git("rev-parse", "HEAD")


def test_a_clean_local_build_is_labelled_with_the_full_head_commit(repo):
    path, head = repo
    assert labels_for(path, None) == [f"{LABEL}={head}"]


def test_ci_source_revision_wins_over_head(repo):
    path, _head = repo
    assert labels_for(path, "a" * 40) == [f"{LABEL}={'a' * 40}"]


def test_a_dirty_local_build_gets_no_revision(repo):
    path, _head = repo
    (path / "untracked").write_text("x")
    assert labels_for(path, None) == []


def test_both_builds_consume_the_label():
    text = SCRIPT.read_text()
    block = text.index(label_block())
    builds = [m.start() for m in re.finditer(r'^\s*"\$\{BUILD_ARGS\[@\]\}" \\$', text, re.M)]
    assert len(builds) == 2, "expected the primary build and the Containerfile.final build"
    assert all(start > block for start in builds), "the label is added after a build ran"
    assert '--file "Containerfile.final"' in text[builds[1]:]


def steps():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return [step for job in jobs.values() for step in job.get("steps", [])]


def test_the_build_step_passes_the_pr_head_or_pushed_commit_through_sudo():
    build = next(s for s in steps() if s.get("id") == "build-image")
    assert build["env"]["SOURCE_REVISION"] == REVISION_EXPR
    preserved = re.search(r"sudo --preserve-env=(\S+)", build["run"]).group(1).split(",")
    assert "SOURCE_REVISION" in preserved


def test_the_manifest_index_carries_the_same_revision():
    metadata = next(s for s in steps() if s.get("id") == "metadata")
    assert f"{LABEL}={REVISION_EXPR}" in metadata["with"]["labels"].splitlines()
