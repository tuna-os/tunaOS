# Anime wallpapers

Each of the 14 variants has anime artwork based on its emoji and the coastal
scene in `scripts/branding/art-prompts.mjs`. These are the only wallpapers that
TunaOS ships. All six desktop families use the same asset for a variant. This
avoids copies for each desktop. The file for a variant is
`system_files/usr/share/backgrounds/tunaos/<variant>.jpg`.

`build_scripts/desktop/select-wallpaper.sh` selects in this order:

1. `<variant>-<desktop>.jpg`, if that desktop has an override.
2. `<variant>.jpg`, the anime artwork.

The selector copies the winner to `tunaos-default.jpg`, which the desktop configs
use. Desktop suffixes such as `gnome-nvidia` use the base desktop name.
If a known variant has neither file, the selector stops the build with an error.
Before `90-image-info.sh` writes the variant identity, the selector keeps the
shipped `tunaos-default.jpg`. That file is a copy of the albacore artwork,
because albacore has the generic 🐟 emoji.

## Source and resolution

OpenAI's image-generation tool produced the images. The original PNGs are
1672 × 941 pixels, about 16:9. These are the native output dimensions, not native
4K. The JPEGs keep those dimensions. Conversion does not resize, crop, or
retouch the artwork. Pillow converts to RGB with `quality=95`, `subsampling=0`,
`optimize=False`, and `progressive=False`.

The review bundle includes original PNGs, JPEGs, a labeled contact sheet, prompts,
asset dimensions, and SHA-256 checksums. The contact sheet uses small previews;
it is not a wallpaper source. `anime-wallpapers.json` records the generation
prompts, the path of each shipped JPEG, and its checksum. The `original` paths
refer to the review bundle, not to this repository.

## Verify

Run `bats tests/bats/test_variant_identity.bats tests/bats/test_wallpaper_contract.bats`
to check selector priority, desktop suffixes, assets, the missing-wallpaper error,
the GNOME wallpaper list, and the Plasma path. These tests examine the source
tree. Inspect the built OS image to verify
that it contains the selected artwork before you claim runtime verification.

The identity writer runs the same selector after final identity updates and overlay
file copies. It uses the original image flavor to retain desktop overrides for
overlay targets. `pytest tests/test_anime_finalization.py` executes these
writer sequences in isolated filesystems, including the real JPEG assets.
