"""iso-e2e asked for `-latest-amd64.iso` for every generic AMD64 cell, but the
producer publishes the bare `-latest.iso` when the flavor has no v2 sibling
(yellowfin:cosmic has only generic AMD64). The consumer 404'd on a published ISO.

Both workflows now take the suffix from scripts/iso-latest-suffix.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "iso-latest-suffix.py"
PRODUCER = ROOT / ".github" / "workflows" / "reusable-build-artifacts.yml"
CONSUMER = ROOT / ".github" / "workflows" / "iso-e2e.yml"


def suffix(variant: str, flavor: str, platform: str) -> str:
    return subprocess.run(
        [sys.executable, str(HELPER), variant, flavor, platform],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout


@pytest.mark.parametrize(
    "variant,flavor,platform,expected",
    [
        ("yellowfin", "cosmic", "linux/amd64", ""),  # no v2 sibling: bare name
        ("yellowfin", "kde", "linux/amd64", "-amd64"),  # v2 owns the bare name
        ("yellowfin", "kde", "linux/amd64/v2", ""),
        ("yellowfin", "kde", "linux/arm64", "-arm64"),
    ],
)
def test_suffix_follows_the_producer_rule(variant, flavor, platform, expected):
    assert suffix(variant, flavor, platform) == expected


def test_unsupported_platform_fails():
    result = subprocess.run(
        [sys.executable, str(HELPER), "yellowfin", "kde", "linux/riscv64"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_both_workflows_name_objects_with_the_shared_helper():
    for path in (PRODUCER, CONSUMER):
        text = path.read_text(encoding="utf-8")
        assert "scripts/iso-latest-suffix.py" in text, path.name
        # No second, hand-written copy of the rule.
        assert 'PLATFORM_SUFFIX="-amd64"' not in text, path.name
        assert "latest-amd64.iso" not in text, path.name
