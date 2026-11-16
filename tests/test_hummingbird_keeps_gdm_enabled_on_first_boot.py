"""hummingbird:tuna booted to a console because first boot disabled gdm.

The Hummingbird base ships server presets: no display manager is named, and
the last preset is `disable *`. The build enables gdm with `systemctl enable`
and a forced graphical.target.wants link. On first boot systemd applies preset
policy and removes both. Measured on the Gate of run 43868943848:

    [ 8.785223] systemd[1]: Removed '.../graphical.target.wants/gdm.service'.
    [ 8.785701] systemd[1]: Removed '.../display-manager.service'.

graphical.target only Wants=display-manager.service. The VM reached a login
prompt on the console with no display manager, so the desktop contract never
printed its marker and the Gate failed after 900 seconds.

The preset sits in system_files_overrides/hummingbird, so no other variant
changes its first-boot policy.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESET = (
    ROOT
    / "system_files_overrides/hummingbird/usr/lib/systemd/system-preset"
    / "50-tunaos-hummingbird.preset"
)
SHARED_PRESET = ROOT / "system_files/usr/lib/systemd/system-preset/50-tunaos.preset"


def _directives(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        verb, _, unit = line.partition(" ")
        out[unit.strip()] = verb
    return out


def test_hummingbird_names_gdm_so_first_boot_keeps_it() -> None:
    assert PRESET.is_file(), f"hummingbird-scoped preset missing: {PRESET}"
    assert _directives(PRESET).get("gdm.service") == "enable"


def test_the_preset_sorts_before_the_base_catch_all_disable() -> None:
    """The base ends with 99-default-disable.preset; a higher number never wins."""
    prefix = int(PRESET.name.split("-", 1)[0])
    assert prefix < 99


def test_gdm_is_not_enabled_for_every_variant() -> None:
    """KDE, niri and cosmic choose their own display manager."""
    assert "gdm.service" not in _directives(SHARED_PRESET)
