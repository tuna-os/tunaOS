#!/usr/bin/env python3
"""Matrix rows for image-installer.yml: one per promoted medium cell.

Reads [installer_medium.cells] from tunaos.toml through
scripts/lib/installer_medium.py, so a new promoted cell joins the nightly
without a workflow edit. Flavor decides the input path: cosmic and niri
have no tested AT-SPI tree, so they use the QEMU-key plus OCR fallback
(scripts/installer-e2e/ocr_fallback.py); every other frontend drives the
AT-SPI matchers. Prints {"include": [...]} for fromJSON in the workflow.
"""

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
# virgl GPU host path scripts/gpu-drm-preflight.sh proves out.
GPU_FLAVORS = frozenset({"cosmic", "niri"})


def load_policy():
    """The validated installer_medium policy from tunaos.toml."""
    spec = importlib.util.spec_from_file_location(
        "installer_medium_policy", ROOT / "scripts/lib/installer_medium.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def input_for(flavor):
    """ocr-fallback for toolkits without AT-SPI, atspi for the rest."""
    return "ocr-fallback" if flavor in OCR_FLAVORS else "atspi"


def gpu_for(flavor):
    """True when the cell compositor needs the virgl GPU host path."""
    return flavor in GPU_FLAVORS


def rows(cells):
    """Matrix rows for validated installer_medium cell rows."""
    out = []
    for cell in cells:
        name = cell["cell"]
        _, _, flavor = name.partition(":")
        out.append(
            {
                "cell": name,
                "tag": name.replace(":", "-"),
                "filesystem": cell["filesystem"],
                "bootloader": cell["bootloader"],
                "backend": cell["backend"],
                "input": input_for(flavor),
                "gpu": gpu_for(flavor),
            }
        )
    return out


def main(argv=None):
    policy = load_policy()
    with open(ROOT / "tunaos.toml", "rb") as handle:
        primary = tomllib.load(handle)
    print(json.dumps({"include": rows(policy.cells(primary))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
