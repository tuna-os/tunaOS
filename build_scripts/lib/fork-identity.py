#!/usr/bin/env python3
"""Apply/verify experimental identity in an explicit staging root, never a live OS.

The build engine refuses this payload. Installer and Plymouth remain incomplete.
This helper exercises the real file formats/paths; it is not boot qualification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

BLOCKERS = ["installer-recipe-resource", "plymouth-initramfs", "built-image-boot-login-install"]
SHA = re.compile(r"[0-9a-f]{64}\Z")


def valid_name(name):
    return bool(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}", name) and name == name.strip())


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate identity key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique)


def load(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("identity manifest must be a regular file")
    m = read_json(path)
    keys = {"schema_version", "status", "name", "variant", "flavor", "platform", "sources", "logo_input_sha256", "assets", "blocked_consumers"}
    if not isinstance(m, dict) or set(m) != keys:
        raise ValueError("invalid identity manifest fields")
    if (type(m["schema_version"]) is not int or m["schema_version"] != 1 or m["status"] != "staging-only"
            or not valid_name(m["name"]) or m["flavor"] != "gnome"
            or not isinstance(m["variant"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", m["variant"])
            or m["platform"] not in ("linux/amd64", "linux/amd64/v2", "linux/arm64")
            or m["blocked_consumers"] != BLOCKERS):
        raise ValueError("unsupported identity staging contract")
    if (not isinstance(m["sources"], dict) or set(m["sources"]) != {"sha256"}
            or not isinstance(m["sources"]["sha256"], str) or not SHA.fullmatch(m["sources"]["sha256"])
            or not isinstance(m["logo_input_sha256"], str) or not SHA.fullmatch(m["logo_input_sha256"])):
        raise ValueError("invalid identity source receipt")
    if not isinstance(m["assets"], dict) or set(m["assets"]) != {"logo", "lettermark"}:
        raise ValueError("identity logo and lettermark required")
    for asset in m["assets"].values():
        if (not isinstance(asset, dict) or set(asset) != {"path", "sha256"}
                or not isinstance(asset["sha256"], str) or not SHA.fullmatch(asset["sha256"])
                or asset["path"] != f"fork-identity-assets/{asset['sha256']}.svg"):
            raise ValueError("invalid identity asset receipt")
        file = path.parent / asset["path"]
        if file.parent.is_symlink() or file.is_symlink() or not file.is_file():
            raise ValueError("identity asset missing or symlinked")
        if hashlib.sha256(file.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("identity asset hash mismatch")
    base = path.parent / "fork-config.json"
    if base.is_symlink() or not base.is_file():
        raise ValueError("identity needs its paired fork-config manifest")
    source = read_json(base)
    if not isinstance(source, dict) or any(source.get(k) != m[k] for k in ("sources", "variant", "flavor", "platform")):
        raise ValueError("identity does not match paired fork-config source/cell")
    return m


def target(root, relative):
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("identity target must stay within its root")
    path = root / relative
    # Refuse host escapes and symlinked writes, including existing ancestors.
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"symlinked identity target: {relative}")
        if parent != path and parent.exists() and not parent.is_dir():
            raise ValueError(f"non-directory identity ancestor: {relative}")
    if path.exists():
        if not path.is_file():
            raise ValueError(f"non-regular identity target: {relative}")
        if path.stat().st_nlink != 1:
            raise ValueError(f"hardlinked identity target: {relative}")
    return path


def fields(m):
    # Keep base ID/ID_LIKE, routing IDs and hostname: display name is not a new
    # distro ID, CPE authority, package family or image publication identity.
    return {"NAME": m["name"], "PRETTY_NAME": m["name"], "VARIANT": f'{m["name"]} {m["flavor"]}',
            "LOGO": "tunaos", "VERSION_CODENAME": m["name"]}


def os_release(data, m):
    values = fields(m)
    lines = [line for line in data.splitlines() if line.partition("=")[0] not in {*values, "CPE_NAME"}]
    return "\n".join(lines + [f'{key}="{value}"' for key, value in values.items()]) + "\n"


def staging_root(root):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("identity staging root must be a directory")
    if root == Path("/"):
        raise ValueError("identity staging requires an explicit non-live root; builds remain blocked")
    return root



def apply(manifest, root, check=False):
    root = staging_root(root)
    osr = target(root, "usr/lib/os-release")
    image_info = target(root, "usr/share/ublue-os/image-info.json")
    info = read_json(image_info)
    base = read_json(manifest.parent / "fork-config.json")
    if "fork-config" in info and (not isinstance(info["fork-config"], dict) or any(
            info["fork-config"].get(k) != m[k] for k in ("sources", "variant", "flavor", "platform"))):
        raise ValueError("identity does not match image-info source/platform receipt")
    # The outer shell adapter writes these files before it invokes apply.
    # Check its targets too, so --check protects the whole staged operation.
    for relative in ("usr/share/tunaos/fork/fork-config.json", "usr/libexec/tunaos/fork-branding.sh",
                     "etc/xdg/kcm-about-distrorc", "usr/share/backgrounds/tunaos/tunaos-default.jpg"):
        target(root, relative)
    if not isinstance(base.get("assets"), dict):
        raise ValueError("invalid paired asset manifest")
    for asset in base["assets"].values():
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
            raise ValueError("invalid paired asset path")
        target(root, "usr/share/tunaos/fork/" + asset["path"])
    if info.get("image-name") != m["variant"] or info.get("image-flavor") != m["flavor"]:
        raise ValueError("identity staging cell does not match image-info")
    etc = root / "etc/os-release"
    link_state = {"target": os.readlink(etc) if etc.is_symlink() else None, "exists": etc.exists() or etc.is_symlink()}
    if etc.is_symlink():
        if os.readlink(etc) not in ("../usr/lib/os-release", "/usr/lib/os-release"):
            raise ValueError("unsupported os-release symlink")
        etc = None
    elif etc.exists():
        target(root, "etc/os-release")
    else:
        etc = None
    updates = {osr: os_release(osr.read_text(), m).encode()}
    if etc:
        updates[etc] = os_release(etc.read_text(), m).encode()
    for kind, destinations in {
        "logo": ["usr/share/pixmaps/tunaos.svg", "usr/share/icons/hicolor/scalable/apps/tunaos.svg"],
        "lettermark": ["usr/share/pixmaps/tunaos-lettermark.svg"],
    }.items():
        data = (manifest.parent / m["assets"][kind]["path"]).read_bytes()
        for dest in destinations:
            updates[target(root, dest)] = data
    updates[target(root, "etc/issue")] = b"\\S{PRETTY_NAME}\n\\r (\\l)\n"
    # Plain JSON is accepted by fastfetch's JSONC reader. Preserve the existing
    # base/route metadata in image-info instead of inventing a fork CPE vendor.
    updates[target(root, "etc/xdg/fastfetch/config.jsonc")] = (json.dumps({
        "logo": {"type": "none"}, "modules": ["title", {"type": "os", "format": "{pretty-name}"},
                                                  "kernel", "de", "wm", "packages"]}, indent=2) + "\n").encode()
    receipt = root / "usr/share/tunaos/fork-identity"
    applied_path = target(root, "usr/share/tunaos/fork-identity/applied.json")
    updates[target(root, "usr/share/tunaos/fork-identity/manifest.json")] = manifest.read_bytes()
    updates[target(root, "usr/share/tunaos/fork-identity/fork-config.json")] = (manifest.parent / "fork-config.json").read_bytes()
    updates[target(root, "usr/share/tunaos/fork-identity/os-release-link.json")] = (json.dumps(link_state, sort_keys=True) + "\n").encode()
    for asset in m["assets"].values():
        updates[target(root, "usr/share/tunaos/fork-identity/" + asset["path"])] = (manifest.parent / asset["path"]).read_bytes()
    # Validate all inputs and destinations before writes. No installer/Plymouth
    # changes: their unresolved contracts must not become a silent stock pass.
    if check:
        return
    for path, data in updates.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    applied = {str(path.relative_to(root)): hashlib.sha256(data).hexdigest()
               for path, data in updates.items() if not path.is_relative_to(receipt)}
    applied_path.write_text(json.dumps(applied, sort_keys=True, indent=2) + "\n")
    verify(root)


def verify(root):
    root = staging_root(root)
    m = load(target(root, "usr/share/tunaos/fork-identity/manifest.json"))
    applied = read_json(target(root, "usr/share/tunaos/fork-identity/applied.json"))
    link_state = read_json(target(root, "usr/share/tunaos/fork-identity/os-release-link.json"))
    etc = root / "etc/os-release"
    if (not isinstance(link_state, dict) or set(link_state) != {"target", "exists"}
            or type(link_state["exists"]) is not bool
            or link_state["target"] not in (None, "../usr/lib/os-release", "/usr/lib/os-release")
            or link_state != {"target": os.readlink(etc) if etc.is_symlink() else None,
                              "exists": etc.exists() or etc.is_symlink()}):
        raise ValueError("os-release link state does not match receipt")
    info = read_json(target(root, "usr/share/ublue-os/image-info.json"))
    if info.get("image-name") != m["variant"] or info.get("image-flavor") != m["flavor"]:
        raise ValueError("installed identity does not match image-info")
    if "fork-config" in info and (not isinstance(info["fork-config"], dict) or any(
            info["fork-config"].get(k) != m[k] for k in ("sources", "variant", "flavor", "platform"))):
        raise ValueError("installed identity does not match image-info source/platform receipt")
    required = {"usr/lib/os-release", "usr/share/pixmaps/tunaos.svg", "usr/share/icons/hicolor/scalable/apps/tunaos.svg",
                "usr/share/pixmaps/tunaos-lettermark.svg", "etc/issue", "etc/xdg/fastfetch/config.jsonc"}
    if not isinstance(applied, dict) or set(applied) not in (required, required | {"etc/os-release"}):
        raise ValueError("invalid applied identity receipt")
    for relative, digest in applied.items():
        path = target(root, relative)
        if not isinstance(digest, str) or not SHA.fullmatch(digest) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"applied identity hash mismatch: {relative}")
    for relative in ("usr/lib/os-release", "etc/os-release"):
        if relative not in applied:
            continue
        data = (root / relative).read_text()
        if os_release(data, m) != data:
            raise ValueError("applied os-release does not match identity intent")
    for kind, dest in (("logo", "usr/share/pixmaps/tunaos.svg"), ("logo", "usr/share/icons/hicolor/scalable/apps/tunaos.svg"),
                       ("lettermark", "usr/share/pixmaps/tunaos-lettermark.svg")):
        if applied[dest] != m["assets"][kind]["sha256"]:
            raise ValueError("applied logo does not match identity intent")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--check", action="store_true", help="validate all inputs and targets without writes")
    args = parser.parse_args()
    try:
        if not args.root.is_absolute() or args.root.resolve() == Path("/"):
            raise ValueError("identity staging requires an absolute non-live root")
        if args.manifest:
            apply(args.manifest, args.root, check=args.check)
        elif args.check:
            raise ValueError("--check needs --manifest")
        else:
            verify(args.root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: fork identity: {exc}", file=sys.stderr)
        return 2
    print("Identity inputs validated; no writes" if args.check else
          "Identity staging verified; installer, Plymouth and boot qualification remain BLOCKED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
