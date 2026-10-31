"""Generic [hardware.<id>] profiles: schema, generated JSON, flavor routing and
build_scripts/overlay/hardware-profile.sh against a fake root filesystem."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hardware_config_under_test", ROOT / "scripts/lib/tunaos_config.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)
RESOLVER = ROOT / "scripts/resolve-flavor.sh"
OVERLAY = ROOT / "build_scripts/overlay/hardware-profile.sh"
INVENTORY = ROOT / "build_scripts/overlay/lib/hardware_inventory.sh"

BOARD = {
    "architectures": ["aarch64"],
    "package_managers": ["pacman"],
    "kernel": "stock",
    "kargs": ["arm64.nopauth", "clk_ignore_unused"],
    "packages": {"pacman": ["board-firmware"]},
    "conflicts": {"pacman": ["bad-driver"]},
    "repos": {},
    "initramfs": {"kms_drivers": ["msm"], "add_drivers": ["panel_edp", "absent_mod"],
                  "omit_drivers": ["nouveau"], "dracut_modules": ["crypt"]},
    "devicetree": {"dtb": "vendor/board.dtb", "select": "auto"},
    "require": {"kconfig": ["CONFIG_BOARD"], "kconfig_optional": ["CONFIG_EXTRA"],
                "modules": ["panel_edp", "nvme"], "firmware": ["/usr/lib/firmware/vendor/gpu.bin"]},
}


def with_profile(document, profile=None, flavor_keys=None, variant="marlin"):
    document.setdefault("hardware", {})["board"] = copy.deepcopy(profile or BOARD)
    document["variants"][variant]["flavors"].append(
        {"id": "gnome-board", "stage": 3, "build_image": True, "platforms": ["linux/arm64"],
         "hardware": "board", "parent": "gnome", **(flavor_keys or {})})
    document["flavor_metadata"]["gnome-board"] = {"desktop": "gnome", "edition": "board"}
    return document


def test_real_config_profiles_validate_and_route():
    document = config.load()
    assert set(document["hardware"]) >= {"x13s"}
    rendered = json.loads(config.render_hardware_profiles(document))
    assert rendered["flavors"]["bonito"]["gnome-x13s"] == {"hardware": "x13s", "parent": "gnome"}
    assert rendered["flavors"]["marlin"]["gnome-x13s"] == {"hardware": "x13s", "parent": "gnome"}


def test_a_new_profile_is_accepted_as_data_only():
    config.validate(with_profile(config.load()))


def mutate(path, value):
    def apply(document):
        target = document["hardware"]["board"]
        for part in path[:-1]:
            target = target[part]
        if value is DELETE:
            del target[path[-1]]
        else:
            target[path[-1]] = value
    return apply


DELETE = object()


@pytest.mark.parametrize("change,message", [
    (mutate(("unknown_future_option",), True), "unknown keys"),
    (mutate(("architectures",), ["riscv64"]), "unsupported"),
    (mutate(("package_managers",), ["pkgsrc"]), "unsupported"),
    (mutate(("architectures",), ["x86_64"]), "outside hardware.board.architectures"),
    (mutate(("kernel",), "custom"), "expected \"stock\""),
    (mutate(("kernel",), {"pacman": "linux-board", "repo": "copr:a/b"}), "supported only for"),
    (mutate(("kernel",), {"dnf": "kernel", "repo": "https://example.com/x.repo"}), "unknown keys"),
    (mutate(("repos",), {"pacman": ["copr:a/b"]}), "supported only for"),
    (mutate(("packages",), {"dnf": ["x"]}), "unknown keys"),
    (mutate(("kargs",), ["quiet splash"]), "not a valid entry"),
    (mutate(("devicetree", "dtb"), "../escape.dtb"), "relative to the kernel dtb directory"),
    (mutate(("devicetree", "select"), "manual"), "expected \"auto\""),
    (mutate(("require", "kconfig"), ["BOARD"]), "not a valid entry"),
    (mutate(("require", "firmware"), ["/etc/gpu.bin"]), "not a valid entry"),
    (mutate(("initramfs", "add_drivers"), ["msm", "msm"]), "duplicate"),
    (mutate(("architectures",), DELETE), "missing keys"),
])
def test_invalid_profiles_are_rejected(change, message):
    document = with_profile(config.load())
    change(document)
    with pytest.raises(config.ConfigError, match=message):
        config.validate(document)


@pytest.mark.parametrize("flavor_keys,message", [
    ({"hardware": "absent"}, "unknown hardware profile"),
    ({"parent": "no-such-flavor"}, "is not another flavor"),
    ({"parent": "gnome-board"}, "is not another flavor"),
    ({"parent": "gnome-x13s"}, "is itself a hardware flavor"),
    ({"platforms": ["linux/amd64"]}, "outside hardware.board.architectures"),
])
def test_invalid_hardware_flavors_are_rejected(flavor_keys, message):
    document = with_profile(config.load(), flavor_keys=flavor_keys)
    with pytest.raises(config.ConfigError, match=message):
        config.validate(document)


def test_profile_must_list_the_parent_package_manager():
    document = with_profile(config.load(), {**BOARD, "package_managers": ["dnf"], "packages": {}, "conflicts": {}})
    config.validate(document)
    with pytest.raises(config.ConfigError, match="variant marlin builds with pacman"):
        config.render_hardware_profiles(document)


def test_hardware_needs_a_parent():
    document = with_profile(config.load())
    del document["variants"]["marlin"]["flavors"][-1]["parent"]
    with pytest.raises(config.ConfigError, match="set together"):
        config.validate(document)


def test_generator_is_deterministic_and_fills_defaults():
    document = with_profile(config.load())
    reordered = copy.deepcopy(document)
    reordered["hardware"]["board"] = dict(reversed(list(reordered["hardware"]["board"].items())))
    sparse = with_profile(config.load(), {"architectures": ["aarch64"], "package_managers": ["pacman"], "kernel": "stock"})
    first = config.render_hardware_profiles(document)
    assert first == config.render_hardware_profiles(copy.deepcopy(document))
    assert first == config.render_hardware_profiles(reordered)
    board = json.loads(config.render_hardware_profiles(sparse))["profiles"]["board"]
    assert board["kargs"] == [] and board["devicetree"] is None
    assert board["initramfs"] == {key: [] for key in config.HARDWARE_INITRAMFS}
    assert board["require"] == {key: [] for key in config.HARDWARE_REQUIRE}


def test_check_hardware_profiles_reports_drift(tmp_path):
    (tmp_path / "tunaos.toml").write_bytes((ROOT / "tunaos.toml").read_bytes())
    (tmp_path / "build_scripts/lib").mkdir(parents=True)
    cli = [sys.executable, str(ROOT / "scripts/config.py")]
    assert subprocess.run(cli + ["check-hardware-profiles", "--root", str(tmp_path)], capture_output=True).returncode == 1
    assert subprocess.run(cli + ["generate-hardware-profiles", "--root", str(tmp_path)], capture_output=True).returncode == 0
    assert subprocess.run(cli + ["check-hardware-profiles", "--root", str(tmp_path)], capture_output=True).returncode == 0
    target = tmp_path / "build_scripts/lib/hardware-profiles.json"
    target.write_text(target.read_text().replace('"arm64.nopauth"', '"quiet"'))
    result = subprocess.run(cli + ["check-hardware-profiles", "--root", str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1 and "drift" in result.stderr


def resolve(variant, flavor, profiles):
    proc = subprocess.run([str(RESOLVER), variant, flavor], check=True, text=True, capture_output=True,
                          env=os.environ | {"TUNAOS_HARDWARE_PROFILES": str(profiles)})
    return {key: (shlex.split(raw) or [""])[0] for key, raw in (line.split("=", 1) for line in proc.stdout.splitlines())}


def test_resolve_flavor_routes_any_declared_hardware_flavor(tmp_path):
    profiles = tmp_path / "profiles.json"
    profiles.write_text(json.dumps({"flavors": {"albacore": {"kde-anyboard": {"hardware": "anyboard", "parent": "kde"}}},
                                    "profiles": {}}))
    values = resolve("albacore", "kde-anyboard", profiles)
    assert (values["CONTAINERFILE"], values["OVERLAY_TYPE"], values["DESKTOP_FLAVOR"]) == \
        ("Containerfile.overlay", "hardware", "desktop")
    assert (values["HARDWARE_PROFILE"], values["PARENT_FLAVOR"]) == ("anyboard", "kde")
    # The same name on a variant that does not declare it is an ordinary flavor.
    other = resolve("bonito", "kde-anyboard", profiles)
    assert (other["OVERLAY_TYPE"], other["HARDWARE_PROFILE"], other["PARENT_FLAVOR"]) == ("", "", "")


# ── hardware-profile.sh against a fake root ─────────────────────────────────
TOOLS = ("bash", "jq", "find", "sort", "grep", "sed", "awk", "install", "mktemp", "cp", "cmp", "tee", "paste",
         "readlink", "dirname", "mkdir", "chmod", "rm", "head", "tail", "cat", "stat", "touch", "env", "true")
KVER = "6.99.0-1-board"


def fake(bindir, name, body):
    path = bindir / name
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(0o755)


@pytest.fixture
def board(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool)
        assert found, tool
        (bindir / tool).symlink_to(found)
    log = tmp_path / "calls.log"
    fake(bindir, "uname", "echo aarch64")
    fake(bindir, "pacman", f'echo "pacman $*" >>{log}\n[[ "$1" == -Q && "$2" == bad-driver ]] && [[ -e {tmp_path}/conflict ]] && exit 0\n[[ "$1" == -Q* ]] && exit 1\nexit 0')
    fake(bindir, "dracut", f'echo "dracut $*" >>{log}\nfor a in "$@"; do [[ "$a" == *initramfs.img ]] && echo built >"$a"; done; exit 0')
    fake(bindir, "lsinitrd", f'printf "dracut modules:\\ncrypt\\nostree\\n==========\\nusr/lib/modules/{KVER}/kernel/drivers/panel-edp.ko.zst\\n"')
    sysroot = tmp_path / "root"
    modules = sysroot / "usr/lib/modules" / KVER
    (modules / "kernel/drivers").mkdir(parents=True)
    (modules / "kernel/drivers/panel-edp.ko.zst").write_bytes(b"ko")
    (modules / "modules.builtin").write_text("kernel/drivers/nvme/host/nvme.ko\n")
    (modules / "vmlinuz").write_bytes(b"kernel")
    (modules / "config").write_text("CONFIG_BOARD=y\n")
    (modules / "dtb/vendor").mkdir(parents=True)
    (modules / "dtb/vendor/board.dtb").write_bytes(b"dtb")
    (sysroot / "usr/lib/ostree").mkdir(parents=True)
    (sysroot / "usr/lib/ostree/prepare-root.conf").write_text("[composefs]\nenabled = no\n")
    (sysroot / "usr/lib/firmware/vendor").mkdir(parents=True)
    (sysroot / "usr/lib/firmware/vendor/gpu.bin.zst").write_bytes(b"fw")
    context = tmp_path / "context"
    (context / "overrides/hardware-board/etc").mkdir(parents=True)
    (context / "overrides/hardware-board/etc/board.conf").write_text("wifi=iwd\n")
    profiles = tmp_path / "profiles.json"
    profiles.write_text(json.dumps({"flavors": {}, "profiles": {"board": BOARD}}))

    def run(profile=None):
        if profile is not None:
            profiles.write_text(json.dumps({"flavors": {}, "profiles": {"board": profile}}))
        return subprocess.run([str(OVERLAY), "board"], text=True, capture_output=True,
                              env={"PATH": str(bindir), "TUNAOS_SYSROOT": str(sysroot), "TMPDIR": str(tmp_path),
                                   "TUNAOS_CONTEXT": str(context), "TUNAOS_HARDWARE_PROFILES": str(profiles)})
    run.root, run.log, run.bin, run.tmp = sysroot, log, bindir, tmp_path
    return run


def test_overlay_applies_the_profile_on_a_fake_root(board):
    proc = board()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    root = board.root
    assert (root / "usr/lib/bootc/kargs.d/10-board.toml").read_text().splitlines()[1:] == [
        'kargs = ["arm64.nopauth", "clk_ignore_unused"]', 'match-architectures = ["aarch64"]']
    # absent_mod is not a module of this kernel and is filtered out; on an
    # ostree parent (no dracut-config.sh) the KMS driver joins add_drivers.
    assert (root / "usr/lib/dracut/dracut.conf.d/90-board.conf").read_text().splitlines()[1:] == [
        'add_drivers+=" panel_edp "', 'add_dracutmodules+=" crypt "', 'omit_drivers+=" nouveau "']
    assert (root / f"usr/lib/modules/{KVER}/devicetree").read_bytes() == b"dtb"
    assert (root / "etc/board.conf").read_text() == "wifi=iwd\n"
    calls = board.log.read_text()
    assert "pacman -S --noconfirm --needed board-firmware" in calls
    assert "--add ostree" in calls
    report = (root / "usr/share/tunaos/hardware-board.txt").read_text()
    assert "\nMISSING " not in "\n" + report
    assert "OPTIONAL-MISSING CONFIG_EXTRA" in report
    assert "BUILTIN nvme" in report and "MODULE panel_edp" in report


@pytest.mark.parametrize("arch,managers,message", [
    ("x86_64", ["pacman"], "applies to aarch64 builds, not x86_64"),
    ("aarch64", ["dnf"], "supports dnf parents, not pacman"),
])
def test_overlay_guards_architecture_and_package_manager(board, arch, managers, message):
    fake(board.bin, "uname", f"echo {arch}")
    proc = board({**BOARD, "package_managers": managers})
    assert proc.returncode == 1
    assert message in proc.stderr
    assert not board.log.exists()


def test_overlay_refuses_conflicting_packages(board):
    (board.tmp / "conflict").touch()
    proc = board()
    assert proc.returncode == 1
    assert "bad-driver must not be present" in proc.stderr


@pytest.mark.parametrize("remove", ["usr/lib/firmware/vendor/gpu.bin.zst", f"usr/lib/modules/{KVER}/modules.builtin",
                                    f"usr/lib/modules/{KVER}/config"])
def test_overlay_fails_when_a_required_item_is_missing(board, remove):
    (board.root / remove).unlink()
    proc = board()
    assert proc.returncode == 1
    assert "payload incomplete" in proc.stderr
    assert "\nMISSING " in "\n" + (board.root / "usr/share/tunaos/hardware-board.txt").read_text()


def test_overlay_fails_without_the_device_tree(board):
    (board.root / f"usr/lib/modules/{KVER}/dtb/vendor/board.dtb").unlink()
    proc = board()
    assert proc.returncode == 1
    assert "has no device tree vendor/board.dtb" in proc.stderr
    assert not (board.root / "usr/share/tunaos/hardware-board.txt").exists()


# ── the device tree for every kernel, not just the build's ──────────────────
LATER = "7.0.0-1-board"


def later_kernel(root, dtb=b"later dtb", where="dtb"):
    """A kernel installed after the hardware profile, as a derived image would."""
    modules = root / "usr/lib/modules" / LATER
    modules.mkdir(parents=True)
    (modules / "vmlinuz").write_bytes(b"later kernel")
    source = modules / "dtb/vendor/board.dtb" if where == "dtb" else root / "boot/dtbs/vendor/board.dtb"
    source.parent.mkdir(parents=True)
    source.write_bytes(dtb)
    return modules


def kernel_install(board, *args):
    """Run every installed kernel-install plugin in name order, as kernel-install does."""
    plugins = sorted((board.root / "usr/lib/kernel/install.d").iterdir())
    assert plugins, "no kernel-install plugin installed"
    for plugin in plugins:
        proc = subprocess.run(["bash", str(plugin), *args], text=True, capture_output=True,
                              env={"PATH": str(board.bin), "TUNAOS_SYSROOT": str(board.root)})
        assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_kernel_installed_later_gets_its_own_device_tree(board):
    assert board().returncode == 0
    root = board.root
    modules = later_kernel(root)
    kernel_install(board, "add", LATER, str(root / "boot/entry"), str(modules / "vmlinuz"))
    # Each kernel directory holds its own DTB, so ostree gives the new
    # deployment the new kernel's and a rollback keeps the old one's.
    assert (modules / "devicetree").read_bytes() == b"later dtb"
    assert (root / f"usr/lib/modules/{KVER}/devicetree").read_bytes() == b"dtb"
    kernel_install(board, "remove", LATER)
    assert not (modules / "devicetree").exists()
    assert (root / f"usr/lib/modules/{KVER}/devicetree").exists()


def test_a_later_kernel_without_the_device_tree_fails_its_install(board):
    assert board().returncode == 0
    modules = later_kernel(board.root)
    (modules / "dtb/vendor/board.dtb").unlink()
    plugin = board.root / "usr/lib/kernel/install.d/04-tunaos-devicetree.install"
    proc = subprocess.run(["bash", str(plugin), "add", LATER], text=True, capture_output=True,
                          env={"PATH": str(board.bin), "TUNAOS_SYSROOT": str(board.root)})
    assert proc.returncode == 1
    assert f"kernel {LATER} has no device tree vendor/board.dtb" in proc.stderr


def alpm_hook(board, operation, targets):
    """Run a pacman hook's Exec with its targets on stdin, as libalpm does."""
    hook = (board.root / f"usr/share/libalpm/hooks/95-tunaos-devicetree-{operation}.hook").read_text()
    lines = hook.splitlines()
    assert "Target = usr/lib/modules/*/vmlinuz" in lines and "NeedsTargets" in lines
    command = next(line.split("=", 1)[1].split() for line in lines if line.startswith("Exec ="))
    command[0] = str(board.root) + command[0]
    proc = subprocess.run(command, input="".join(f"{t}\n" for t in targets), text=True, capture_output=True,
                          env={"PATH": str(board.bin), "TUNAOS_SYSROOT": str(board.root)})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return hook


