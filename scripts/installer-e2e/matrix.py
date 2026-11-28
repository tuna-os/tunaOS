#!/usr/bin/env python3
"""Matrix rows for image-installer.yml: the promoted medium cells, or one cell by name.

Usage: scripts/installer-e2e/matrix.py [--cell VARIANT:FLAVOR | --supported]

Reads the resolved cells of scripts/lib/installer_medium.py. With no option
the rows are the promoted cells, which is the nightly. `--cell` takes any
supported cell, promoted or not, and fails with the resolver's reason for an
unverified or headless one, and with a plain reason for a cell that builds
for arm64 only: the workflow has no arm64 lane. `--supported` lists every
supported cell. The
desktop decides the input path, not the flavor: cosmic and niri have no
tested AT-SPI tree, so cosmic-nvidia uses the QEMU-key plus OCR fallback
(scripts/installer-e2e/ocr_fallback.py) as cosmic does. Prints
{"include": [...]} for fromJSON in the workflow.
"""

import argparse
import importlib.util
import json
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# Toolkits without a tested AT-SPI tree (shared/flow test contract rule 6).
OCR_FLAVORS = frozenset({"cosmic", "niri"})

# Cells whose compositor needs a DRM render node (tunaOS#4910): reuse the
# virgl GPU host path scripts/gpu-drm-preflight.sh proves out. niri needs a
# real GPU in the guest, measured, not assumed:
# - niri 26.04 src/backend/tty.rs (Tty::device_added) rejects any EGL device
#   whose extensions hold EGL_MESA_device_software (smithay EGLDevice::
#   is_software): `ensure!(!egl_device.is_software(), "software EGL renderers
#   are skipped")`. No config, debug option or environment variable skips it;
#   debug.render-drm-device only picks the node.
# - Hosted runner, virtio-vga-gl + egl-headless on vgem: the guest kernel
#   logs "[drm] features: -virgl" (run 46008379629, serial line 633), so the
#   guest has kms_swrast only and niri logs "failed to initialize renderer
#   ... software EGL renderers are skipped" (run 45651256265); the screen is
#   console text only (usb-1-live-boot.png). Plain virtio-vga: the same
#   (run 45637943733).
# - karnataka GPU pod (radeonsi): niri draws the live session (pod run on
#   medium 45986432375, stages 1-3 and 5-7).
GPU_FLAVORS = frozenset({"cosmic", "niri"})


def load_policy():
    """The validated installer_medium policy from tunaos.toml."""
    spec = importlib.util.spec_from_file_location(
        "installer_medium_policy", ROOT / "scripts/lib/installer_medium.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def input_for(desktop):
    """ocr-fallback for toolkits without AT-SPI, atspi for the rest."""
    return "ocr-fallback" if desktop in OCR_FLAVORS else "atspi"


# Cells of a flavor that needs no GPU elsewhere. brussels:xfce runs xfwl4
# (smithay, Wayland) on GNOME OS. Without virgl Mesa renders with llvmpipe,
# whose EGL device has no DRM render node, and xfwl4 stops with
# `failed to initialize gpu err=NoRenderNode` (hosted run 46048824774, guest
# `[drm] features: -virgl`); with virgl on the hosted runner (vgem) it draws
# its desktop (run 46051990086, stages 1-6 in 46065150653). bonito:xfce runs
# LightDM/X11 and needs none. albacore:kde (test branch only, a trial): the
# Plasma user session stays black on plain virtio-vga while the login
# screen draws (runs 46083819054, 46087879404).
GPU_CELLS = frozenset({"brussels:xfce", "albacore:kde"})


def gpu_for(desktop, cell=""):
    """True when the cell compositor needs the virgl GPU host path."""
    return desktop in GPU_FLAVORS or cell in GPU_CELLS


def rows(cells, variants=None):
    """Matrix rows for resolved installer_medium cell rows.

    `variants` is the set of variant names of tunaos.toml. A cell whose
    variant part is not one of them is a sibling image, which has no
    <flavor>-testing tag: the workflow reads its `image` instead.
    """
    out = []
    for cell in cells:
        name = cell["cell"]
        desktop = cell.get("desktop") or name.partition(":")[2].partition("-")[0]
        out.append(
            {
                "cell": name,
                "tag": name.replace(":", "-"),
                "desktop": desktop,
                "frontend": cell.get("frontend", desktop),
                "filesystem": cell["filesystem"],
                "bootloader": cell["bootloader"],
                "backend": cell["backend"],
                "secure_boot": cell.get("secure_boot") or "",
                "image": cell.get("image") or "",
                "sibling": variants is not None and name.partition(":")[0] not in variants,
                "promoted": bool(cell.get("promoted", True)),
                "secure_boot": cell.get("secure_boot") or "",
                "secure_boot_enroll": cell.get("secure_boot_enroll") or "",
                "input": input_for(desktop),
                "gpu": gpu_for(desktop, name),
            }
        )
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--cell", default="", help="one supported cell, promoted or not")
    group.add_argument("--supported", action="store_true", help="every supported cell")
    args = parser.parse_args(argv)
    policy = load_policy()
    with open(ROOT / "tunaos.toml", "rb") as handle:
        primary = tomllib.load(handle)
    try:
        if args.cell:
            selected = [policy.cell(primary, args.cell)]
            if "amd64" not in selected[0]["architectures"]:
                # The workflow boots the medium under x86_64 QEMU on an amd64 runner.
                raise policy.MediumError(
                    f"cell {args.cell} builds for {selected[0]['architectures']} only; "
                    "image-installer.yml has no arm64 lane"
                )
        else:
            selected = policy.cells(primary, promoted_only=not args.supported)
    except policy.MediumError as error:
        print(f"matrix: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"include": rows(selected, set(primary.get("variants", {})))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
