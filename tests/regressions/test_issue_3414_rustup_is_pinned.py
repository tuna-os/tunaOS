"""tunaOS#3414: the Debian toolchain must not pipe a mutable rustup script.

The toolchain build runs as root and publishes the resulting Rust-built
binaries. Keep the installer release and both supported architecture hashes
explicit so a bootstrap endpoint change cannot silently alter the build.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTAINERFILE = ROOT / "toolchain" / "Containerfile.debian"

EXPECTED_HASHES = {
    "20a06e644b0d9bd2fbdbfd52d42540bdde820ea7df86e92e533c073da0cdd43c",
    "e3853c5a252fca15252d07cb23a1bdd9377a8c6f3efa01531109281ae47f841c",
}


def test_rustup_bootstrap_is_release_pinned_and_verified() -> None:
    content = CONTAINERFILE.read_text(encoding="utf-8")

    assert "https://sh.rustup.rs" not in content
    assert "ARG RUSTUP_VERSION=1.28.2" in content
    assert (
        "https://static.rust-lang.org/rustup/archive/"
        "${RUSTUP_VERSION}/${RUSTUP_ARCH}/rustup-init"
    ) in content
    assert "sha256sum --check --strict" in content
    assert all(expected_hash in content for expected_hash in EXPECTED_HASHES)
    assert "rustup-init -y --profile minimal" in content
