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

> **Goal: incorporate as much as possible from upstream.**
> At the end of this file is an **EL10 Package Availability Check** section with
> definitive results from a live AlmaLinux Kitten 10 + EPEL 10 + CRB container query.
> Use those results — do not guess.

1. **Packages — use the availability report**:

   Aurora targets Fedora only. TunaOS KDE targets both Fedora (`bonito`) and EL10
   (`yellowfin`/`albacore`/`skipjack`). For every package in the diff, check the
   `## EL10 Package Availability Check` section at the bottom of this file:

   | Result | Action |
   |---|---|
   | ✅ Available in EL10 | Add to **both** the `IS_FEDORA == true` block **and** the `else` (EL10) block in `build_scripts/kde.sh` |
   | ❌ Not available in EL10 | Add **only** inside `if [[ $IS_FEDORA == true ]]; then` — a tracking issue has already been opened |

   Active EL10 repos in TunaOS: base AlmaLinux/CentOS Stream 10, EPEL 10, CRB,
   `ublue-os/packages` COPR, `tuna-os/github-copr` COPR (see `build_scripts/lib.sh`).

2. **COPR packages**: Aurora uses `ublue-os/packages`, `ublue-os/staging`, `ledif/kairpods`,
   `lizardbyte/beta`. TunaOS has `ublue-os/packages` for EL10. Add Fedora-only COPRs
   inside the `IS_FEDORA == true` block only.

3. **Config files**: Mirror aurora's `system_files/shared/` → TunaOS `system_files/`,
   and KDE-specific overrides → `system_files_overrides/kde/`.

4. **Version-specific packages**: Aurora uses `case "$FEDORA_MAJOR_VERSION"` blocks. TunaOS
   uses `$MAJOR_VERSION_NUMBER` from `lib.sh`. Replicate conditionals using that variable.

5. **DX flavor**: Aurora's `dx` variant maps to TunaOS's `kde` flavor with DX additions —
   check `system_files_overrides/kde/` for the right place.

6. **Do NOT port**: aurora/fedora branding, signing keys, CI/CD files, Renovate config,
   documentation, `image.toml`, or `os-release` changes.

7. **If nothing to port**: Still commit `.github/upstream-notes/aurora-{SHORT_SHA}.md`
   explaining why the commit was skipped.

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
