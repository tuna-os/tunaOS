"""tunaOS#3414: Debian toolchain executed mutable rustup bootstrap as root.

toolchain/Containerfile.debian previously piped the mutable https://sh.rustup.rs
bootstrap script directly into a root shell during container builds without
a version pin or independent checksum validation.

The toolchain builder now uses a pinned release of rustup-init (1.28.2),
checks architecture-specific SHA-256 sums with `sha256sum --check --strict`
before execution, and rejects remote pipeline execution.

Falsification: structural — reverting toolchain/Containerfile.debian to pipe
https://sh.rustup.rs into sh or removing the architecture checksum check fails
these assertions.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLCHAIN_CONTAINERFILE = ROOT / "toolchain" / "Containerfile.debian"
BUILD_TOOLCHAIN_WORKFLOW = ROOT / ".github" / "workflows" / "build-toolchain.yml"

EXPECTED_CHECKSUMS = {
    "amd64": (
        "x86_64-unknown-linux-gnu",
        "20a06e644b0d9bd2fbdbfd52d42540bdde820ea7df86e92e533c073da0cdd43c",
    ),
    "arm64": (
        "aarch64-unknown-linux-gnu",
        "e3853c5a252fca15252d07cb23a1bdd9377a8c6f3efa01531109281ae47f841c",
    ),
}

PIPE_TO_SHELL = re.compile(
    r"(curl|wget)[^|;&]*\|\s*(\\\s*\n\s*)?(sudo\s+)?(bash|sh)(\s|$)",
    re.MULTILINE,
)


def test_toolchain_does_not_execute_mutable_remote_script() -> None:
    content = TOOLCHAIN_CONTAINERFILE.read_text(encoding="utf-8")
    assert "https://sh.rustup.rs" not in content
    assert "sh.rustup.rs" not in content
    assert not PIPE_TO_SHELL.search(content), "found curl|sh pipeline in toolchain Containerfile"


def test_toolchain_pins_rustup_version_and_targetarch() -> None:
    content = TOOLCHAIN_CONTAINERFILE.read_text(encoding="utf-8")
    assert "ARG RUSTUP_VERSION=1.28.2" in content
    assert "ARG TARGETARCH" in content
    assert 'https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/${RUSTUP_ARCH}/rustup-init' in content


def test_toolchain_verifies_checksums_per_architecture() -> None:
    content = TOOLCHAIN_CONTAINERFILE.read_text(encoding="utf-8")

    for arch, (rustup_arch, sha256) in EXPECTED_CHECKSUMS.items():
        assert f"RUSTUP_ARCH={rustup_arch}" in content
        assert f"RUSTUP_SHA256={sha256}" in content

    assert 'Unsupported Rustup architecture: ${TARGETARCH}' in content
    assert 'echo "${RUSTUP_SHA256}  /tmp/rustup-init" | sha256sum --check --strict' in content
    assert "/tmp/rustup-init -y --profile minimal" in content
    assert "rm -f /tmp/rustup-init" in content


def test_workflow_supplies_targetarch_build_arg() -> None:
    workflow = BUILD_TOOLCHAIN_WORKFLOW.read_text(encoding="utf-8")
    assert '--build-arg TARGETARCH="${{ matrix.arch }}"' in workflow
