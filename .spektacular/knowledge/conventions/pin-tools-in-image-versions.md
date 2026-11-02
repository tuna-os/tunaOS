---
tags: [pins, tacklebox, formatting, ci]
---

# Pin each tool in its reviewed source contract

Pin image/runtime downloads (tacklebox, bootc, chezmoi, and similar tools) in
`image-versions.yaml` with a Renovate comment. Do not hardcode a SHA or version
in a workflow or script: callers read the reviewed pin
(`scripts/lib/tacklebox.sh` reads `TACKLEBOX_SHA` from it). Read the pin's
comment first: some pins are a FLOOR (tacklebox), some a CEILING (bootc).

The configuration-lint tools are one deliberate exception. actionlint,
ShellCheck, just and shfmt use `toolchain/lint-tools.json`, which records each
supported release asset and SHA-256. `scripts/lint_tools.py` is the only
installer; local checks and lint/format CI reject any other version. Do not
`brew install` current versions of those four tools.

Source: `image-versions.yaml`; `toolchain/lint-tools.json`;
`docs/LINTING.md`; `docs/ci-troubleshooting.md` §4 rows 22 and 41.
