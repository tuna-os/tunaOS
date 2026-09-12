"""The Test workflow must run on the files the tests actually read.

`test.yml` is path-filtered, so a pull request touching nothing in the filter
gets no Unit Tests at all -- and a PR with every applicable check green reads
exactly like a PR that was tested.

That is not theoretical. tunaOS#2475 changed one file,
manifests/desktops/gnome.yaml, and merged on 13 green checks with Unit Tests
absent, because `manifests/**` was not in the filter. Ten test files read
manifests/. One of them, tests/bats/test_niri_dms_payload.bats, exists because
a niri image once shipped, booted and published with its entire shell missing
(tunaOS#1009, #637) -- a manifest edit that broke that guard would have gone
green here and failed on a nightly instead.

The property: every repository path the suite asserts on is a path that
re-runs the suite. A test that cannot run on a change to the thing it tests is
the same class of dead gate as a karg on the wrong install path (tunaOS#2472)
-- present, passing, and measuring nothing.

Deliberately NOT required here, with reasons, because coverage comes from
elsewhere:

  README.md, ROADMAP.md, AGENTS.md   Prose. The `ste` workflow (Simplified
  CLAUDE.md                          Technical English) runs without a path
                                     filter, so an edit is still gated -- by a
                                     different check.

  docs/**                            Prose and generated content. The two docs
                                     files the suite reads more than once are
                                     MATRIX-STATUS.md, which the `regenerate`
                                     check owns end to end, and LUKS-TPM.md,
                                     which is prose under `ste`. Adding
                                     docs/** would run the whole suite on
                                     every typo fix for no coverage the repo
                                     does not already have. docs/CI_SPEC.md is
                                     in the filter on its own, because the CI
                                     contract test reads it as a spec rather
                                     than as prose.
"""
from __future__ import annotations

import collections
import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"

# A path must be referenced at least this many times before it counts. A single
# mention is often an example in a docstring or a one-off fixture; a path the
# suite genuinely depends on is read repeatedly.
MIN_REFS = 2

GATED_ELSEWHERE = {
    # Prose, gated by the `ste` workflow, which has no path filter.
    "README.md", "ROADMAP.md", "AGENTS.md", "CLAUDE.md",
    # Prose and generated content -- see the module docstring. CI_SPEC.md is
    # listed in the filter separately and is not excluded here.
    "docs",
}


def _filter_paths() -> list[str]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML parses the bare key `on:` as the boolean True.
    triggers = doc[True] if True in doc else doc["on"]
    return triggers["pull_request"]["paths"]


def _paths_the_suite_reads() -> dict[str, int]:
    """Top-level repo paths referenced from test files, with a count.

    Read out of the tests themselves rather than hardcoded, so a new test that
    reaches into a new directory shows up here instead of being silently
    untested.
    """
    refs: collections.Counter[str] = collections.Counter()
    for f in sorted(ROOT.joinpath("tests").rglob("*")):
        if f.suffix not in {".py", ".bats"}:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        # Only the FIRST segment. `ROOT / ".github" / "workflows"` is a
        # two-segment reference, but the filter's entries for .github are
        # file- and directory-specific, so comparing first segments alone
        # would call .github covered while .github/build-config.yml was not --
        # which is exactly the gap that existed. _is_covered handles that by
        # requiring a filter entry to cover the segment wholesale.
        for m in re.finditer(r'ROOT\s*/\s*"([A-Za-z0-9_.\-]+)"', text):
            refs[m.group(1)] += 1
        for m in re.finditer(r"\$\{REPO_ROOT\}/([A-Za-z0-9_.\-]+)", text):
            refs[m.group(1)] += 1
    return {k: v for k, v in refs.items() if v >= MIN_REFS}


def _is_covered(name: str, patterns: list[str]) -> bool:
    """Is every change under `name` guaranteed to run the suite?

    Deliberately strict for a directory: `.github/scripts/**` does NOT make
    `.github` covered, because a change to `.github/anything-else` would still
    run nothing. Only a wholesale entry counts. That strictness is the point --
    a partially-covered directory reads as covered otherwise, which is how
    `.github/build-config.yml` went twenty test files deep with no trigger.
    """
    for pat in patterns:
        if pat == name or pat == f"{name}/**":
            return True
        # A glob like Containerfile* covers Containerfile.el10.
        if pat.endswith("*") and not pat.endswith("/**"):
            if name.startswith(pat[:-1]):
                return True
    return False


def test_the_selectors_find_something():
    """Guard both sides: either matching nothing would make the assertion
    below vacuously true (tunaOS#1730)."""
    patterns = _filter_paths()
    assert patterns, "test.yml has no pull_request paths filter any more"
    reads = _paths_the_suite_reads()
    assert reads, "no repo paths parsed out of the test files"
    for known in ("build_scripts", "scripts", "manifests"):
        assert known in reads, (
            f"expected the suite to read {known}; parsed {sorted(reads)}")


@pytest.mark.parametrize(
    "name", sorted(n for n in _paths_the_suite_reads()
                   if n not in GATED_ELSEWHERE))
def test_a_path_the_suite_reads_also_triggers_the_suite(name: str):
    patterns = _filter_paths()
    assert _is_covered(name, patterns), (
        f"the test suite reads {name!r}, but test.yml's paths filter does not "
        f"match it, so a pull request changing only {name!r} runs no Unit "
        f"Tests and still shows every applicable check green.\n"
        f"Add it to the filter, or -- if a different workflow gates it "
        f"without a path filter, as `ste` does for prose -- add it to "
        f"GATED_ELSEWHERE with that reason."
    )
