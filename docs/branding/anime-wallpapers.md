# Anime wallpapers

Each of the 14 variants has anime artwork based on its emoji and the coastal
scene in `scripts/branding/art-prompts.mjs`. All six desktop families use the
same asset for a variant. This avoids copies for each desktop.

`build_scripts/desktop/select-wallpaper.sh` selects in this order:

1. `<variant>-<desktop>.jpg`, if that desktop has an override.
2. `<variant>-anime.jpg`, the shared artwork.
3. `<variant>.jpg`, the vector fallback.
4. The existing `tunaos-default.jpg`, if the variant is unknown.

The selector copies the winner to `tunaos-default.jpg`, which the desktop configs
use. Desktop suffixes such as `gnome-nvidia` use the base desktop name.
The existing renderer still owns the vector wallpapers. It does not replace
the `-anime.jpg` files.

## Source and resolution

OpenAI's image-generation tool produced the images. The original PNGs are
1672 × 941 pixels, about 16:9. These are the native output dimensions, not native
4K. The JPEGs keep those dimensions. Conversion does not resize, crop, or
retouch the artwork. Pillow converts to RGB with `quality=95`, `subsampling=0`,
`optimize=False`, and `progressive=False`.

The review bundle includes original PNGs, JPEGs, a labeled contact sheet, prompts,
asset dimensions, and SHA-256 checksums. The contact sheet uses small previews;
it is not a wallpaper source. `anime-wallpapers.json` records the generation
prompts and checksums for the JPEGs.

## Verify

Run `bats tests/bats/test_variant_identity.bats tests/bats/test_wallpaper_contract.bats`
to check selector priority, desktop suffixes, assets, fallbacks, and the Plasma
path. These tests examine the source tree. Inspect the built OS image to verify
that it contains the selected artwork before you claim runtime verification.
