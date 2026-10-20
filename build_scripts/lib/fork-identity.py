#!/usr/bin/env python3
"""Apply/verify experimental identity in an explicit staging root, never a live OS.

The build engine refuses this payload. Boot and installer artifacts remain unqualified.
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
    if not isinstance(m["assets"], dict) or set(m["assets"]) != {"logo", "lettermark", "splash", "splash_script"}:
        raise ValueError("identity logo and lettermark required")
    for kind, asset in m["assets"].items():
        if (not isinstance(asset, dict) or set(asset) != {"path", "sha256"}
                or not isinstance(asset["sha256"], str) or not SHA.fullmatch(asset["sha256"])
                or asset["path"] != f"fork-identity-assets/{asset['sha256']}.{ {'splash': 'png', 'splash_script': 'script'}.get(kind, 'svg')}"):
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


THEME = "fork-identity"
THEME_DIR = "usr/share/plymouth/themes/" + THEME
BOOT_FILES = {THEME_DIR + "/" + THEME + ".plymouth", THEME_DIR + "/splash.png",
              THEME_DIR + "/splash.script", "etc/plymouth/plymouthd.conf"}
INSTALLER_FILES = {"etc/bootc-installer/branding.json"}


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def boot_updates(manifest, root, m):
    """Select the generated script theme before dracut copies its assets."""
    import configparser
    conf = target(root, "etc/plymouth/plymouthd.conf")
    settings = configparser.ConfigParser(interpolation=None)
    settings.optionxform = str
    if conf.exists():
        settings.read_string(conf.read_text())
    if not settings.has_section("Daemon"):
        settings.add_section("Daemon")
    settings.set("Daemon", "Theme", THEME)
    import io
    output = io.StringIO()
    settings.write(output, space_around_delimiters=False)
    theme = ("[Plymouth Theme]\nName=" + m["name"] + "\nModuleName=script\n"
             "[script]\nImageDir=/" + THEME_DIR + "\nScriptFile=/" + THEME_DIR + "/splash.script\n")
    return {conf: output.getvalue().encode(),
            target(root, THEME_DIR + "/" + THEME + ".plymouth"): theme.encode(),
            target(root, THEME_DIR + "/splash.script"): (manifest.parent / m["assets"]["splash_script"]["path"]).read_bytes(),
            target(root, THEME_DIR + "/splash.png"): (manifest.parent / m["assets"]["splash"]["path"]).read_bytes()}


def installer_updates(manifest, root, m):
    """Project display intent only; never infer image references or routing IDs."""
    base = read_json(manifest.parent / "fork-config.json")
    path = target(root, "etc/bootc-installer/branding.json")
    branding = read_json(path) if path.exists() else {}
    if not isinstance(branding, dict):
        raise ValueError("installer branding must be an object")
    branding.update(name=m["name"], logo="/usr/share/pixmaps/tunaos.svg")
    for source, dest in (("homepage", "home_url"), ("documentation", "docs_url"), ("support", "support_url")):
        if source in base["intent"]["branding"]:
            branding[dest] = base["intent"]["branding"][source]
    updates = {path: json_bytes(branding)}
    path = target(root, "etc/bootc-installer/recipe.json")
    if path.exists():
        recipe = read_json(path)
        if not isinstance(recipe, dict):
            raise ValueError("installer recipe must be an object")
        old_name = recipe.get("distro_name", "TunaOS")
        tour = recipe.get("tour", {})
        if not isinstance(tour, dict):
            raise ValueError("installer recipe tour must be an object")
        for slide in tour.values():
            if not isinstance(slide, dict):
                raise ValueError("installer recipe slide must be an object")
            for field in ("title", "description"):
                if isinstance(slide.get(field), str):
                    if isinstance(old_name, str) and old_name and old_name != m["name"]:
                        pattern = "|".join(re.escape(name) for name in sorted({old_name, "TunaOS"}, key=len, reverse=True))
                        slide[field] = re.sub(pattern, lambda _: m["name"], slide[field])
            if slide.get("image") == "/run/host/usr/share/bootc-installer/images/tunaos-install.png":
                # Legacy recipe tours read host paths directly; the common
                # branding logo remains unprefixed for the shared resolver.
                slide["image"] = "/run/host" + branding["logo"]
        recipe.update(distro_name=m["name"], distro_logo=branding["logo"], welcome_title="Welcome to " + m["name"])
        updates[path] = json_bytes(recipe)
    # Existing catalog entries may include other distributions. Update only
    # the leaf whose exact image ref matches the recipe; preserve every option.
    path = target(root, "etc/bootc-installer/images.json")
    if path.exists():
        catalog = read_json(path)
        if not isinstance(catalog, dict) or not isinstance(catalog.get("images"), list):
            raise ValueError("installer catalog must contain an images list")
        recipe_path = target(root, "etc/bootc-installer/recipe.json")
        imgref = read_json(recipe_path).get("imgref") if recipe_path.exists() else None
        def project(nodes, registry=""):
            for node in nodes:
                if not isinstance(node, dict):
                    raise ValueError("invalid installer catalog node")
                registry_here = node.get("registry", registry)
                ref = node.get("imgref")
                if ref is None and "tag" in node and registry_here:
                    ref = f"{registry_here}:{node['tag']}"
                if imgref and ref == imgref:
                    node.update(name=m["name"], icon=branding["logo"])
                if "children" in node:
                    if not isinstance(node["children"], list):
                        raise ValueError("invalid installer catalog children")
                    project(node["children"], registry_here)
        project(catalog["images"])
        updates[path] = json_bytes(catalog)
    return updates


def apply_boot(manifest, root):
    m = load(manifest)
    root = root.resolve(strict=True)
    if root == Path("/") or not root.is_dir():
        raise ValueError("identity boot staging requires a non-live directory; builds remain blocked")
    updates = boot_updates(manifest, root, m)
    for path, data in updates.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def staging_root(root):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("identity staging root must be a directory")
    if root == Path("/"):
        raise ValueError("identity staging requires an explicit non-live root; builds remain blocked")
    return root



def apply(manifest, root, check=False):
    m = load(manifest)
    root = staging_root(root)
    osr = target(root, "usr/lib/os-release")
    image_info = target(root, "usr/share/ublue-os/image-info.json")
    info = read_json(image_info)
    base = read_json(manifest.parent / "fork-config.json")
    canonical = target(root, "usr/share/tunaos/fork/fork-config.json")
    if canonical.exists() and read_json(canonical) != base:
        raise ValueError("identity paired intent differs from canonical fork manifest")
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
    updates[target(root, "usr/libexec/tunaos/fork-identity.py")] = Path(__file__).read_bytes()
    updates.update(boot_updates(manifest, root, m))
    updates.update(installer_updates(manifest, root, m))
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
    # Validate all inputs and destinations before writes. Source-level consumers
    # do not qualify the installer artifact or the generated initramfs.
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
    canonical = target(root, "usr/share/tunaos/fork/fork-config.json")
    if canonical.exists() and read_json(canonical) != read_json(target(root, "usr/share/tunaos/fork-identity/fork-config.json")):
        raise ValueError("identity paired intent differs from canonical fork manifest")
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
                "usr/share/pixmaps/tunaos-lettermark.svg", "etc/issue", "etc/xdg/fastfetch/config.jsonc", "usr/libexec/tunaos/fork-identity.py"} | BOOT_FILES | INSTALLER_FILES
    for relative in ("etc/bootc-installer/recipe.json", "etc/bootc-installer/images.json"):
        if target(root, relative).exists():
            required.add(relative)
    if not isinstance(applied, dict) or set(applied) not in (required, required | {"etc/os-release"}):
        raise ValueError("invalid applied identity receipt")
    for relative, digest in applied.items():
        path = target(root, relative)
        if not isinstance(digest, str) or not SHA.fullmatch(digest) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"applied identity hash mismatch: {relative}")
    installed_manifest = target(root, "usr/share/tunaos/fork-identity/manifest.json")
    for path, data in {**boot_updates(installed_manifest, root, m), **installer_updates(installed_manifest, root, m)}.items():
        if path.read_bytes() != data:
            raise ValueError("boot or installer values do not match identity intent")
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
    parser.add_argument("--boot-only", action="store_true", help="stage theme before initramfs generation")
    parser.add_argument("--check", action="store_true", help="validate all inputs and targets without writes")
    args = parser.parse_args()
    try:
        if not args.root.is_absolute() or ((args.manifest or args.boot_only) and args.root.resolve() == Path("/")):
            raise ValueError("identity staging requires an absolute non-live root")
        if args.boot_only:
            if not args.manifest or args.check:
                raise ValueError("--boot-only needs --manifest and cannot use --check")
            apply_boot(args.manifest, args.root)
        elif args.manifest:
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
