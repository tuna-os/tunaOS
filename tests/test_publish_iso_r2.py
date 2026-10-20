"""Publication names must remain safe basenames before any upload work."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/publish-iso-r2.sh"


@pytest.mark.parametrize(
    ("iso", "latest"),
    [
        ("/tmp/unsafe name.iso", "good.iso"),
        ("/tmp/good.iso", "../bad.iso"),
        ("/tmp/good.iso", "bad\nname.iso"),
    ],
)
def test_unsafe_publication_names_fail_before_artifact_checks(iso: str, latest: str) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), iso, latest, "/tmp/unused-config.json", "R2:bucket/prefix"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "safe single-line basenames" in result.stderr


def test_github_actions_failures_emit_error_annotations() -> None:
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "/tmp/unsafe name.iso",
            "good.iso",
            "/tmp/unused-config.json",
            "R2:bucket/prefix",
        ],
        capture_output=True,
        text=True,
        env={"GITHUB_ACTIONS": "true", "PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 2
    assert result.stderr.startswith("::error::")
