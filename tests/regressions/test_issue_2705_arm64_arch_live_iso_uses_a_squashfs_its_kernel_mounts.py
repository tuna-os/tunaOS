"""tunaOS#2705: the marlin arm64 live ISO could not mount its own root.

tacklebox writes every live squashfs with `-comp zstd`. Arch Linux ARM's
linux-aarch64 kernel has `# CONFIG_SQUASHFS_ZSTD is not set`, so the boot
looped in the dracut initqueue on

    mount: /run/rootfsbase: fsconfig() failed: Filesystem uses "zstd"
    compression. This is not supported.

and the ISO boot gate timed out every night (run 36075112992, job
107892302194). scripts/build-iso-tacklebox.sh now builds such an image's
squashfs with xz through a mksquashfs wrapper, and reads the compressors
back out of the finished ISO.

Falsification: behavioural. The real wrapper is installed into a scratch
path and run against a stand-in mksquashfs that records its argv. With the
`zstd -> xz` rewrite deleted from the wrapper,
test_the_wrapper_turns_zstd_into_xz fails (checked). The superblock reader
runs on synthetic superblocks, and test_a_zstd_iso_fails_the_check fails if
the zstd branch of tunaos_assert_iso_squashfs_mountable is removed
(checked). The wiring test is structural.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "scripts" / "lib" / "squashfs-compat.sh"
BUILD = (ROOT / "scripts" / "build-iso-tacklebox.sh").read_text(encoding="utf-8")


def _bash(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f". '{LIB}'\n{script}"],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


@pytest.mark.parametrize(
    "kernels",
    [
        "linux-aarch64\n7.2.7-2-aarch64-ARCH",  # marlin arm64, both signals
        "7.2.7-2-aarch64-ARCH",  # no pkgbase file, directory name only
        "linux-aarch64",
    ],
)
def test_arch_linux_arm_kernel_is_recognised(kernels):
    assert _bash(f"tunaos_pkgbase_lacks_squashfs_zstd '{kernels}'").returncode == 0


@pytest.mark.parametrize(
    "kernels",
    [
        "linux\n7.2.6-arch2-1",  # marlin amd64: boots zstd fine
        "7.2.7-200.fc44.aarch64",  # bonito arm64
        "6.12.0-55.el10.aarch64",  # EL10 arm64
        "",  # an image with no modules directory
    ],
)
def test_kernels_with_zstd_are_left_alone(kernels):
    assert _bash(f"tunaos_pkgbase_lacks_squashfs_zstd '{kernels}'").returncode == 1


def _install_shim(tmp_path: Path) -> tuple[Path, Path]:
    record = tmp_path / "argv"
    fake = tmp_path / "real-mksquashfs"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\n')
    fake.chmod(0o755)
    shim = tmp_path / "local-bin" / "mksquashfs"
    proc = _bash(
        "tunaos_install_mksquashfs_xz_shim",
        {"TUNAOS_MKSQUASHFS_SHIM": str(shim), "TUNAOS_REAL_MKSQUASHFS": str(fake)},
    )
    assert proc.returncode == 0, proc.stderr
    return shim, record


def test_the_wrapper_turns_zstd_into_xz(tmp_path):
    shim, record = _install_shim(tmp_path)
    # The shape tacklebox's live.go passes (the -comp/-X/-b line).
    proc = subprocess.run(
        [
            str(shim),
            "/src",
            "/out/marlin-gnome.rootfs.sfs",
            "-noappend",
            "-comp",
            "zstd",
            "-Xcompression-level",
            "3",
            "-b",
            "1M",
            "-quiet",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    argv = record.read_text().splitlines()
    assert argv == [
        "/src",
        "/out/marlin-gnome.rootfs.sfs",
        "-noappend",
        "-comp",
        "xz",
        "-b",
        "1M",
        "-quiet",
    ]
    assert "tunaOS#2705" in proc.stderr, "the job log must say why"


def test_the_wrapper_passes_other_compressors_through(tmp_path):
    shim, record = _install_shim(tmp_path)
    subprocess.run(
        [str(shim), "a", "b", "-comp", "gzip", "-Xcompression-level", "9"],
        check=True,
        capture_output=True,
    )
    # -Xcompression-level is dropped whatever the compressor: xz is the only
    # compressor this wrapper exists to produce, and it rejects the option.
    assert record.read_text().splitlines() == ["a", "b", "-comp", "gzip"]


def test_the_wrapper_never_replaces_a_foreign_mksquashfs(tmp_path):
    shim = tmp_path / "local-bin" / "mksquashfs"
    shim.parent.mkdir()
    shim.write_text("#!/bin/sh\necho someone else's\n")
    proc = _bash(
        "tunaos_install_mksquashfs_xz_shim",
        {"TUNAOS_MKSQUASHFS_SHIM": str(shim), "TUNAOS_REAL_MKSQUASHFS": "/bin/true"},
    )
    assert proc.returncode != 0
    assert "someone else's" in shim.read_text()
    # And removal leaves it alone too.
    _bash("tunaos_remove_mksquashfs_xz_shim", {"TUNAOS_MKSQUASHFS_SHIM": str(shim)})
    assert shim.exists()


def test_removal_deletes_only_the_wrapper(tmp_path):
    shim, _ = _install_shim(tmp_path)
    _bash("tunaos_remove_mksquashfs_xz_shim", {"TUNAOS_MKSQUASHFS_SHIM": str(shim)})
    assert not shim.exists()


def _superblock(comp_id: int) -> bytes:
    # magic, inodes, mkfs_time, block_size, fragments, compression id at +20
    return b"hsqs" + struct.pack("<IIII", 1, 0, 131072, 0) + struct.pack("<H", comp_id) + b"\0" * 74


@pytest.mark.parametrize("comp_id,name", [(4, "xz"), (6, "zstd"), (1, "gzip")])
def test_the_superblock_reader_names_the_compressor(tmp_path, comp_id, name):
    f = tmp_path / "img"
    f.write_bytes(b"\0" * 4096 + _superblock(comp_id))
    proc = _bash(f"tunaos_squashfs_compressor_at '{f}' 4096")
    assert proc.stdout.strip() == name


def test_a_non_squashfs_file_is_not_misread(tmp_path):
    f = tmp_path / "img"
    f.write_bytes(b"\0" * 128)
    assert _bash(f"tunaos_squashfs_compressor_at '{f}' 0").stdout.strip() == "not-squashfs"


needs_iso_tools = pytest.mark.skipif(
    not (shutil.which("xorriso") and shutil.which("dd") and shutil.which("od")),
    reason="xorriso not installed",
)


def _iso(tmp_path: Path, comps: dict[str, int]) -> Path:
    tree = tmp_path / "tree" / "LiveOS"
    tree.mkdir(parents=True)
    for name, comp_id in comps.items():
        (tree / name).write_bytes(_superblock(comp_id))
    iso = tmp_path / "x.iso"
    subprocess.run(
        ["xorriso", "-outdev", str(iso), "-map", str(tree.parent), "/"],
        check=True,
        capture_output=True,
    )
    return iso


@needs_iso_tools
def test_an_xz_iso_passes_the_check(tmp_path):
    iso = _iso(tmp_path, {"marlin-gnome.rootfs.sfs": 4, "store.squashfs.img": 4})
    proc = _bash(f"tunaos_assert_iso_squashfs_mountable '{iso}'")
    assert proc.returncode == 0, proc.stderr


@needs_iso_tools
def test_a_zstd_iso_fails_the_check(tmp_path):
    iso = _iso(tmp_path, {"marlin-gnome.rootfs.sfs": 6, "store.squashfs.img": 4})
    proc = _bash(f"tunaos_assert_iso_squashfs_mountable '{iso}'")
    assert proc.returncode != 0
    assert "marlin-gnome.rootfs.sfs is zstd" in proc.stderr


def test_the_build_installs_the_wrapper_before_tacklebox_and_checks_after():
    install = BUILD.index("tunaos_install_mksquashfs_xz_shim")
    run = BUILD.index('tunaos_run_tacklebox "$RECIPE_FILE"')
    check = BUILD.index('tunaos_assert_iso_squashfs_mountable "$ISO_OUT"')
    assert install < run < check
    # Only for a kernel that needs it: the install sits under the detection.
    guarded = BUILD[:install]
    assert "tunaos_pkgbase_lacks_squashfs_zstd" in guarded[guarded.rindex("\nif ") :]
    # And the wrapper is removed on every exit path, not just success.
    assert "tunaos_remove_mksquashfs_xz_shim" in BUILD[BUILD.rindex("trap ", 0, install) : install]
