"""tunaOS#3406: Debian and Ubuntu images consumed mutable toolchain aliases.

The image build already passes the Renovate-controlled ``BOOTC_VERSION`` build
argument, but both Containerfiles previously ignored it and pulled
``latest-${TARGETARCH}`` OCI tags. This test holds the consumer-side contract:
the reference must contain the pinned version and must not resolve a mutable
latest alias.

Falsification: structural — revert either Containerfile's pull reference to
``latest-${TARGETARCH}`` or remove its ``BOOTC_VERSION`` argument, and the
corresponding assertion fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTAINERFILES = (ROOT / "Containerfile.debian", ROOT / "Containerfile.ubuntu")
MUTABLE_ALIAS = ":latest-${TARGETARCH}"


@pytest.mark.parametrize("containerfile", CONTAINERFILES, ids=lambda path: path.name)
def test_toolchain_pull_uses_pinned_bootc_version(containerfile: Path) -> None:
    content = containerfile.read_text(encoding="utf-8")

    assert "ARG BOOTC_VERSION" in content
    assert MUTABLE_ALIAS not in content
    assert "${BOOTC_VERSION}-${TARGETARCH}" in content

    pull_lines = [line for line in content.splitlines() if "oras pull" in line]
    assert len(pull_lines) == 1
    assert "${BOOTC_VERSION}-${TARGETARCH}" in pull_lines[0]
