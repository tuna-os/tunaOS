"""tunaOS#3356: Marlin shipped uupd triggers without uupd itself.

The common system-files layer supplies uupd's timer and AC-power trigger, but
Containerfile.arch did not run the package phase that installs the binary and
core units. The resulting image reported a failed uupd-on-ac.service on every
AC event.

Falsification: behavioural — the installer test fails if the shared installer
stops extracting the binary or writing any core unit; the wiring test fails if
Containerfile.arch no longer carries the pinned version file or invokes that
installer before service setup.
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
INSTALLER = ROOT / "build_scripts" / "install-uupd.sh"
CONTAINERFILE = ROOT / "Containerfile.arch"


def _fake_curl(bin_dir: Path, archive: Path) -> None:
    (bin_dir / "curl").write_text(
        """#!/usr/bin/env python3
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
out = Path(args[args.index('-o') + 1])
url = args[-1]
if url.endswith('.tar.gz'):
    shutil.copyfile(Path(__ARCHIVE__), out)
else:
    out.write_text('[Unit]\\nDescription=' + url.rsplit('/', 1)[-1] + '\\n')
""".replace("__ARCHIVE__", repr(str(archive))),
        encoding="utf-8",
    )
    mode = (bin_dir / "curl").stat().st_mode
    (bin_dir / "curl").chmod(mode | stat.S_IXUSR)


def test_arch_carries_the_pin_and_installs_uupd_before_services() -> None:
    text = CONTAINERFILE.read_text(encoding="utf-8")
    assert "COPY image-versions.yaml /image-versions.yaml" in text
    common_copy = text.index("COPY --from=common /system_files/shared /")
    installer = text.index("/run/context/build_scripts/install-uupd.sh")
    services = text.index("/run/context/build_scripts/40-services.sh")
    assert common_copy < installer < services


def test_uupd_installer_lays_down_binary_and_core_units(tmp_path: Path) -> None:
    context = tmp_path / "context"
    image = tmp_path / "image"
    fake_bin = tmp_path / "bin"
    context.mkdir()
    fake_bin.mkdir()
    archive = tmp_path / "uupd.tar.gz"
    payload = b"#!/bin/sh\n[ \"${1:-}\" = --help ]\n"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("uupd")
        info.mode = 0o755
        info.size = len(payload)

        tar.addfile(info, io.BytesIO(payload))
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()

    unit_hashes = {}
    for unit in ("uupd.service", "uupd.timer", "uupd-manual.service"):
        unit_hashes[unit] = hashlib.sha256(
            f"[Unit]\nDescription={unit}\n".encode("utf-8")
        ).hexdigest()

    (context / "image-versions.yaml").write_text(
        f"""downloads:
  uupd: "v1.5.0"
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
    _fake_curl(fake_bin, archive)

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
    for unit in ("uupd.service", "uupd.timer", "uupd-manual.service"):
        installed = image / "usr/lib/systemd/system" / unit
        assert installed.is_file()
        assert unit in installed.read_text(encoding="utf-8")
