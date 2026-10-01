"""tunaOS#2071: CI workflow steps downloaded unverified mutable yq latest binary.

Multiple GitHub Actions workflow files downloaded mikefarah/yq from
`releases/latest/download/yq_linux_amd64` directly into system binary paths
without an explicit version pin or checksum verification. Because the `latest`
redirect is mutable, upstream asset changes could compromise workflow
runners executing as root. All CI steps now route through the verified
`.github/actions/setup-yq` installer (or verify SHA-256 checksums before installation)
pinned to the repository-aligned `v4.53.3` release.

Falsification: structural -- reverting any workflow's yq download to an unpinned URL
or unverified download fails `test_no_workflow_downloads_latest_yq` or
`test_no_unverified_yq_downloads`.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
ACTIONS_DIR = ROOT / ".github" / "actions"

UNPINNED_YQ = re.compile(r"github\.com/mikefarah/yq/releases/latest/download")
YQ_DOWNLOAD = re.compile(r"(?:https?://)?github\.com/mikefarah/yq/releases/download/[^\s\"']+")


def _get_workflow_files() -> list[Path]:
    return sorted(
        [p for p in WORKFLOWS_DIR.iterdir() if p.suffix in (".yml", ".yaml")]
    )


def _get_action_files() -> list[Path]:
    return sorted(
        [p for p in ACTIONS_DIR.rglob("*") if p.suffix in (".yml", ".yaml")]
    )


def test_no_workflow_downloads_latest_yq():
    offenders = []
    for wf in _get_workflow_files():
        content = wf.read_text(encoding="utf-8")
        matches = UNPINNED_YQ.findall(content)
        if matches:
            offenders.append(f"{wf.name}: {len(matches)} unpinned yq download(s)")

    assert not offenders, (
        f"Found mutable yq latest downloads in workflow files:\n"
        + "\n".join(offenders)
    )


def test_no_action_downloads_latest_yq():
    offenders = []
    for act in _get_action_files():
        content = act.read_text(encoding="utf-8")
        matches = UNPINNED_YQ.findall(content)
        if matches:
            offenders.append(f"{act.name}: {len(matches)} unpinned yq download(s)")

    assert not offenders, (
        f"Found mutable yq latest downloads in action files:\n"
        + "\n".join(offenders)
    )


def test_no_unverified_yq_downloads():
    """Verify that any step directly downloading yq checks its SHA-256 hash."""
    offenders = []
    for p in _get_workflow_files() + _get_action_files():
        content = p.read_text(encoding="utf-8")
        if YQ_DOWNLOAD.search(content):
            if "sha256sum" not in content and "YQ_SHA256" not in content:
                offenders.append(
                    f"{p.relative_to(ROOT)}: downloads yq directly without SHA-256 verification"
                )

    assert not offenders, (
        f"Found unverified yq downloads without SHA-256 verification:\n"
        + "\n".join(offenders)
    )
