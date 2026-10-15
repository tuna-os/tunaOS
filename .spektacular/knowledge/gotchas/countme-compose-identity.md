---
tags: [countme, metadata, flavors, images]
---

# Compose defaults do not identify adoption categories

`build_scripts/90-image-info.sh` writes `image-tag=latest` and reads flavor from `DESKTOP_FLAVOR`. `scripts/resolve-flavor.sh` changes that variable to `desktop` for overlays. `scripts/build-image-inner.sh` passes the canonical original `IMAGE_NAME_VARIANT` separately from the publish name. Preserve original canonical variant and requested full flavor for adoption data; verify final metadata after desktop and overlay copies. Do not infer a runtime channel from the compose default.

Source: these files on main `7c9efe4f`; measured `rg` and source reads recorded in `docs/rfc/rfc012-private-adoption-metrics.md` and the adoption row in `docs/ci-troubleshooting.md`. The implementation now passes `TUNAOS_IMAGE_FLAVOR` from the build recipe through every family and reasserts metadata/masks after desktop copies. `tests/test_countme_images.py` verifies every matrix flavor in installer output; a built yellowfin-derived artifact preserves `gnome-hwe` instead of `desktop`. Complete boot validation for all families remains rollout work.
