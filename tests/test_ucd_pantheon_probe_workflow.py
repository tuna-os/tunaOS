"""The Pantheon-on-UCD probe builds and packs; it never publishes.

docs/UBUNTU-CORE-DESKTOP.md ("Pantheon on Ubuntu Core Desktop") describes
`ucd-pantheon-probe.yml`: a by-hand experiment with a `snapcraft pack` and an
Actions artifact. These tests pin the shape that keeps it harmless.

Falsification: add a `schedule:` or `pull_request:` trigger, widen
`permissions`, or add a release, registry push or Snap Store upload, and a
test below fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ucd-pantheon-probe.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC = yaml.safe_load(TEXT)
# PyYAML resolves the bare key `on:` to the boolean True.
ON = DOC.get("on", DOC.get(True))


def _code() -> str:
    """The workflow without comment lines, which may name what is forbidden."""
    return "\n".join(line for line in TEXT.splitlines() if not line.lstrip().startswith("#"))


def test_dispatch_is_the_only_trigger():
    assert set(ON) == {"workflow_dispatch"}


def test_token_is_read_only():
    assert DOC["permissions"] == {"contents": "read"}
    for name, job in DOC["jobs"].items():
        assert "permissions" not in job, f"job {name} widens the token"


def test_nothing_publishes():
    code = _code()
    forbidden = [
        r"gh release",
        r"docker push",
        r"podman push",
        r"snapcraft (upload|release|push)",
        r"secrets\.",
        r"packages:\s*write",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, code), f"workflow matches {pattern!r}"