def test_pacman_hooks_give_a_later_kernel_its_device_tree(board):
    assert board().returncode == 0
    # Arch-family kernel packages put their DTBs in /boot/dtbs, not the module directory.
    modules = later_kernel(board.root, where="boot")
    hook = alpm_hook(board, "add", [f"usr/lib/modules/{LATER}/vmlinuz"])
    assert "When = PostTransaction" in hook
    assert (modules / "devicetree").read_bytes() == b"later dtb"
    hook = alpm_hook(board, "remove", [f"usr/lib/modules/{LATER}/vmlinuz"])
    assert "When = PreTransaction" in hook
    assert not (modules / "devicetree").exists()


def test_composefs_enabled_on_a_bootupd_grub_image_still_gets_an_ostree_devicetree(board):
    # Such an image installs on ostree with GRUB (installer-recipe-backend.sh),
    # which loads /usr/lib/modules/<kver>/devicetree, not a stub-wrapped kernel.
    (board.root / "usr/lib/ostree/prepare-root.conf").write_text("[composefs]\nenabled = yes\n")
    payload = board.root / "usr/lib/bootupd/updates/EFI/fedora"
    payload.mkdir(parents=True)
    (payload / "grubaa64.efi").write_bytes(b"grub")
    proc = board()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (board.root / f"usr/lib/modules/{KVER}/devicetree").read_bytes() == b"dtb"
    assert (board.root / f"usr/lib/modules/{KVER}/vmlinuz").read_bytes() == b"kernel"
    assert "layout=ostree" in (board.root / "usr/lib/tunaos/hardware-devicetree.conf").read_text()


