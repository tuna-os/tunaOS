#!/usr/bin/env python3
"""Opt-in source bootstrap and read-only contract for an unqualified bootc candidate.

Never called by production builds or installers. No backend configuration is
written here: detection alone cannot safely change the installed boot chain.
"""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess

VERSION = "v1.17.1"
COMMIT = "d01e723ae9480fa53aa9db09a7eff0439548e9f6"
NATIVE = "usr/lib/composefs/setup-root-conf.toml"
OSTREE = ("usr/lib/ostree/prepare-root.conf", "etc/ostree/prepare-root.conf")
FAMILIES = ("arch", "debian", "ubuntu", "gentoo", "fedora", "el10", "hummingbird", "opensuse")
INHERITED = ("fedora", "el10", "hummingbird")
PACKAGED = ("opensuse",)


def cargo_options(family):
    if family not in FAMILIES:
        raise ValueError("unknown family")
    if family == "arch":
        return '--no-default-features --features "install-to-disk pre-6.15"'
    # Preserve default SELinux for every other family, including Gentoo.
    features = "install-to-disk pre-6.15 selinux"
    if family == "el10":
        features += " rhsm"
    return f'--features "{features}"'


def build_command(source, destination, family):
    # One make invocation propagates CARGO_OPTIONS through completion -> bin
    # and manpages, including the rebuild performed by install-all.
    return ["make", "-C", str(source), "bin", "install-all",
            f"DESTDIR={destination}", "prefix=/usr", f"CARGO_OPTIONS={cargo_options(family)}"]


def bootstrap(source, destination, family):
    source, destination = source.resolve(), destination.resolve()
    # Upstream expands DESTDIR unquoted in shell recipes and as a make value.
    if not all(re.fullmatch(r"/[A-Za-z0-9_./-]+", str(path)) for path in (source, destination)):
        raise ValueError("source and destination need plain absolute paths without spaces or metacharacters")
    if destination == Path("/") or destination == source or source.is_relative_to(destination):
        raise ValueError("destination must be an empty staging directory outside the source")
    if destination.is_relative_to(source):
        raise ValueError("destination must be outside the source")
    if not destination.is_dir() or any(destination.iterdir()):
        raise ValueError("destination must be an existing empty staging directory")
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"], text=True)
    if head != COMMIT or dirty:
        raise ValueError(f"source must be a clean checkout of {VERSION} ({COMMIT})")
    env = os.environ.copy()
    # Prevent ambient make/cargo feature overrides from removing SELinux.
    for name in ("MAKEFILES", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "CARGO_OPTIONS", "CARGO_FEATURES", "CARGO_FEATURES_DEFAULT"):
        env.pop(name, None)
    subprocess.run(build_command(source, destination, family), env=env, check=True)
    return {"candidate": VERSION, "source_commit": head, "family": family,
            "staging_directory": str(destination), "qualified": False,
            "binary_version": None, "note": "Build completed; installed binary/runtime not qualified."}


def marker(root, relative):
    path = root / relative
    # Inspection is of an extracted tree, never a host mount. Reject links in
    # the marker path so a fixture cannot accidentally read outside that tree.
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError(f"symlink in marker path: {relative}")
    if path.exists() and not path.is_file():
        raise ValueError(f"marker is not a regular file: {relative}")
    return path.is_file()


def inspect(root, family, architecture="amd64", firmware="uefi", luks=False,
            asahi=False, unified=False, partial=False, filesystem="ext4"):
    if family not in FAMILIES:
        raise ValueError("unknown family")
    root = root.resolve()
    if root == Path("/") or not root.is_dir():
        raise ValueError("provide an extracted candidate tree, not the live root")
    native = marker(root, NATIVE)
    ostree = [name for name in OSTREE if marker(root, name)]
    backend = "conflict" if native and ostree else "composefs-native" if native else "ostree" if ostree else "unknown"
    blockers = ["No runtime qualification receipt; installation is not admitted."]
    if backend != "composefs-native":
        blockers.append("Native requires setup-root-conf.toml and neither OSTree prepare-root.conf.")
    if family in INHERITED:
        blockers.append("Inherited bootc: source pin does not establish the image's binary version or features.")
    if family in PACKAGED:
        blockers.append("Packaged bootc: OBS package version/features require separate artifact evidence.")
    if architecture != "amd64":
        blockers.append("ARM64 needs independent kernel, initramfs and loader qualification.")
    if firmware != "uefi":
        blockers.append("BIOS native installation is not admitted by this candidate.")
    if asahi:
        blockers.append("Asahi needs its separate firmware/installer chain; no generic ISO admission.")
    if luks:
        blockers.append("LUKS needs offline GUI installation, unlock and target-only boot evidence.")
    if filesystem != "ext4":
        blockers.append("Candidate baseline is ext4 with mandatory fs-verity.")
    if unified:
        blockers.append("Unified storage is experimental and lacks install/update/rollback/GC evidence.")
    if partial:
        blockers.append("Partial pulls lack OCI chunk metadata, client and registry byte-transfer evidence.")
    return {"candidate": VERSION, "source_commit": COMMIT, "family": family,
            "backend": backend, "native_marker": native, "ostree_markers": ostree,
            "qualified": False, "install_allowed": False, "binary_version": None,
            "requested": {"architecture": architecture, "firmware": firmware, "luks": luks,
                          "asahi": asahi, "unified": unified, "partial": partial, "filesystem": filesystem},
            "blockers": blockers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("bootstrap", help="compile a clean pinned source into an empty staging directory")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--destination", type=Path, required=True)
    build.add_argument("--family", choices=FAMILIES, required=True)
    check = commands.add_parser("inspect", help="read markers; always refuse runtime admission")
    check.add_argument("--root", type=Path, required=True)
    check.add_argument("--family", choices=FAMILIES, required=True)
    check.add_argument("--architecture", choices=("amd64", "arm64"), default="amd64")
    check.add_argument("--firmware", choices=("uefi", "bios"), default="uefi")
    check.add_argument("--filesystem", choices=("ext4", "xfs", "btrfs"), default="ext4")
    for flag in ("luks", "asahi", "unified", "partial"):
        check.add_argument(f"--{flag}", action="store_true")
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        result = bootstrap(**args) if command == "bootstrap" else inspect(**args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    print(json.dumps(result, indent=2))
    # Inspection is a gate, not a success receipt merely because markers match.
    return 0 if command == "bootstrap" else 1


if __name__ == "__main__":
    raise SystemExit(main())
