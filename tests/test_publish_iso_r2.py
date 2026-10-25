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


def test_checksum_mismatch_fails_before_policy_or_upload(tmp_path: Path) -> None:
    iso = tmp_path / "fish-20261024.iso"
    iso.write_bytes(b"iso bytes\n")
    (tmp_path / "fish-20261024.iso.sha256").write_text(
        f"{'0' * 64}  {iso.name}\n", encoding="utf-8"
    )
    (tmp_path / "fish-20261024.iso.sigstore.json").write_text(
        "{}\n", encoding="utf-8"
    )

    result = subprocess.run(
        [
            "bash", str(SCRIPT), str(iso), "fish-latest.iso",
            "/does/not/matter.json", "R2:bucket/prefix",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "signed checksum does not match ISO bytes" in result.stderr
