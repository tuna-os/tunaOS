"""tunaOS#3414: Debian toolchain executes mutable rustup bootstrap as root.

toolchain/Containerfile.debian previously downloaded and executed the unpinned,
unverified bootstrap script from https://sh.rustup.rs with root privileges
during the Debian toolchain container build:

    RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \\
            sh -s -- --profile minimal -y

The script controls the Rust toolchain builder that compiles bootc, bootupd,
and libostree, and publishes the output as an OCI artifact consumed by image
builds.

The fix replaces the remote shell pipeline with a versioned, checksum-verified
installer (rustup-init) pinned to RUSTUP_VERSION and verified with sha256sum
--check --strict for each supported architecture (amd64 and arm64).

Falsification: structural — revert toolchain/Containerfile.debian to pipe
https://sh.rustup.rs into sh; this test detects the pipe to shell, the absence
of RUSTUP_SHA256 checksum verification, and fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTAINERFILE = ROOT / "toolchain" / "Containerfile.debian"
RENOVATE_JSON = ROOT / "renovate.json"

EXPECTED_SHA256 = {
    "amd64": "20a06e644b0d9bd2fbdbfd52d42540bdde820ea7df86e92e533c073da0cdd43c",
    "arm64": "e3853c5a252fca15252d07cb23a1bdd9377a8c6f3efa01531109281ae47f841c",
}


def test_toolchain_containerfile_does_not_pipe_to_shell() -> None:
    """No curl/wget piped to sh/bash, including multi-line continuations."""
    content = CONTAINERFILE.read_text(encoding="utf-8")
    assert "sh.rustup.rs" not in content, (
        "toolchain/Containerfile.debian must not fetch from mutable sh.rustup.rs"
    )

    # Normalize line continuations (\ + newline) to detect multi-line pipes
    normalized = re.sub(r"\\\s*\n\s*", " ", content)
    pipe_pattern = re.compile(
        r"(curl|wget)[^|;&]*\|\s*(sudo\s+)?(bash|sh)(\s|$)"
    )
    m = pipe_pattern.search(normalized)
    assert m is None, (
        f"toolchain/Containerfile.debian pipes remote download into shell: {m.group(0) if m else ''}"
    )


def test_toolchain_containerfile_pins_rustup_version_and_checksums() -> None:
    """rustup-init is versioned and verified against pinned sha256 hashes."""
    content = CONTAINERFILE.read_text(encoding="utf-8")

    m_ver = re.search(r"^ARG RUSTUP_VERSION=([0-9.]+)", content, re.MULTILINE)
    assert m_ver, "toolchain/Containerfile.debian must define ARG RUSTUP_VERSION"
    version = m_ver.group(1)
    assert version == "1.28.2", f"unexpected RUSTUP_VERSION: {version}"

    assert "ARG TARGETARCH" in content, (
        "toolchain/Containerfile.debian must declare ARG TARGETARCH"
    )

    for arch, expected_hash in EXPECTED_SHA256.items():
        m_hash = re.search(
            rf"{arch}\).*?RUSTUP_SHA256=([0-9a-f]{{64}})", content, re.DOTALL
        )
        assert m_hash, f"missing RUSTUP_SHA256 for {arch}"
        actual_hash = m_hash.group(1)
        assert actual_hash == expected_hash, (
            f"RUSTUP_SHA256 for {arch} is {actual_hash}, expected {expected_hash}"
        )

    assert "sha256sum --check --strict" in content, (
        "toolchain/Containerfile.debian must verify rustup-init with sha256sum --check --strict"
    )


def test_toolchain_versions_record_rustup() -> None:
    """Provenance file /output/.toolchain-versions records rustup version."""
    content = CONTAINERFILE.read_text(encoding="utf-8")
    assert "rustup=%s" in content, (
        "toolchain/Containerfile.debian must record rustup version in /output/.toolchain-versions"
    )


def test_renovate_configuration_guards_rustup() -> None:
    """Renovate must track rust-lang/rustup without automerging checksum bumps."""
    content = CONTAINERFILE.read_text(encoding="utf-8")
    assert "# renovate: datasource=github-tags depName=rust-lang/rustup" in content, (
        "toolchain/Containerfile.debian must carry a Renovate marker for rust-lang/rustup"
    )

    cfg = json.loads(RENOVATE_JSON.read_text(encoding="utf-8"))
    automerge_disabled = False
    for rule in cfg.get("packageRules", []):
        if "rust-lang/rustup" in (rule.get("matchDepNames") or []):
            if rule.get("automerge") is False:
                automerge_disabled = True
    assert automerge_disabled, (
        "renovate.json must hold rust-lang/rustup at automerge: false"
    )