@pytest.fixture
def composefs_board(board):
    """A composefs/systemd-boot parent with stand-ins for ukify and pefile."""
    (board.root / "usr/lib/ostree/prepare-root.conf").write_text("[composefs]\nenabled = yes\n")
    # ukify wraps the kernel; the stand-in's first line lists its PE sections
    # and the rest records the DTB and kernel it embedded.
    fake(board.bin, "ukify", f'echo "ukify $*" >>{board.log}\n'
         'for a in "$@"; do case "$a" in --linux=*) l="${a#*=}";; --devicetree-auto=*) d="${a#*=}";; '
         '--output=*) o="${a#*=}";; esac; done\n'
         'printf "SECTIONS .linux .dtbauto .hwids\\ndtb=%s linux=%s" "$(cat "$d")" "$(cat "$l")" >"$o"')
    # python3 -c <pefile script> <image> [section]: the stand-in's section list.
    fake(board.bin, "python3", 'read -r first <"$3" || true; sections=()\n'
         '[[ "$first" == "SECTIONS "* ]] && read -ra sections <<<"${first#SECTIONS }"\n'
         'if [[ $# -eq 4 ]]; then for s in "${sections[@]}"; do [[ "$s" == "$4" ]] && exit 0; done; exit 1; fi\n'
         'printf "%s\\n" "${sections[@]}"')
    return board


