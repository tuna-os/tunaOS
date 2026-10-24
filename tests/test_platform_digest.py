"""Platform digests must describe the image actually in local storage."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/lib/platform-digest.sh"


@pytest.mark.parametrize(
    ("image", "platform", "architecture"),
    [
        ("ghcr.io/tuna-os/yellowfin:gnome", "linux/amd64", "amd64"),
        ("localhost/tunaos:dev", "linux/arm64", "arm64"),
    ],
)
def test_resolves_digest_from_the_local_store_for_registry_and_local_images(
    tmp_path: Path, image: str, platform: str, architecture: str
) -> None:
    digest = "sha256:" + "a" * 64
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "skopeo").write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" > \"$DIGEST_ARGS\"\n"
        f"printf '%s\\n' '{digest}'\n",
        encoding="utf-8",
    )
    (bin_dir / "skopeo").chmod(0o755)
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}", "DIGEST_ARGS": str(tmp_path / "args")}
    result = subprocess.run(
        [
            "bash",
            "-euc",
            'source "$1"; platform_manifest_digest "$2" "$3"',
            "platform-digest-test",
            str(HELPER),
            image,
            platform,
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.strip() == digest
    args = (tmp_path / "args").read_text(encoding="utf-8")
    assert f"containers-storage:{image}" in args
    assert f"--override-arch {architecture}" in args
    assert "--override-os linux" in args


def test_reports_skopeo_failure_cause(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "skopeo").write_text(
        "#!/usr/bin/env bash\n"
        "echo 'denied: local image is missing' >&2\n"
        "exit 17\n",
        encoding="utf-8",
    )
    (bin_dir / "skopeo").chmod(0o755)
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    result = subprocess.run(
        [
            "bash",
            "-euc",
            'source "$1"; platform_manifest_digest "$2" "$3"',
            "platform-digest-test",
            str(HELPER),
            "localhost/tunaos:missing",
            "linux/amd64",
        ],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "cannot resolve linux/amd64" in result.stderr
