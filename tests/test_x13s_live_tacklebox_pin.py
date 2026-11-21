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

Build-bonito run 44880904535 then built the ISO, but its boot gate waited
900 s: at 453ffb4 the X13s initqueue retried without a deadline and dracut fell
to emergency mode with no reason. tacklebox 02e12e8 (tacklebox#507) stops it
with the reason once the ADSP budget is spent.

Falsification: structural. Reverting the tacklebox pin in image-versions.yaml
to 1427011a3d408e778a87ff29184bc0b0cb98e9ab or to
453ffb4a9074895b5cc26230b1e374d8a2b436ab fails this test.
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

# Revisions that accept the shim but retry the X13s initqueue without a deadline.
NO_ADSP_DEADLINE_PINS = {
    "453ffb4a9074895b5cc26230b1e374d8a2b436ab",  # tacklebox#505
    "c60ef57",  # tacklebox#506 (prefix)
}


def test_tacklebox_pin_accepts_fedora_signed_shim() -> None:
    downloads = yaml.safe_load((ROOT / "image-versions.yaml").read_text())["downloads"]
    pin = downloads["tacklebox"]

    assert re.fullmatch(r"[0-9a-f]{40}", pin), pin
    assert pin not in SHIM_REJECTING_PINS, (
        f"tacklebox {pin[:7]} rejects Fedora's signed shimaa64.efi (COFF symbols)"
    )


def test_tacklebox_pin_stops_the_x13s_initqueue_with_a_reason() -> None:
    pin = yaml.safe_load((ROOT / "image-versions.yaml").read_text())["downloads"]["tacklebox"]
    assert not any(pin.startswith(bad) for bad in NO_ADSP_DEADLINE_PINS), (
        f"tacklebox {pin[:7]} lets the X13s initqueue hang until dracut's timeout"
    )
