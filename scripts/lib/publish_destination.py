"""Python seam over scripts/publish-destination.sh.

That script is the one resolver of where images publish (IMAGE_REGISTRY /
REPO_ORGANIZATION, then [build.publish] in tunaos.toml, then the GitHub
repository owner, then the stock destination; precedence in
scripts/lib/publish-destination.sh). Python tooling asks it instead of
carrying a second copy of the rules.
"""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "publish-destination.sh"


@lru_cache(maxsize=None)
def publish_destination() -> str:
    """The "<registry>/<namespace>" images publish to."""
    return subprocess.run(
        ["bash", str(SCRIPT)], check=True, stdout=subprocess.PIPE, text=True
    ).stdout.strip()


def registry_and_namespace() -> tuple[str, str]:
    registry, _, namespace = publish_destination().partition("/")
    return registry, namespace
