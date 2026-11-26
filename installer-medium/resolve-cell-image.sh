#!/usr/bin/env bash
# Print the container image ref a medium cell installs (tunaOS#4907).
#
# Usage: installer-medium/resolve-cell-image.sh CELL
#
# The cell must be a supported row of scripts/lib/installer_medium.py; an
# unverified or headless cell fails with the resolver's reason. Variant cells
# resolve through scripts/published-image-ref.sh, so bonito-rawhide:gnome is
# bonito:gnome-rawhide and a fork's publish destination applies. Sibling image
# cells (tromso:kde) resolve to the sibling's published image with the desktop
# as tag; the CI track pins the digest before build-to-disk.sh runs.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
CELL="${1:?usage: resolve-cell-image.sh CELL}"

python3 - "${ROOT}" "${CELL}" <<'PY'
import importlib.util
import subprocess
import sys
from pathlib import Path

root, cell = Path(sys.argv[1]), sys.argv[2]
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
config = c.load(root / "tunaos.toml")
medium = c.installer_medium_policy()
try:
    row = medium.cell(config, cell)
except medium.MediumError as error:
    raise SystemExit(f"resolve-cell-image: {error}")
variant, _, flavor = cell.partition(":")
if variant in config.get("variants", {}):
    out = subprocess.run([str(root / "scripts/published-image-ref.sh"), variant, flavor],
                         capture_output=True, text=True, check=True)
    print(out.stdout.strip())
elif row["image"]:
    print(row["image"])
else:
    raise SystemExit(f"resolve-cell-image: sibling cell {cell} publishes no image")
PY
