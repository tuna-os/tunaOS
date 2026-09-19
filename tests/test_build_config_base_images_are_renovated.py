"""Base-image pins must move deliberately instead of becoming stale silently.

The nightly reachability check catches garbage-collected digests, but it cannot
notice a still-resolving base that has drifted away from a rolling package
repository. Hummingbird demonstrated that distinction in #1754: its August base
still resolved in September, while Flatpak from the live package repository had
moved to libfuse3.so.4 and could no longer install on that base.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github/build-config.yml"
RENOVATE = ROOT / "renovate.json"

yaml = pytest.importorskip("yaml")


def _renovate_config() -> dict:
    return json.loads(RENOVATE.read_text(encoding="utf-8"))


def _base_image_manager(config: dict) -> dict:
    managers = [
        manager
        for manager in config["customManagers"]
        if any("build-config" in pattern for pattern in manager["managerFilePatterns"])
    ]
    assert len(managers) == 1, "build-config.yml needs exactly one digest updater"
    return managers[0]


def test_renovate_discovers_every_configured_base_image():
    renovate = _renovate_config()
    manager = _base_image_manager(renovate)

    assert manager["datasourceTemplate"] == "docker"
    assert manager["depNameTemplate"] == "{{{packageName}}}"

    # Renovate/RE2 spells named groups `(?<name>...)`; Python uses
    # `(?P<name>...)`. The rest of this deliberately exercises the configured
    # expression itself, so adding a new registry/path shape cannot silently
    # leave that base pinned forever.
    expression = re.sub(r"\(\?<([A-Za-z][A-Za-z0-9_]*)>", r"(?P<\1>", manager["matchStrings"][0])
    source = CONFIG.read_text(encoding="utf-8")
    matches = list(re.finditer(expression, source))

    variants = yaml.safe_load(source)["variants"]
    expected = {variant["base_image"] for variant in variants}
    found = {match.group(0).split('"', 1)[1].rsplit('"', 1)[0] for match in matches}

    assert found == expected, (
        "Renovate must discover every variants[].base_image digest; uncovered "
        "pins can keep resolving while drifting away from rolling repositories"
    )
    assert all(match.group("currentDigest").startswith("sha256:") for match in matches)


def test_base_image_updates_require_gate_review_instead_of_automerge():
    rules = _renovate_config()["packageRules"]
    blanket = next(
        index
        for index, rule in enumerate(rules)
        if rule.get("automerge") is True and "digest" in rule.get("matchUpdateTypes", [])
    )
    holds = [
        index
        for index, rule in enumerate(rules)
        if ".github/build-config.yml" in rule.get("matchFileNames", [])
        and rule.get("automerge") is False
    ]

    assert len(holds) == 1
    assert holds[0] > blanket, (
        "Renovate merges matching package rules in order; the base-image hold "
        "must override the blanket digest automerge rule"
    )