def test_composefs_kernels_each_carry_their_own_device_tree_once(composefs_board):
    board = composefs_board
    proc = board()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    root = board.root
    assert (root / f"usr/lib/modules/{KVER}/vmlinuz").read_text().endswith("dtb=dtb linux=kernel")
    assert not (root / f"usr/lib/modules/{KVER}/devicetree").exists()
    assert "PRESENT vmlinuz section .dtbauto" in (root / "usr/share/tunaos/hardware-board.txt").read_text()
    modules = later_kernel(root)
    kernel_install(board, "add", LATER)
    kernel_install(board, "add", LATER)  # a repeated add must not wrap the stub again
    assert (modules / "vmlinuz").read_text().endswith("dtb=later dtb linux=later kernel")
    assert board.log.read_text().count(f"--uname={LATER}") == 1


# ── inventory helpers ───────────────────────────────────────────────────────
def inventory(function, *args):
    return subprocess.run(["bash", "-euo", "pipefail", "-c", f'source "$1"; shift; {function} "$@"', "bash",
                           str(INVENTORY), *map(str, args)], text=True, capture_output=True, check=True).stdout


@pytest.mark.parametrize("suffix", ["", ".xz", ".zst"])
def test_firmware_inventory_accepts_supported_payloads(tmp_path, suffix):
    expected = tmp_path / "amss.bin"
    expected.with_name(expected.name + suffix).write_bytes(b"firmware")
    assert inventory("inventory_file", expected).startswith(f"PRESENT {expected} -> ")


