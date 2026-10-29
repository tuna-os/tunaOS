"""tunaOS#2536 shipped mutable, unverified installer bytes in live media.

The live customization entrypoint downloaded a ``releases/latest`` Flatpak and
passed it directly to ``flatpak build-import-bundle``. The folded security
finding on #2536 measured both trust failures in ``customize-live.sh``.

Falsification: these behavioral tests fail if the real fetcher uses a mutable
URL, accepts bytes that do not match the architecture pin, or leaves a failed
download where the customization lifecycle can import it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FETCHER = ROOT / "live-iso" / "common" / "src" / "fetch-installer-bundle.sh"


def _write_fake_curl(directory: Path) -> None:
    curl = directory / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >"$CAPTURE"
out=""
while (($#)); do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
cp "$PAYLOAD" "$out"
"""
    )
    curl.chmod(0o755)


def _write_pins(path: Path, digest: str) -> None:
    path.write_text(
        f'''downloads:
  bootc_installer: "v2026.10.19-9f582fe0"
  bootc_installer_sha256:
    x86_64: "{digest}"
    aarch64: "{digest}"
'''
    )


def _run_fetcher(tmp_path: Path, arch: str, digest: str) -> tuple[subprocess.CompletedProcess[str], Path, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_curl(fake_bin)

    payload = tmp_path / "release.flatpak"
    payload.write_bytes(b"verified installer bundle fixture\n")
    pins = tmp_path / "image-versions.yaml"
    _write_pins(pins, digest)
    output = tmp_path / "installer.flatpak"
    capture = tmp_path / "curl-arguments"

    env = os.environ.copy()
    env.update(
        {
            "CAPTURE": str(capture),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "PAYLOAD": str(payload),
        }
    )
    result = subprocess.run(
        [str(FETCHER), str(pins), str(output), arch],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return result, output, capture.read_text() if capture.exists() else ""


@pytest.mark.parametrize(
    ("arch", "asset"),
    [
        ("x86_64", "org.bootcinstaller.Installer.flatpak"),
        ("aarch64", "org.bootcinstaller.Installer-aarch64.flatpak"),
    ],
)
def test_fetches_each_asset_from_the_exact_pinned_release(tmp_path: Path, arch: str, asset: str):
    digest = hashlib.sha256(b"verified installer bundle fixture\n").hexdigest()

    result, output, request = _run_fetcher(tmp_path, arch, digest)

    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == b"verified installer bundle fixture\n"
    assert f"/releases/download/v2026.10.19-9f582fe0/{asset}" in request
    assert "/releases/latest/" not in request


def test_checksum_mismatch_fails_closed_before_bundle_becomes_visible(tmp_path: Path):
    result, output, _ = _run_fetcher(tmp_path, "x86_64", "0" * 64)

    assert result.returncode != 0
    assert "FAILED" in result.stdout + result.stderr
    assert not output.exists()
    assert not Path(f"{output}.part").exists()


def test_unsupported_architecture_fails_before_any_download(tmp_path: Path):
    digest = hashlib.sha256(b"verified installer bundle fixture\n").hexdigest()

    result, output, request = _run_fetcher(tmp_path, "ppc64le", digest)

    assert result.returncode != 0
    assert "publishes no pinned asset for ppc64le" in result.stderr
    assert request == ""
    assert not output.exists()
