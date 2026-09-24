---
tags: [pins, tacklebox, formatting, ci]
---

# Pin tools in `image-versions.yaml`, nowhere else

Pin external tools (tacklebox, shfmt, bootc, chezmoi, ...) in `image-versions.yaml` with a Renovate comment. Do not hardcode a SHA or version in a workflow or script: callers fall back to the reviewed pin (`scripts/lib/tacklebox.sh` reads `TACKLEBOX_SHA` from it). Read the pin's comment first: some pins are a FLOOR (tacklebox), some a CEILING (bootc).

shfmt is pinned (`shfmt: "v3.14.1"`); `just fix` and `just check` both refuse a different shfmt version (override: `TUNAOS_ALLOW_SHFMT_DRIFT=1`). Do not `brew install shfmt` latest.

Source: `image-versions.yaml`; `docs/ci-troubleshooting.md` §4 rows 22 and 41.
