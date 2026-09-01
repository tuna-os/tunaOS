"""GitHub CLI transport for the matrix-status generator.

Keep process execution and retry policy out of the status-domain module.  The
adapter intentionally returns ``None`` after exhausted JSON retries because
that is the generator's established absence-of-data contract.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


class GitHubClient:
    """Small adapter around the GitHub CLI operations used by the report."""

    def json(self, *args: str):
        """Run ``gh`` and parse JSON, retrying transient and decode failures."""
        for attempt in range(3):
            try:
                out = subprocess.run(
                    ["gh", *args], capture_output=True, text=True, check=True
                ).stdout
                return json.loads(out) if out.strip() else None
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                if attempt == 2:
                    return None
                time.sleep(2)
        return None

    def download_artifact(
        self, repo: str, run_id: str, artifact: str, destination: Path
    ) -> bool:
        """Download one run artifact, returning whether the CLI succeeded."""
        try:
            subprocess.run(
                [
                    "gh", "run", "download", run_id,
                    "--repo", repo,
                    "--name", artifact,
                    "--dir", str(destination),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            return False
        return True
