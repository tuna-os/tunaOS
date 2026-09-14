"""The R2 prune must never delete a `-latest` pointer, for ANY platform.

`prune-r2.yml` (#1619, for #1618) deletes dated objects out of the shared R2
bucket and keeps the stable `-latest` names that documentation and smoke tests
`wget` by hand. It expressed "keep the pointers" as

    --exclude "*-latest.iso*"

which needs the literal string `-latest.iso`. Non-amd64 ISOs do not have it.
`reusable-build-artifacts.yml` publishes an arch-suffixed pointer for every
platform that is not linux/amd64 (#1378), so the real pointer set is

    bonito-gnome-latest.iso              <- matched the exclude
    bonito-gnome-latest-arm64.iso        <- did NOT
    bonito-gnome-latest-arm64.iso.sha256          <- did NOT, and matched
    bonito-gnome-latest-arm64.iso.sigstore.json   <- `--include "*.iso*"`

An arch-suffixed pointer was therefore deletable the moment its mtime crossed
14 days: the first time an arm64 leg went two weeks without a green build,
the daily prune would remove the exact object whose whole job is to stay put
while builds are broken.

This test is the rule rather than the one fix. It harvests the pointer names
the upload workflows actually construct -- expanding `${{ }}` and shell
expansions to placeholders, so a NEW pointer shape is picked up by existing
code instead of needing a new case here -- and replays every prune step's
filter list against them. A pointer that any prune step would delete fails.

The negative controls matter as much: dated objects must still be deleted.
An exclude of `*` would satisfy the rule above and prune nothing, which is the
other way to get this wrong.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PRUNE = WORKFLOWS / "prune-r2.yml"

# Every expansion collapses to one placeholder. The test is about the SHAPE of
# the name around "-latest", not about resolving variant/flavor/arch: any
# non-empty value produces the same verdict from a glob, and pretending to
# know the real matrix here would just be a second copy of build-config.yml.
PLACEHOLDER = "sample"
GH_EXPR = re.compile(r"\$\{\{.*?\}\}")
SHELL_VAR = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*[^{}]*\}|\$[A-Za-z_][A-Za-z0-9_]*")

# Quoted shell tokens that mention "latest" in any case -- `-latest.iso` in a
# path, or `${LATEST}` in the sidecar names built from it.
LATEST_TOKEN = re.compile(r'"([^"\n]*[Ll][Aa][Tt][Ee][Ss][Tt][^"\n]*)"')
LATEST_ASSIGN = re.compile(r'LATEST="([^"\n]+)"')

# What an R2 object looks like. `runs-on: ubuntu-latest` and image tags mention
# "latest" too; only names ending in an artifact suffix are objects in a bucket.
ARTIFACT_SUFFIXES = (".iso", ".png", ".sha256", ".sigstore.json")


def _expand(token: str, latest_values: list[str]) -> list[str]:
    """One shell token -> the concrete object name(s) it can produce."""
    token = GH_EXPR.sub(PLACEHOLDER, token)
    candidates = [token]
    if "LATEST" in token:
        # `"${LATEST}.sha256"` is a pointer sidecar, and its name only carries
        # "-latest" once LATEST itself is substituted. Without this the sidecars
        # -- the half that `--include "*.iso.sha256"` made deletable -- would
        # silently drop out of the corpus.
        candidates = [
            token.replace("${LATEST}", v).replace("$LATEST", v) for v in latest_values
        ] or candidates
    out = []
    for c in candidates:
        name = SHELL_VAR.sub(PLACEHOLDER, c).rsplit("/", 1)[-1]
        if "-latest" in name and name.endswith(ARTIFACT_SUFFIXES):
            out.append(name)
    return out


def pointer_names() -> set[str]:
    """Every `-latest` object name the workflows in this repo write."""
    found: set[str] = set()
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        if wf.name == PRUNE.name:
            continue
        text = wf.read_text(encoding="utf-8")
        latest_values = [
            v
            for raw in LATEST_ASSIGN.findall(text)
            for v in _expand(raw, [])
        ]
        for token in LATEST_TOKEN.findall(text):
            found.update(_expand(token, latest_values))
        found.update(latest_values)
    return found


def prune_steps() -> list[tuple[str, str, list[tuple[str, str]]]]:
    """(step name, pruned prefix, ordered filter rules) for each delete step."""
    doc = yaml.safe_load(PRUNE.read_text(encoding="utf-8"))
    steps = []
    for step in doc["jobs"]["prune"]["steps"]:
        run = step.get("run", "")
        if "rclone delete" not in run:
            continue
        # Shell comments out first. The step explains WHY the exclude reads
        # the way it does, quoting the `--include "*.iso"` that made the
        # arch-suffixed sidecars deletable -- and a rule scraped out of that
        # prose would be read as a real filter, in the wrong order, making the
        # test fail on a workflow that is correct.
        code = "\n".join(
            line for line in run.splitlines() if not line.lstrip().startswith("#")
        )
        prefix = re.search(r'R2:\$\{\{[^}]*\}\}/([^"\s]+)', code)
        rules = [
            (kind, pattern)
            for kind, pattern in re.findall(r'--(exclude|include) "([^"]+)"', code)
        ]
        steps.append((step.get("name", "?"), prefix.group(1) if prefix else "?", rules))
    return steps


def verdict(name: str, rules: list[tuple[str, str]]) -> str:
    """Replay rclone's filter semantics for one object name.

    First matching rule wins. A matching `--exclude` skips the object (for
    `rclone delete`, that means the object survives); a matching `--include`
    selects it for deletion. If nothing matches, rclone appends an implicit
    `--exclude *` when any `--include` was given, and otherwise defaults to
    including everything.

    Matched against the basename: rclone patterns without a leading `/` apply
    at any directory level, which is what lets one recursive pass cover
    `screenshots/boot/`, and fnmatch on the basename is equivalent for the
    single-segment patterns this workflow uses.
    """
    for kind, pattern in rules:
        if fnmatch.fnmatch(name, pattern):
            return "keep" if kind == "exclude" else "delete"
    return "keep" if any(kind == "include" for kind, _ in rules) else "delete"


def test_the_corpus_is_not_empty():
    """Guard: a sweep that matches nothing passes for the wrong reason."""
    names = pointer_names()
    assert len(names) >= 4, f"only harvested {names}; token parser broken?"
    assert any(n.endswith(".iso") for n in names)
    assert any(n.endswith(".png") for n in names)
    assert any(n.endswith(".sha256") for n in names), "pointer sidecars missing"


def test_the_arch_suffixed_pointer_is_in_the_corpus():
    """The shape that broke it: `-latest-<arch>.iso`, not `-latest.iso`.

    Separate from the count guard above because this is the specific thing
    `*-latest.iso*` could not see. If the arch-suffixed pointer ever stops
    being harvested, the regression test below goes green while protecting
    nothing.
    """
    names = pointer_names()
    assert any(re.search(r"-latest-[^.]+\.iso$", n) for n in names), (
        f"no arch-suffixed pointer harvested from the upload workflows: {sorted(names)}"
    )


def test_there_are_prune_steps_to_check():
    steps = prune_steps()
    assert len(steps) >= 2, f"expected the ISO and screenshot prunes, got {steps}"
    for name, prefix, rules in steps:
        assert rules, f"{name!r} deletes from {prefix!r} with no filters at all"


@pytest.mark.parametrize("name", sorted(pointer_names()))
def test_no_prune_step_deletes_a_latest_pointer(name):
    for step, prefix, rules in prune_steps():
        assert verdict(name, rules) == "keep", (
            f"{step!r} (prunes {prefix}) would delete the stable pointer {name!r} "
            f"with rules {rules}"
        )


@pytest.mark.parametrize(
    "name,prefix",
    [
        # Dated ISO and its sidecars: the whole point of the 14-day window.
        ("bonito-gnome-20260914.iso", "live-isos/"),
        ("bonito-gnome-20260914.iso.sha256", "live-isos/"),
        ("bonito-gnome-20260914.iso.sigstore.json", "live-isos/"),
        # Arch-suffixed DATED ISOs are ordinary builds, not pointers.
        ("bonito-gnome-20260914-arm64.iso", "live-isos/"),
        ("yellowfin-gnome-20260914.png", "screenshots/"),
    ],
)
def test_dated_objects_are_still_deleted(name, prefix):
    """The other way to get this wrong: keep everything and prune nothing.

    An `--exclude "*"` satisfies "never delete a pointer" perfectly while
    leaving #1618's actual retention gap wide open, so the keep-rule above is
    only meaningful next to this one.
    """
    steps = [s for s in prune_steps() if s[1] == prefix]
    assert steps, f"no prune step covers {prefix}"
    for step, _, rules in steps:
        assert verdict(name, rules) == "delete", (
            f"{step!r} would keep dated object {name!r} forever; rules {rules}"
        )
