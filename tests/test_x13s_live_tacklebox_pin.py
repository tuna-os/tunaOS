"""The X13s live ISO needs a tacklebox that accepts Fedora's signed shim (tunaOS#3368).

What shipped: tacklebox 1427011 (tacklebox#497) rejected every EFI input with
a COFF symbol table. Fedora 44 shim-aa64 16.1-7 shimaa64.efi has 4593 COFF
symbols at 0xda000, inside the bytes its Authenticode signature covers, so
scripts/x13s-live-inputs.sh cannot strip them without voiding the signature.

What was measured: build-bonito run 44863755033 (job 136738023488) stopped
the bonito:gnome-x13s live ISO with "X13s live: COFF symbols are unsupported
in EFI inputs". tacklebox 453ffb4 (tacklebox#505) accepts a symbol table that
lies inside the file and outside every section.

What this holds: the tacklebox pin is not one of the --x13s-live revisions
that reject the shim.

Falsification: structural. Reverting the tacklebox pin in image-versions.yaml
to 1427011a3d408e778a87ff29184bc0b0cb98e9ab fails this test.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

# The tacklebox main revisions with `build --x13s-live` before tacklebox#505.
SHIM_REJECTING_PINS = {
    "1427011a3d408e778a87ff29184bc0b0cb98e9ab",  # tacklebox#497
    "9312b24338b689a53f14dc59f28615c4e83273cf",  # tacklebox#500
    "4e9e632d0201258d154a4ff364c55c61865e37f6",  # tacklebox#504
}


def test_tacklebox_pin_accepts_fedora_signed_shim() -> None:
    downloads = yaml.safe_load((ROOT / "image-versions.yaml").read_text())["downloads"]
    pin = downloads["tacklebox"]

    assert re.fullmatch(r"[0-9a-f]{40}", pin), pin
    assert pin not in SHIM_REJECTING_PINS, (
        f"tacklebox {pin[:7]} rejects Fedora's signed shimaa64.efi (COFF symbols)"
    )
