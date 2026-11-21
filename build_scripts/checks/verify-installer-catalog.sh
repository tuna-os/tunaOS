#!/usr/bin/env bash
# Build gate (tunaOS#4858): the installer's image list names this project's
# images only.
#
# Every installer frontend reads /etc/bootc-installer/images.json before the
# catalog it bundles from fisherman. That bundled catalog lists other
# projects' images: the Bonito Installer offered "Aurora > Aurora DX > Fedora
# 43" (ghcr.io/ublue-os/aurora-dx:43). 90-image-info.sh writes the system
# catalog; this check reads it back from the image and fails the build when:
#
#   - the catalog is missing, or is not a JSON object with a non-empty
#     `images` list (a frontend then falls back to the bundled catalog);
#   - a leaf names an image outside the registry and namespace of the
#     recipe's imgref. That ref is the configured publish destination
#     (scripts/published-image-ref.sh: [build.publish] in tunaos.toml);
#   - no leaf names the recipe's imgref, the image this installer installs.
#
# A leaf's references are `imgref`, `registry` + `tag` (the registry comes
# from the nearest node that sets it) and `nvidia_imgref`, the same rules as
# bootc-installer's shared/catalog/README.md.
#
# TUNAOS_INSTALLER_ETC points the check at a fixture directory.
set -euo pipefail

etc_dir="${TUNAOS_INSTALLER_ETC:-/etc/bootc-installer}"

python3 - "${etc_dir}/recipe.json" "${etc_dir}/images.json" <<'PYEOF'
import json
import sys

recipe_path, catalog_path = sys.argv[1:3]


def fail(message):
    print(f"ERROR: verify-installer-catalog: {message}", file=sys.stderr)
    print("TUNAOS_INSTALLER_CATALOG_FAIL")
    sys.exit(1)


try:
    with open(recipe_path) as f:
        imgref = json.load(f).get("imgref") or ""
except (OSError, ValueError) as error:
    fail(f"cannot read {recipe_path}: {error}")
if "/" not in imgref:
    fail(f"{recipe_path} has no published imgref (got {imgref!r})")
prefix = imgref.rsplit("/", 1)[0] + "/"

try:
    with open(catalog_path) as f:
        catalog = json.load(f)
except (OSError, ValueError) as error:
    fail(f"cannot read {catalog_path}: {error}; the installer would list its bundled catalog")
images = catalog.get("images") if isinstance(catalog, dict) else None
if not isinstance(images, list) or not images:
    fail(f"{catalog_path} has no non-empty `images` list; the installer would list its bundled catalog")

refs = []


def walk(nodes, registry, trail):
    for node in nodes:
        if not isinstance(node, dict):
            fail(f"{catalog_path}: entry under {trail or 'the root'} is not an object")
        name = trail + " > " + str(node.get("name", "?")) if trail else str(node.get("name", "?"))
        node_registry = node.get("registry") or registry
        if node.get("children"):
            walk(node["children"], node_registry, name)
            continue
        leaf = []
        if node.get("imgref"):
            leaf.append(node["imgref"])
        elif node.get("tag") and node_registry:
            leaf.append(f"{node_registry}:{node['tag']}")
        if node.get("nvidia_imgref"):
            leaf.append(node["nvidia_imgref"])
        if not leaf:
            fail(f"{catalog_path}: {name} names no image")
        refs.extend((name, ref) for ref in leaf)


walk(images, "", "")
foreign = [f"{name} ({ref})" for name, ref in refs if not ref.startswith(prefix)]
if foreign:
    fail(f"{catalog_path} lists images outside {prefix}: " + "; ".join(foreign))
if imgref not in (ref for _, ref in refs):
    fail(f"{catalog_path} does not list this image, {imgref}")
print(f"TUNAOS_INSTALLER_CATALOG_OK leaves={len(refs)} prefix={prefix} "
      + " ".join(ref for _, ref in refs))
PYEOF
