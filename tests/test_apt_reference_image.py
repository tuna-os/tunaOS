"""Static APT consumer behavior using real cpio and dracut inspection tools.

The small crafted kernel/EFI/plugin bytes are public test inputs, not bootable
images. These tests prove artifact rejection and exact initramfs comparison,
never installation or runtime qualification.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import struct
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify-apt-reference.py"
SPEC = importlib.util.spec_from_file_location("apt_reference_image", SCRIPT)
APT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APT)
KVER = "7.0.0-29-generic"
SYMBOLS = ("CONFIG_X86_64=y\nCONFIG_EROFS_FS_BACKED_BY_FILE=y\nCONFIG_FS_VERITY=y\n"
           "CONFIG_EROFS_FS=m\nCONFIG_OVERLAY_FS=m\nCONFIG_EXT4_FS=m\n")


def put(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value if isinstance(value, bytes) else value.encode())
    return target


def pack(root, initrd):
    paths = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    result = subprocess.run(["cpio", "--create", "--format=newc", "--quiet"], cwd=root,
                            input=("\n".join(paths) + "\n").encode(), capture_output=True, check=True)
    # Real zstd compression exercises the format finalized Grouper images use.
    packed = subprocess.run(["zstd", "--quiet", "--stdout"], input=result.stdout,
                            capture_output=True, check=True)
    initrd.write_bytes(packed.stdout)


@pytest.fixture
def image(tmp_path):
    # These are dependencies, not optional assertions. CI must install dracut
    # tooling to run this suite; a missing extractor cannot produce green proof.
    for tool in ("cpio", "zstd", "lsinitrd"):
        assert shutil.which(tool), f"APT proof tests require {tool}"
    root, ramfs = tmp_path / "image", tmp_path / "initrd-root"
    modules = root / "usr/lib/modules" / KVER
    modules.mkdir(parents=True)
    config = put(root, f"usr/lib/modules/{KVER}/config", SYMBOLS)
    header = bytearray(0x400)
    header[0x1FE:0x200] = b"\x55\xaa"
    header[0x202:0x206] = b"HdrS"
    struct.pack_into("<H", header, 0x206, 0x20C)
    struct.pack_into("<H", header, 0x20E, 0x100)
    struct.pack_into("<H", header, 0x236, 1)
    header[0x300:0x300 + len(KVER) + 1] = KVER.encode() + b"\0"
    put(root, f"usr/lib/modules/{KVER}/vmlinuz", bytes(header))
    put(root, "usr/lib/systemd/boot/efi/systemd-bootx64.efi", "public EFI fixture")
    put(root, "usr/lib/ostree/prepare-root.conf", "[composefs]\nenabled = yes\n[sysroot]\nreadonly = true\n")
    theme = subprocess.run(["bash", str(ROOT / "build_scripts/plymouth-set-theme.sh"), "--print", "grouper"],
                           capture_output=True, text=True, check=True).stdout.strip()
    for tree in (root, ramfs):
        theme_dir = tree / "usr/share/plymouth/themes" / theme
        shutil.copytree(ROOT / "system_files/usr/share/plymouth/themes" / theme, theme_dir)
        (theme_dir.parent / "default.plymouth").symlink_to(f"{theme}/{theme}.plymouth")
        put(tree, "etc/plymouth/plymouthd.conf", f"[Daemon]\nTheme={theme}\n")
        put(tree, "usr/lib/x86_64-linux-gnu/plymouth/script.so", "public plugin fixture")
        put(tree, "usr/sbin/plymouthd", "public executable fixture")
    put(ramfs, "usr/lib/dracut/modules.txt", "systemd\nbootc\nplymouth\n")
    for driver in ("erofs", "overlay", "ext4"):
        put(ramfs, f"usr/lib/modules/{KVER}/kernel/fs/{driver}/{driver}.ko", "public module fixture")
    initrd = modules / "initramfs.img"
    pack(ramfs, initrd)
    return root, ramfs, config, initrd, theme


def test_real_zstd_initramfs_and_recipe_are_static_only(image):
    root, _ramfs, _config, _initrd, _theme = image
    result = APT.verify(root)
    assert result["purpose"] == "apt-image-static-proof-only"
    assert result["family"] == "apt" and result["platform"] == "linux/amd64"
    assert result["backend"] == {"bootloader": "systemd", "composeFsBackend": True, "filesystem": "ext4"}
    assert result["runtimeAcceptance"] == "not-run"
    assert result["kernel"]["configSha256"] == APT.digest(root / f"usr/lib/modules/{KVER}/config")
    assert result["branding"]["status"] == "passed"


@pytest.mark.parametrize("symbol", ["CONFIG_X86_64", "CONFIG_EROFS_FS_BACKED_BY_FILE", "CONFIG_FS_VERITY"])
def test_kernel_version_cannot_replace_missing_capability(image, symbol):
    root, _ramfs, config, _initrd, _theme = image
    config.write_text(config.read_text().replace(f"{symbol}=y\n", ""))
    with pytest.raises(APT.InvalidImage, match="kernel-lacks-" + symbol):
        APT.verify(root)


def test_config_discarded_with_boot_tmpfs_is_not_qualified(image):
    root, _ramfs, config, _initrd, _theme = image
    config.unlink()
    with pytest.raises(APT.InvalidImage, match="missing-image-file"):
        APT.verify(root)


def test_missing_module_in_actual_initramfs_fails(image):
    root, ramfs, _config, initrd, _theme = image
    (ramfs / f"usr/lib/modules/{KVER}/kernel/fs/erofs/erofs.ko").unlink()
    pack(ramfs, initrd)
    with pytest.raises(APT.InvalidImage, match="initramfs-lacks-erofs"):
        APT.verify(root)


def test_builtin_driver_does_not_require_a_module(image):
    root, ramfs, config, initrd, _theme = image
    config.write_text(config.read_text().replace("CONFIG_EROFS_FS=m", "CONFIG_EROFS_FS=y"))
    (ramfs / f"usr/lib/modules/{KVER}/kernel/fs/erofs/erofs.ko").unlink()
    pack(ramfs, initrd)
    assert APT.verify(root)["runtimeAcceptance"] == "not-run"


def test_wrong_kernel_module_cannot_satisfy_initramfs(image):
    root, ramfs, _config, initrd, _theme = image
    module = ramfs / f"usr/lib/modules/{KVER}/kernel/fs/erofs/erofs.ko"
    module.unlink()
    put(ramfs, "usr/lib/modules/6.8.0-old/kernel/fs/erofs/erofs.ko", "wrong kernel fixture")
    pack(ramfs, initrd)
    with pytest.raises(APT.InvalidImage, match="initramfs-lacks-erofs"):
        APT.verify(root)


def test_no_bootc_dracut_module_is_not_an_installable_root(image):
    root, ramfs, _config, initrd, _theme = image
    put(ramfs, "usr/lib/dracut/modules.txt", "systemd\nplymouth\n")
    pack(ramfs, initrd)
    with pytest.raises(APT.InvalidImage, match="initramfs-lacks-bootc-module"):
        APT.verify(root)


def test_ostree_grub_payload_does_not_satisfy_apt_recipe(image):
    root, _ramfs, _config, _initrd, _theme = image
    put(root, "usr/lib/bootupd/updates/EFI/ubuntu/grubx64.efi", "public wrong-backend fixture")
    with pytest.raises(APT.InvalidImage, match="wrong-apt-install-layout"):
        APT.verify(root)


@pytest.mark.parametrize("change", ["frame", "plugin", "selection"])
def test_existing_checker_rejects_stale_initramfs_branding(image, change):
    root, ramfs, _config, initrd, theme = image
    if change == "frame":
        put(ramfs, f"usr/share/plymouth/themes/{theme}/{theme}-0001.png", "stale public frame")
    elif change == "plugin":
        (ramfs / "usr/lib/x86_64-linux-gnu/plymouth/script.so").unlink()
    else:
        put(ramfs, "etc/plymouth/plymouthd.conf", "[Daemon]\nTheme=wrong-theme\n")
    pack(ramfs, initrd)
    with pytest.raises(APT.InvalidImage, match="initramfs-branding-failed"):
        APT.verify(root)


def test_external_symlink_cannot_substitute_host_config(image, tmp_path):
    root, _ramfs, config, _initrd, _theme = image
    external = put(tmp_path, "outside-config", SYMBOLS)
    config.unlink()
    config.symlink_to(external)
    with pytest.raises(APT.InvalidImage, match="image-path-escapes-root"):
        APT.verify(root)


def test_cli_emits_only_json_and_never_runtime_acceptance(image):
    import json
    root, _ramfs, _config, _initrd, _theme = image
    completed = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
                               capture_output=True, text=True, env=os.environ, check=True)
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["runtimeAcceptance"] == "not-run"


@pytest.mark.parametrize("offset,value,reason", [
    (0x236, 0, "kernel-binary-is-not-amd64"),
    (0x206, 0x20B, "kernel-binary-is-not-amd64"),
    (0x20E, 0, "missing-kernel-release"),
])
def test_bzimage_binary_identity_is_not_inferred_from_config(image, offset, value, reason):
    root, _ramfs, _config, _initrd, _theme = image
    kernel = root / f"usr/lib/modules/{KVER}/vmlinuz"
    header = bytearray(kernel.read_bytes())
    struct.pack_into("<H", header, offset, value)
    kernel.write_bytes(header)
    with pytest.raises(APT.InvalidImage, match=reason):
        APT.verify(root)


def test_old_kernel_binary_cannot_borrow_new_config(image):
    root, _ramfs, _config, _initrd, _theme = image
    kernel = root / f"usr/lib/modules/{KVER}/vmlinuz"
    header = bytearray(kernel.read_bytes())
    header[0x300:0x310] = b"6.8.0-old\0xxxxxxx"
    kernel.write_bytes(header)
    with pytest.raises(APT.InvalidImage, match="kernel-binary-release-mismatch"):
        APT.verify(root)


@pytest.mark.parametrize("stream", [1, 2])
def test_inspector_output_is_bounded_during_collection(stream):
    with pytest.raises(APT.InvalidImage, match="inspection-output-limit"):
        APT.command([sys.executable, "-c", f"import os; os.write({stream}, b'x'*131072)"],
                    "unexpected-command-failure", limit=4096)


def test_deadline_terminates_descendant_with_open_pipes(tmp_path):
    marker = tmp_path / "descendant-survived"
    child = f"import time; time.sleep(0.5); open({str(marker)!r}, 'w').write('survived')"
    parent = f"import subprocess,sys; subprocess.Popen([sys.executable, '-c', {child!r}])"
    with pytest.raises(APT.InvalidImage, match="inspection-timeout"):
        APT.command([sys.executable, "-c", parent], "unexpected-command-failure", timeout=0.1)
    time.sleep(0.6)
    assert not marker.exists()


def newc_record(name, mode, payload=b"", inode=1, nlink=1):
    encoded = name.encode() + b"\0"
    fields = (inode, mode, 0, 0, nlink, 0, len(payload), 0, 0, 0, 0, len(encoded), 0)
    header = b"070701" + b"".join(f"{value:08x}".encode() for value in fields)
    result = header + encoded
    result += b"\0" * (-len(result) % 4)
    result += payload
    return result + b"\0" * (-len(payload) % 4)


def cpio_segment(*records):
    import stat
    data = b"".join(records) + newc_record("TRAILER!!!", stat.S_IFREG)
    return data + b"\0" * (-len(data) % 512)


def test_build_parameter_presentation_cannot_forge_artifacts(image):
    root, ramfs, _config, initrd, _theme = image
    put(ramfs, "usr/lib/dracut/modules.txt", "systemd\nplymouth\n")
    (ramfs / f"usr/lib/modules/{KVER}/kernel/fs/erofs/erofs.ko").unlink()
    put(ramfs, "usr/lib/dracut/build-parameter.txt",
        f"bootc\nusr/lib/modules/{KVER}/kernel/fs/erofs/erofs.ko\n")
    pack(ramfs, initrd)
    with pytest.raises(APT.InvalidImage, match="initramfs-lacks-bootc-module"):
        APT.verify(root)


@pytest.mark.parametrize("replacement", ["directory", "not-erofs.ko"])
def test_required_driver_must_be_an_exact_regular_member(image, replacement):
    root, ramfs, _config, initrd, _theme = image
    module = ramfs / f"usr/lib/modules/{KVER}/kernel/fs/erofs/erofs.ko"
    module.unlink()
    if replacement == "directory":
        module.mkdir()
    else:
        module.with_name(replacement).write_text("not the required module")
    pack(ramfs, initrd)
    with pytest.raises(APT.InvalidImage, match="initramfs-lacks-erofs"):
        APT.verify(root)


@pytest.mark.parametrize("kind", ["absolute", "parent-traversal", "symlink-parent"])
def test_escaping_cpio_records_never_write_outside_owned_tree(image, tmp_path, kind):
    import stat
    root, _ramfs, _config, initrd, _theme = image
    outside = put(tmp_path, "outside-sentinel", "must remain unchanged")
    if kind == "absolute":
        malicious = newc_record(str(outside), stat.S_IFREG | 0o644, b"overwrite")
    elif kind == "parent-traversal":
        malicious = newc_record("../../outside-sentinel", stat.S_IFREG | 0o644, b"overwrite")
    else:
        malicious = newc_record("escape", stat.S_IFLNK | 0o777, b"../../")
    initrd.write_bytes(cpio_segment(malicious) + initrd.read_bytes())
    with pytest.raises(APT.InvalidImage, match="initramfs-decoding-failed"):
        APT.verify(root)
    assert outside.read_text() == "must remain unchanged"


def test_image_theme_symlink_cannot_replace_initramfs_artwork(image):
    root, ramfs, _config, initrd, theme = image
    target = ramfs / f"usr/share/plymouth/themes/{theme}"
    shutil.rmtree(target)
    target.symlink_to(root / f"usr/share/plymouth/themes/{theme}")
    pack(ramfs, initrd)
    with pytest.raises(APT.InvalidImage, match="initramfs-branding-failed"):
        APT.verify(root)


def test_early_microcode_and_compressed_main_are_both_consumed(image):
    import stat
    root, _ramfs, _config, initrd, _theme = image
    early = cpio_segment(newc_record("early_cpio", stat.S_IFREG | 0o644, b"1"),
                         newc_record("kernel/x86/microcode/GenuineIntel.bin",
                                     stat.S_IFREG | 0o644, b"public microcode fixture", inode=2))
    initrd.write_bytes(early + initrd.read_bytes())
    assert APT.verify(root)["runtimeAcceptance"] == "not-run"


def test_later_cpio_segment_is_not_ignored(image, tmp_path):
    import stat
    root, _ramfs, _config, initrd, _theme = image
    outside = put(tmp_path, "later-sentinel", "unchanged")
    evil = cpio_segment(newc_record(str(outside), stat.S_IFREG | 0o644, b"overwrite"))
    compressed = subprocess.run(["zstd", "--quiet", "--stdout"], input=evil,
                                capture_output=True, check=True).stdout
    initrd.write_bytes(initrd.read_bytes() + compressed)
    with pytest.raises(APT.InvalidImage, match="initramfs-decoding-failed"):
        APT.verify(root)
    assert outside.read_text() == "unchanged"


def test_internal_tree_comparison_never_claims_archive_authentication(image):
    root, ramfs, _config, _initrd, _theme = image
    result = subprocess.run(["bash", str(ROOT / "build_scripts/checks/verify-plymouth-initramfs.sh"),
                             "--tree", "grouper", str(ramfs)],
                            env={**os.environ, "PLYMOUTH_SYSROOT": str(root)},
                            capture_output=True, text=True, check=True)
    assert "no archive authentication" in result.stdout
    assert "TUNAOS_PLYMOUTH_TREE_OK" in result.stdout
    assert "TUNAOS_PLYMOUTH_OK" not in result.stdout


def test_existing_archive_cli_keeps_actual_extraction_and_asset_comparisons(image):
    root, _ramfs, _config, initrd, _theme = image
    result = subprocess.run(["bash", str(ROOT / "build_scripts/checks/verify-plymouth-initramfs.sh"),
                             "grouper", str(initrd)],
                            env={**os.environ, "PLYMOUTH_SYSROOT": str(root)},
                            capture_output=True, text=True, check=True)
    assert "TUNAOS_PLYMOUTH_OK" in result.stdout
    assert "TUNAOS_PLYMOUTH_TREE_OK" not in result.stdout


def test_gnu_cpio_last_data_hardlink_preserves_exact_brand_bytes(image):
    root, ramfs, _config, initrd, theme = image
    frame = ramfs / f"usr/share/plymouth/themes/{theme}/{theme}-0001.png"
    os.link(frame, ramfs / "zz-public-frame-hardlink")
    pack(ramfs, initrd)
    assert APT.verify(root)["branding"]["status"] == "passed"


def test_later_hardlink_payload_updates_shared_module_list(image):
    import stat
    root, ramfs, _config, initrd, _theme = image
    (ramfs / "usr/lib/dracut/modules.txt").unlink()
    pack(ramfs, initrd)
    early = cpio_segment(
        newc_record("usr/lib/dracut/modules.txt", stat.S_IFREG | 0o644, b"bootc\n", inode=9, nlink=2),
        newc_record("module-list-alias", stat.S_IFREG | 0o644, b"not-bootc\n", inode=9, nlink=2))
    initrd.write_bytes(early + initrd.read_bytes())
    with pytest.raises(APT.InvalidImage, match="initramfs-lacks-bootc-module"):
        APT.verify(root)


@pytest.mark.parametrize("suffix", ["raw-cpio", "zero-padding"])
def test_segment_scanner_resumes_after_zstd_frame(image, suffix):
    import stat
    root, _ramfs, _config, initrd, _theme = image
    tail = (cpio_segment(newc_record("public-trailing-record", stat.S_IFREG | 0o644, b"tail"))
            if suffix == "raw-cpio" else b"\0" * 512)
    initrd.write_bytes(initrd.read_bytes() + tail)
    assert APT.verify(root)["runtimeAcceptance"] == "not-run"


@pytest.mark.parametrize("magic", [b"070702", b"070707"])
def test_unverified_crc_and_kernel_unsupported_odc_never_qualify(image, magic):
    import stat
    root, _ramfs, _config, initrd, _theme = image
    record = cpio_segment(newc_record("untrusted-method", stat.S_IFREG | 0o644, b"payload"))
    initrd.write_bytes(magic + record[6:] + initrd.read_bytes())
    with pytest.raises(APT.InvalidImage, match="initramfs-decoding-failed"):
        APT.verify(root)


@pytest.mark.parametrize("relative", [
    "usr/lib/ostree/prepare-root.conf",
    "etc/plymouth/plymouthd.conf",
    "usr/lib/x86_64-linux-gnu/plymouth/script.so",
    "usr/share/plymouth/themes/coral/coral-0001.png",
])
def test_auxiliary_probe_files_cannot_borrow_host_bytes(image, tmp_path, relative):
    root, _ramfs, _config, _initrd, theme = image
    relative = relative.replace("coral", theme)
    target = root / relative
    external = put(tmp_path, "external-public-input", target.read_bytes())
    target.unlink()
    target.symlink_to(external)
    with pytest.raises(APT.InvalidImage, match="image-path-escapes-root"):
        APT.verify(root)


@pytest.mark.parametrize("location", ["later-record", "trailer"])
def test_crc_policy_applies_after_first_newc_header(image, location):
    import stat
    root, _ramfs, _config, initrd, _theme = image
    first = newc_record("public-first-newc", stat.S_IFREG | 0o644, b"first")
    if location == "later-record":
        bad_crc = newc_record("unchecked-crc-data", stat.S_IFREG | 0o644, b"checksum-is-not-zero")
        segment = cpio_segment(first, b"070702" + bad_crc[6:])
    else:
        segment = cpio_segment(first)
        trailer = segment.rfind(b"070701")
        segment = segment[:trailer] + b"070702" + segment[trailer + 6:]
    initrd.write_bytes(segment + initrd.read_bytes())
    with pytest.raises(APT.InvalidImage, match="initramfs-decoding-failed"):
        APT.verify(root)


def test_internal_theme_directory_alias_cannot_hide_external_file(image, tmp_path):
    root, _ramfs, _config, _initrd, theme = image
    selected = root / f"usr/share/plymouth/themes/{theme}"
    internal = root / "internal-theme-alias"
    shutil.move(selected, internal)
    selected.symlink_to(internal)
    descriptor = internal / f"{theme}.plymouth"
    external = put(tmp_path, "external-theme-descriptor", descriptor.read_bytes())
    descriptor.unlink()
    descriptor.symlink_to(external)
    with pytest.raises(APT.InvalidImage, match="image-path-escapes-root"):
        APT.verify(root)
