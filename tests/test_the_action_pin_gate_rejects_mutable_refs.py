#!/usr/bin/env python3
"""Unit tests for .github/scripts/check-action-pins.py.

lint.yml runs this script as the supply-chain gate that keeps every
third-party GitHub Action pinned to a full commit SHA: a mutable `@v4` can be
repointed by whoever owns the tag, so the gate is what stands between this
repository and someone else's force-push.

The gate itself had no tests. That is the uncomfortable half of a
supply-chain check -- a regression that makes it accept `@v4`, or stop
walking `.yaml` files, or skip anything after the first hit, does not fail
loudly. It goes green, which is exactly what a passing gate looks like.

These tests drive `main()` against a throwaway `.github` tree (the script
resolves its paths relative to the process working directory, so each case
chdirs into a tmp_path) and pin the four decisions it makes:

  * a 40-hex ref passes, in either case;
  * a tag, a branch, a short SHA, or a missing `@` fails;
  * `./local` and `docker://` references are deliberately exempt;
  * both `.yml` and `.yaml` are walked, at any depth, and every offending
    line is reported rather than only the first.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / ".github" / "scripts" / "check-action-pins.py"
_spec = importlib.util.spec_from_file_location("check_action_pins", _SCRIPT)
pins = importlib.util.module_from_spec(_spec)
sys.modules["check_action_pins"] = pins
_spec.loader.exec_module(pins)

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


@pytest.fixture
def workflows(tmp_path, monkeypatch):
    """Write .github workflow files into an empty tree and run there.

    Returns a writer taking `name -> text`; the gate is invoked with the
    process cwd set to the tree, which is how it finds `.github` at all.
    """
    monkeypatch.chdir(tmp_path)

    def write(name: str, text: str) -> Path:
        path = tmp_path / ".github" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    return write


def test_a_full_sha_passes(workflows, capsys):
    workflows(
        "workflows/build.yml",
        f"jobs:\n  a:\n    steps:\n      - uses: actions/checkout@{SHA}\n",
    )

    assert pins.main() == 0
    assert "pinned to full commit SHAs" in capsys.readouterr().out


def test_an_uppercase_sha_passes(workflows):
    """Git accepts either case for a hex object name, so the gate must too."""
    workflows("workflows/build.yml", f"      - uses: actions/checkout@{SHA.upper()}\n")

    assert pins.main() == 0


def test_a_trailing_version_comment_does_not_defeat_the_match(workflows):
    """The repository's own convention is `@<sha> # v7.0.1`; that must pass."""
    workflows("workflows/build.yml", f"      - uses: actions/checkout@{SHA} # v7.0.1\n")

    assert pins.main() == 0


def test_a_mutable_tag_fails(workflows, capsys):
    workflows("workflows/build.yml", "      - uses: actions/checkout@v4\n")

    assert pins.main() == 1
    err = capsys.readouterr().err
    assert "mutable action ref: actions/checkout@v4" in err
    assert ".github/workflows/build.yml:1" in err


def test_a_branch_ref_fails(workflows):
    workflows("workflows/build.yml", "      - uses: some/action@main\n")

    assert pins.main() == 1


def test_a_short_sha_fails(workflows, capsys):
    """A 12-hex prefix is not an immutable name: it can gain a sibling."""
    workflows("workflows/build.yml", f"      - uses: some/action@{SHA[:12]}\n")

    assert pins.main() == 1
    assert "mutable action ref" in capsys.readouterr().err


def test_a_reference_with_no_at_sign_fails_differently(workflows, capsys):
    """An unversioned `uses:` is a distinct mistake and says so."""
    workflows("workflows/build.yml", "      - uses: actions/checkout\n")

    assert pins.main() == 1
    err = capsys.readouterr().err
    assert "missing immutable SHA: actions/checkout" in err
    assert "mutable action ref" not in err


def test_a_local_composite_action_is_exempt(workflows):
    """`./.github/actions/*` is versioned by this repository's own commit."""
    workflows("workflows/build.yml", "      - uses: ./.github/actions/ghcr-login\n")

    assert pins.main() == 0


def test_a_docker_reference_is_exempt(workflows):
    workflows("workflows/build.yml", "      - uses: docker://alpine:3.20\n")

    assert pins.main() == 0


def test_yaml_files_are_walked_too(workflows, capsys):
    """content-filter.yaml and validate-renovate.yaml use the long suffix."""
    workflows("workflows/content-filter.yaml", "      - uses: actions/checkout@v4\n")

    assert pins.main() == 1
    assert "content-filter.yaml:1" in capsys.readouterr().err


def test_nested_action_definitions_are_walked(workflows, capsys):
    """Composite actions live at .github/actions/<name>/action.yml."""
    workflows(
        "actions/ghcr-login/action.yml",
        "runs:\n  steps:\n    - uses: docker/login-action@v3\n",
    )

    assert pins.main() == 1
    assert "actions/ghcr-login/action.yml:3" in capsys.readouterr().err


def test_a_uses_key_without_a_list_dash_is_matched(workflows):
    """A reusable-workflow `uses:` sits under `jobs.<id>:`, with no dash."""
    workflows(
        "workflows/build.yml",
        "jobs:\n  call:\n    uses: some/repo/.github/workflows/w.yml@v1\n",
    )

    assert pins.main() == 1


def test_every_offender_is_reported_not_only_the_first(workflows, capsys):
    workflows(
        "workflows/build.yml",
        "      - uses: actions/checkout@v4\n"
        f"      - uses: actions/cache@{SHA}\n"
        "      - uses: actions/setup-go@v5\n",
    )
    workflows("workflows/other.yml", "      - uses: actions/upload-artifact@v7\n")

    assert pins.main() == 1
    err = capsys.readouterr().err
    assert "actions/checkout@v4" in err
    assert "actions/setup-go@v5" in err
    assert "actions/upload-artifact@v7" in err
    # The one correctly pinned action is not reported.
    assert "actions/cache" not in err


def test_a_tree_with_no_workflows_passes(workflows):
    """No `.github` at all must not crash the gate."""
    assert pins.main() == 0


def test_the_repositorys_own_workflows_are_pinned():
    """The gate, run for real against this tree, is green.

    This is the assertion lint.yml makes on every push; keeping it here means
    a bad pin is caught by `just test` and not only by the lint job.
    """
    import os

    root = Path(__file__).resolve().parent.parent
    cwd = os.getcwd()
    os.chdir(root)
    try:
        assert pins.main() == 0
    finally:
        os.chdir(cwd)
