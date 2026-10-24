"""tunaOS#3331: Base image builds installed unverified uupd binaries and units.

build_scripts/10-base-packages.sh downloaded and installed the uupd executable
as root in both the apt and dnf paths from a mutable release tag, without
verifying the archive against a checksum before extraction, and fetched unit
files from an unverified tag ref.

The download and install routine now verifies the release asset against a
Renovate-managed architecture SHA-256 pin before extraction, fetches systemd
unit files from an immutable commit ref, and verifies each unit against its
expected SHA-256 digest before installation into the image root.

Falsification: behavioural -- running install-uupd.sh with a mutable tag ref
(e.g. v1.5.0), a corrupted binary archive, or a mismatched unit file exits
non-zero and refuses to install unverified files to the target root.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "build_scripts" / "install-uupd.sh"
BASE_PACKAGES = ROOT / "build_scripts" / "10-base-packages.sh"
IMAGE_VERSIONS = ROOT / "image-versions.yaml"
RENOVATE = ROOT / "renovate.json"

VALID_UNIT_CONTENTS = {
    "uupd.service": b"[Unit]\nDescription=uupd update service\n",
    "uupd.timer": b"[Unit]\nDescription=uupd update timer\n",
    "uupd-manual.service": b"[Unit]\nDescription=uupd manual update service\n",
}


def _make_archive(path: Path) -> str:
    payload = b"#!/bin/sh\n[ \"${1:-}\" = --help ]\n"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("uupd")
        info.mode = 0o755
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_fake_curl(bin_dir: Path, archive: Path, corrupt_unit: str | None = None) -> None:
    (bin_dir / "curl").write_text(
        f"""#!/usr/bin/env python3
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
out = Path(args[args.index('-o') + 1])
url = args[-1]
unit_name = url.rsplit('/', 1)[-1]
if url.endswith('.tar.gz'):
    shutil.copyfile(Path({repr(str(archive))}), out)
elif {repr(corrupt_unit)} and unit_name == {repr(corrupt_unit)}:
    out.write_bytes(b"[Unit]\\nCorruptedContent=true\\n")
else:
    unit_map = {repr({k: v.decode('utf-8') for k, v in VALID_UNIT_CONTENTS.items()})}
    out.write_text(unit_map.get(unit_name, '[Unit]\\nDescription=' + unit_name + '\\n'))
""",
        encoding="utf-8",
    )
    (bin_dir / "curl").chmod(0o755)


def _setup_env(
    tmp_path: Path,
    *,
    corrupt_archive: bool = False,
    corrupt_unit: str | None = None,
    tag_ref: str | None = None,
    missing_sha: bool = False,
) -> tuple[dict[str, str], Path, Path]:
    context = tmp_path / "context"
    image = tmp_path / "image"
    fake_bin = tmp_path / "bin"
    context.mkdir()
    fake_bin.mkdir()

    archive = tmp_path / "uupd.tar.gz"
    digest = _make_archive(archive)
    if corrupt_archive:
        archive.write_bytes(b"not a valid or matching tarball")

    _write_fake_curl(fake_bin, archive, corrupt_unit=corrupt_unit)

    if missing_sha:
        sha_yaml = ""
    else:
        sha_yaml = f'  uupd_sha256:\n    x86_64: "{digest}"\n    arm64: "{digest}"\n'

    (context / "image-versions.yaml").write_text(
        f'downloads:\n  uupd: "v1.5.0"\n{sha_yaml}',
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "UUPD_CONTEXT": str(context),
            "UUPD_ROOT": str(image),
            "UUPD_SERVICE_SHA256": hashlib.sha256(VALID_UNIT_CONTENTS["uupd.service"]).hexdigest(),
            "UUPD_TIMER_SHA256": hashlib.sha256(VALID_UNIT_CONTENTS["uupd.timer"]).hexdigest(),
            "UUPD_MANUAL_SERVICE_SHA256": hashlib.sha256(VALID_UNIT_CONTENTS["uupd-manual.service"]).hexdigest(),
        }
    )
    if tag_ref is not None:
        env["UUPD_REF"] = tag_ref

    return env, image, context


def test_10_base_packages_apt_and_dnf_paths_use_verified_routine() -> None:
    text = BASE_PACKAGES.read_text(encoding="utf-8")

    # Neither path may perform an unverified ad-hoc download of uupd
    assert "https://github.com/ublue-os/uupd/releases/download" not in text
    assert "raw.githubusercontent.com/ublue-os/uupd" not in text

    apt_installer = text.index("/run/context/build_scripts/install-uupd.sh")
    apt_return = text.index("return 0\nfi\n# ── dnf (RPM) path continues below")
    assert apt_installer < apt_return, "apt path must invoke install-uupd.sh before return"

    dnf_installer = text.index("/run/context/build_scripts/install-uupd.sh", apt_return)
    assert dnf_installer > apt_return, "dnf path must invoke install-uupd.sh"


def test_installer_rejects_tag_only_ref(tmp_path: Path) -> None:
    env, image, _ = _setup_env(tmp_path, tag_ref="v1.5.0")
    result = subprocess.run([str(INSTALLER)], check=False, capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert "missing or invalid immutable commit ref" in result.stderr
    assert not (image / "usr/bin/uupd").exists()
    assert not (image / "usr/lib/systemd/system/uupd.service").exists()


def test_installer_rejects_corrupted_binary(tmp_path: Path) -> None:
    env, image, _ = _setup_env(tmp_path, corrupt_archive=True)
    result = subprocess.run([str(INSTALLER)], check=False, capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert not (image / "usr/bin/uupd").exists()


def test_installer_rejects_corrupted_unit(tmp_path: Path) -> None:
    env, image, _ = _setup_env(tmp_path, corrupt_unit="uupd.service")
    result = subprocess.run([str(INSTALLER)], check=False, capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert not (image / "usr/lib/systemd/system/uupd.service").exists()
    assert not (image / "usr/bin/uupd").exists()


def test_installer_rejects_missing_checksum(tmp_path: Path) -> None:
    env, image, _ = _setup_env(tmp_path, missing_sha=True)
    result = subprocess.run([str(INSTALLER)], check=False, capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert "missing or invalid SHA-256" in result.stderr
    assert not (image / "usr/bin/uupd").exists()


def test_installer_succeeds_when_verified(tmp_path: Path) -> None:
    env, image, _ = _setup_env(tmp_path)
    result = subprocess.run([str(INSTALLER)], check=False, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert (image / "usr/bin/uupd").is_file()
    assert (image / "usr/bin/uupd").stat().st_mode & stat.S_IXUSR
    for unit in ("uupd.service", "uupd.timer", "uupd-manual.service"):
        unit_file = image / "usr/lib/systemd/system" / unit
        assert unit_file.is_file()
        assert unit_file.read_bytes() == VALID_UNIT_CONTENTS[unit]


def test_image_versions_and_renovate_configuration() -> None:
    versions = yaml.safe_load(IMAGE_VERSIONS.read_text(encoding="utf-8"))
    downloads = versions["downloads"]
    assert "uupd" in downloads
    assert "uupd_sha256" in downloads
    for arch in ("x86_64", "arm64"):
        sha = downloads["uupd_sha256"][arch]
        assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)

    renovate = json.loads(RENOVATE.read_text(encoding="utf-8"))
    hold_rules = [
        rule for rule in renovate.get("packageRules", [])
        if rule.get("automerge") is False and "ublue-os/uupd" in (rule.get("matchDepNames") or [])
    ]
    assert hold_rules, "renovate.json must exclude ublue-os/uupd from automerge"
