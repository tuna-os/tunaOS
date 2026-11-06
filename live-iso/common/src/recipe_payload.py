#!/usr/bin/env python3
"""Bind the installer's exact ISO payload ref at live-customize time.

Called by live-iso/common/src/customize-live.sh (sibling file, ships to the
ISO in the same staged directory) after it probes the installer backend:

    python3 recipe_payload.py <recipe.json> <bootloader> <composefs> <filesystem>

build_scripts/90-image-info.sh owns the canonical published tracking ref
(recipe["imgref"]). The ISO builder supplies its exact embedded store ref for
this invocation via TUNA_LIVE_PAYLOAD_REF; per-platform and grouped ISO
payload tags differ, so the local source is never derived from the tracking
ref. Live-overlay artifacts are intermediate layers, not ISO payloads: with
TUNA_LIVE_DEFER_LOCAL_IMGREF=1 any stale local_imgref is removed and binding
is left to the downstream packager. Anything else fails closed, because an
installer pointed at the wrong store silently installs the wrong image.

A standalone module (not an inline heredoc) so regression tests execute this
exact file instead of a sed-extracted copy of a shell script.
"""

import json
import os
import sys


STOCK_UNRESOLVED_REF = "ghcr.io/tuna-os/tunaos:latest"


def main(argv):
    if len(argv) != 5:
        print(f"usage: {argv[0]} <recipe.json> <bootloader> <composefs> <filesystem>",
              file=sys.stderr)
        return 2
    path, bootloader, composefs, filesystem = argv[1:5]
    with open(path) as f:
        recipe = json.load(f)
    recipe["bootloader"] = bootloader
    recipe["composeFsBackend"] = composefs == "true"
    recipe["filesystem"] = filesystem

    # build_scripts/90-image-info.sh owns the canonical published tracking ref.
    # The ISO builder supplies its exact embedded store ref to this invocation.
    # Never derive the local source from the tracking ref: per-platform and grouped
    # ISO payload tags differ.
    imgref = recipe.get("imgref")
    if not imgref or imgref == STOCK_UNRESOLVED_REF:
        raise SystemExit("customize-live: installer recipe has no resolved published imgref")
    payload_ref = os.environ.get("TUNA_LIVE_PAYLOAD_REF")
    if payload_ref:
        recipe["local_imgref"] = f"containers-storage:{payload_ref}"
    elif os.environ.get("TUNA_LIVE_DEFER_LOCAL_IMGREF") == "1":
        # Live-overlay artifacts are intermediate layers, not ISO payloads. Leave
        # local source binding to the downstream packager that chooses the store ref.
        recipe.pop("local_imgref", None)
    else:
        raise SystemExit("customize-live: ISO payload ref was not supplied")

    with open(path, "w") as f:
        json.dump(recipe, f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
