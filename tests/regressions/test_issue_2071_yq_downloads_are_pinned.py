"""tunaOS#2071: CI workflow steps downloaded unverified mutable yq latest binary.

Multiple GitHub Actions workflow files downloaded mikefarah/yq from
`releases/latest/download/yq_linux_amd64` directly into system binary paths
without an explicit version pin or checksum verification. Because the `latest`
redirect is mutable, upstream asset changes could compromise workflow
runners executing as root. All CI steps now pin to the repository-aligned
`v4.53.3` release.

Falsification: structural -- reverting any workflow's yq download URL back to
`releases/latest/download/yq_linux_amd64` fails `test_no_workflow_downloads_latest_yq`.
"""

from __future__ import annotations

import re
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
ACTIONS_DIR = ROOT / ".github" / "actions"

UNPINNED_YQ = re.compile(r"github\.com/mikefarah/yq/releases/latest/download")


def test_no_workflow_downloads_latest_yq():
    offenders = []
    for wf in sorted(WORKFLOWS_DIR.glob("*.yml")):
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
    for act in sorted(ACTIONS_DIR.rglob("*.yml")):
        content = act.read_text(encoding="utf-8")
        matches = UNPINNED_YQ.findall(content)
        if matches:
            offenders.append(f"{act.name}: {len(matches)} unpinned yq download(s)")

    assert not offenders, (
        f"Found mutable yq latest downloads in action files:\n"
        + "\n".join(offenders)
    )
