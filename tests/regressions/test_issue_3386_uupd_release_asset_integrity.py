"""tunaOS#3386: verify uupd release assets and systemd units before installing into images.

build_scripts/10-base-packages.sh previously downloaded the ublue-os/uupd release
archive for apt and dnf image builds without integrity verification and extracted
it directly into /usr/bin. It also fetched systemd units from a mutable tag.

Falsification: behavioral — the test drives install-uupd.sh with mismatched archive
and unit checksums, verifying it fails closed before writing to the target root.
"""

from __future__ import annotations

import hashlib
import io
import os
import stat
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_PACKAGES = ROOT / "build_scripts" / "10-base-packages.sh"
INSTALLER = ROOT / "build_scripts" / "install-uupd.sh"
UNITS = ("uupd.service", "uupd.timer", "uupd-manual.service")


def _fake_curl(bin_dir: Path, archive: Path, unit_contents: dict[str, bytes] | None = None) -> None:
    contents = unit_contents or {u: f"[Unit]\nDescription={u}\n".encode("utf-8") for u in UNITS}
    encoded = {k: v.decode("utf-8") for k, v in contents.items()}

    script = f"""#!/usr/bin/env python3
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
out = Path(args[args.index('-o') + 1])
url = args[-1]
units = {encoded!r}

if url.endswith('.tar.gz'):
    shutil.copyfile(Path({str(archive)!r}), out)
else:
    unit_name = url.rsplit('/', 1)[-1]
    out.write_text(units.get(unit_name, '[Unit]\\nDescription=' + unit_name + '\\n'))
"""
    (bin_dir / "curl").write_text(script, encoding="utf-8")
    mode = (bin_dir / "curl").stat().st_mode
    (bin_dir / "curl").chmod(mode | stat.S_IXUSR)


def _make_archive(path: Path) -> str:
    payload = b'#!/bin/sh\n[ "${1:-}" = --help ]\n'
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("uupd")
        info.mode = 0o755
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_base_packages_delegates_both_apt_and_dnf_paths_to_installer() -> None:
    text = BASE_PACKAGES.read_text(encoding="utf-8")
    apt_marker = 'if [[ "$PKG_MGR" == "apt" ]]; then'
    dnf_marker = "# ── dnf (RPM) path continues below ──"

    assert apt_marker in text
    assert dnf_marker in text

    apt_path, dnf_path = text.split(dnf_marker, 1)

    assert "/run/context/build_scripts/install-uupd.sh" in apt_path
    assert "https://github.com/ublue-os/uupd/releases/download" not in apt_path
    assert "tar -xzf" not in apt_path

    assert "/run/context/build_scripts/install-uupd.sh" in dnf_path
    assert "https://github.com/ublue-os/uupd/releases/download" not in dnf_path
    assert "tar -xzf" not in dnf_path


def test_installer_fails_closed_when_archive_checksum_mismatches(tmp_path: Path) -> None:
    context = tmp_path / "context"
    image = tmp_path / "image"
    fake_bin = tmp_path / "bin"
    context.mkdir()
    fake_bin.mkdir()

    archive = tmp_path / "uupd.tar.gz"
    _make_archive(archive)
    _fake_curl(fake_bin, archive)

    bad_hash = "0" * 64
    (context / "image-versions.yaml").write_text(
        f"""downloads:
  uupd: "v1.5.1"
  uupd_sha256:
    x86_64: "{bad_hash}"
    aarch64: "{bad_hash}"
  uupd_units_sha256:
    uupd.service: "{"a" * 64}"
    uupd.timer: "{"a" * 64}"
    uupd-manual.service: "{"a" * 64}"
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "UUPD_CONTEXT": str(context),
            "UUPD_ROOT": str(image),
        }
    )
    result = subprocess.run(
        [str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "FAILED" in result.stdout + result.stderr
    assert not (image / "usr/bin/uupd").exists()
    assert not (image / "usr/lib/systemd/system/uupd.service").exists()


def test_installer_fails_closed_when_unit_checksum_mismatches(tmp_path: Path) -> None:
    context = tmp_path / "context"
    image = tmp_path / "image"
    fake_bin = tmp_path / "bin"
    context.mkdir()
    fake_bin.mkdir()

    archive = tmp_path / "uupd.tar.gz"
    archive_sha = _make_archive(archive)
    _fake_curl(fake_bin, archive)

    bad_hash = "f" * 64
    (context / "image-versions.yaml").write_text(
        f"""downloads:
  uupd: "v1.5.1"
  uupd_sha256:
    x86_64: "{archive_sha}"
    aarch64: "{archive_sha}"
  uupd_units_sha256:
    uupd.service: "{bad_hash}"
    uupd.timer: "{bad_hash}"
    uupd-manual.service: "{bad_hash}"
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "UUPD_CONTEXT": str(context),
            "UUPD_ROOT": str(image),
        }
    )
    result = subprocess.run(
        [str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "FAILED" in result.stdout + result.stderr
    assert not (image / "usr/bin/uupd").exists()
    assert not (image / "usr/lib/systemd/system/uupd.service").exists()


def test_installer_succeeds_when_all_checksums_match(tmp_path: Path) -> None:
    context = tmp_path / "context"
    image = tmp_path / "image"
    fake_bin = tmp_path / "bin"
    context.mkdir()
    fake_bin.mkdir()

    archive = tmp_path / "uupd.tar.gz"
    archive_sha = _make_archive(archive)

    unit_contents = {u: f"[Unit]\nDescription=verified {u}\n".encode("utf-8") for u in UNITS}
    unit_hashes = {u: hashlib.sha256(data).hexdigest() for u, data in unit_contents.items()}
    _fake_curl(fake_bin, archive, unit_contents=unit_contents)

    (context / "image-versions.yaml").write_text(
        f"""downloads:
  uupd: "v1.5.1"
  uupd_sha256:
    x86_64: "{archive_sha}"
    aarch64: "{archive_sha}"
  uupd_units_sha256:
    uupd.service: "{unit_hashes['uupd.service']}"
    uupd.timer: "{unit_hashes['uupd.timer']}"
    uupd-manual.service: "{unit_hashes['uupd-manual.service']}"
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "UUPD_CONTEXT": str(context),
            "UUPD_ROOT": str(image),
        }
    )
    result = subprocess.run(
        [str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (image / "usr/bin/uupd").is_file()
    assert (image / "usr/bin/uupd").stat().st_mode & stat.S_IXUSR
    for unit in UNITS:
        installed = image / "usr/lib/systemd/system" / unit
        assert installed.is_file()
        assert f"verified {unit}" in installed.read_text(encoding="utf-8")
