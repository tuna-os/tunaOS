# aurora → TunaOS Upstream Port Guide

You are porting a commit from [ublue-os/aurora](https://github.com/ublue-os/aurora)
(a Fedora 43/44 bootc KDE Plasma image) into TunaOS's kde flavor.

## Your Task

1. Read the commit details and diff at the bottom of this file.
2. Read the relevant TunaOS files listed below before making any changes.
3. Decide what (if anything) should be ported. Document your reasoning.
4. Apply equivalent changes to TunaOS. If nothing should be ported, explain why clearly.

Always run `just fix && just check` after making changes to validate the build config.

---

## Repository Structure Map

| aurora (build_files) | TunaOS equivalent |
|---|---|
| `build_files/base/01-packages.sh` `FEDORA_PACKAGES[]` | `build_scripts/kde.sh` — `dnf install` block for Fedora (`IS_FEDORA == true`) |
| `build_files/base/01-packages.sh` `EXCLUDED_PACKAGES[]` | `build_scripts/kde.sh` — `dnf remove` / exclusion (`-x`) flags |
| `build_files/base/01-packages.sh` `NEGATIVO_PACKAGES[]` | `build_scripts/kde.sh` — negativo17 multimedia packages section |
| `build_files/dx/00-dx.sh` | `build_scripts/kde.sh` or `system_files_overrides/kde/` (DX is a separate flavor in TunaOS) |
| `system_files/shared/` | `system_files/` |
| `build_files/base/0X-*.sh` post-install steps | `build_scripts/kde.sh` `"post"` case block |
| `build_files/base/nvidia.sh` | `build_scripts/kde.sh` or a dedicated nvidia script (check `system_files_overrides/niri-gdx/`) |

## Key Files to Read First

- `build_scripts/kde.sh` — all KDE package installs and post-setup
- `system_files_overrides/kde/` — KDE-specific config files
- `system_files/` — shared config files for all flavors
- `Containerfile` lines ~140–155 — kde flavor build stage
- `build_scripts/lib.sh` — `IS_FEDORA`, `MAJOR_VERSION_NUMBER`, etc.

## Porting Rules

1. **Packages**: Aurora targets Fedora only. TunaOS KDE targets both Fedora (bonito) and EL10
   (yellowfin/albacore/skipjack). Port Fedora packages into the `IS_FEDORA == true` block in
   `build_scripts/kde.sh`. For packages that also exist in EL10 repos or the `ublue-os/packages`
   COPR, also add them to the EL10 block.

2. **COPR packages**: Aurora uses `ublue-os/packages`, `ublue-os/staging`, `ledif/kairpods`,
   `lizardbyte/beta`. TunaOS already has `ublue-os/packages` for EL10. Add Fedora-only COPRs
   inside the `IS_FEDORA == true` block only.

3. **Config files**: Mirror aurora's `system_files/shared/` → TunaOS's `system_files/`,
   and any KDE-specific overrides → `system_files_overrides/kde/`.

4. **Version-specific packages**: Aurora has `case "$FEDORA_MAJOR_VERSION"` blocks. TunaOS
   uses `$MAJOR_VERSION_NUMBER` from `lib.sh`. Replicate conditionals using that variable.

5. **DX flavor**: Aurora's `dx` variant maps to TunaOS's `kde` flavor with DX additions — check
   `system_files_overrides/kde/` for the right place.

6. **Do NOT port**: aurora/fedora branding, `plasma-lookandfeel-fedora` removal (TunaOS may
   have its own), signing keys, CI/CD files, Renovate config, documentation,
   `plasma-welcome-fedora` removal (check if TunaOS needs this), or `image.toml`.

7. **If nothing to port**: Still commit a file `.github/upstream-notes/aurora-{SHORT_SHA}.md`
   documenting why the commit was reviewed and skipped.

## Output

After making changes, run:
```
just fix && just check
```

Then commit everything with message:
```
port(kde): [aurora] {subject} ({short_sha})

Ported from ublue-os/aurora@{sha}

Changes:
- {bullet list of what was ported}
```

Do NOT create a PR — the workflow will do that after you finish.
