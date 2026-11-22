#!/usr/bin/env bash
# Print the container image ref a medium cell installs (tunaOS#4907).
#
# Usage: installer-medium/resolve-cell-image.sh CELL
#
# Variant cells resolve through scripts/published-image-ref.sh. Sibling image
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
variant, _, flavor = cell.partition(":")
if variant in config.get("variants", {}):
    out = subprocess.run([str(root / "scripts/published-image-ref.sh"), variant, flavor],
                         capture_output=True, text=True, check=True)
    print(out.stdout.strip())
else:
    sibling = next((s for s in config.get("sibling_images", []) if s.get("id") == variant), None)
    if sibling is None or flavor not in {str(d).lower() for d in sibling.get("desktops", [])}:
        raise SystemExit(f"resolve-cell-image: unknown cell {cell}")
    print(f"{sibling['image']}:{flavor}")
PY