@pytest.mark.parametrize("suffix", [".bak", ".sig", ".xz.bak", ".zst.sig", ".gz"])
def test_firmware_inventory_rejects_non_payload_suffixes(tmp_path, suffix):
    expected = tmp_path / "amss.bin"
    expected.with_name(expected.name + suffix).write_bytes(b"not usable firmware")
    assert inventory("inventory_file", expected) == f"MISSING {expected}\n"


def test_firmware_inventory_follows_links_and_rejects_dangling_ones(tmp_path):
    payload = tmp_path / "payload.xz"
    payload.write_bytes(b"firmware")
    (tmp_path / "good.bin.xz").symlink_to(payload)
    (tmp_path / "bad.bin.xz").symlink_to(tmp_path / "absent")
    assert inventory("inventory_file", tmp_path / "good.bin").startswith("PRESENT ")
    assert inventory("inventory_file", tmp_path / "bad.bin") == f"MISSING {tmp_path / 'bad.bin'}\n"


def test_module_inventory_distinguishes_loadable_builtin_and_missing(tmp_path):
    (tmp_path / "kernel/drivers").mkdir(parents=True)
    (tmp_path / "kernel/drivers/phy-qcom-edp.ko.xz").write_bytes(b"ko")
    (tmp_path / "modules.builtin").write_text("kernel/drivers/nvme/host/nvme.ko\n")
    assert inventory("inventory_module", tmp_path, "phy_qcom_edp").startswith("MODULE phy_qcom_edp -> ")
    assert inventory("inventory_module", tmp_path, "nvme") == "BUILTIN nvme\n"
    assert inventory("inventory_module", tmp_path, "msm") == "MISSING msm\n"
