---
tags: [tacklebox, iso]
---

# tacklebox

`tuna-os/tacklebox`: the ISO builder. Takes a `recipe.json` of bootable environments and produces a live ISO with a dedup squashfs store. Run in a container by `scripts/lib/tacklebox.sh` / `scripts/build-iso-tacklebox.sh`; pinned in `image-versions.yaml`. Knobs are `TBOX_*` env vars.
