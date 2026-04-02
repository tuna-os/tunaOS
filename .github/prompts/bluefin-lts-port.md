# bluefin-lts → TunaOS Upstream Port Guide

You are porting a commit from [ublue-os/bluefin-lts](https://github.com/ublue-os/bluefin-lts)
(a CentOS Stream 10 / EL10 bootc GNOME image) into TunaOS's gnome flavor.

## Your Task

1. Read the commit details and diff at the bottom of this file.
2. Read the relevant TunaOS files listed below before making any changes.
3. Decide what (if anything) should be ported. Document your reasoning.
4. Apply equivalent changes to TunaOS. If nothing should be ported, explain why clearly.

Always run `just fix && just check` after making changes to validate the build config.

---

## Why bluefin-lts Is Directly Relevant

bluefin-lts uses an **almost identical directory structure** to TunaOS (both EL10-based):

| bluefin-lts | TunaOS equivalent |
|---|---|
| `build_scripts/gnome.sh` | `build_scripts/gnome.sh` |
| `system_files/` | `system_files/` |
| `system_files_overrides/gnome/` | `system_files_overrides/gnome/` |
| `system_files_overrides/dx/` | `system_files_overrides/dx/` (if present) |
| `Containerfile` gnome stage | `Containerfile` gnome stage (lines ~130–145) |
| `build_scripts/lib.sh` | `build_scripts/lib.sh` |

This means many changes are nearly direct copies. Check the diff carefully —
if the upstream change is in one of these files, the port is often trivial.

## Key Files to Read First

- `build_scripts/gnome.sh` — all gnome package installs and post-setup
- `system_files_overrides/gnome/` — gnome-specific config files
- `system_files/` — shared config files for all flavors
- `Containerfile` lines ~130–145 — gnome flavor build stage
- `build_scripts/lib.sh` — `IS_FEDORA`, `MAJOR_VERSION_NUMBER`, etc.

## Porting Rules

1. **Packages**: Port packages from `build_scripts/gnome.sh` directly. If the upstream adds
   a package in an EL10-specific COPR that TunaOS already uses (e.g., `jreilly1821/c10s-gnome-49`,
   `jreilly1821/c10s-gnome-50-fresh`, `ublue-os/packages`), it's safe to add.
   If it requires a new COPR not already in TunaOS, note it in the PR body.

2. **Config files**: Copy config files from `system_files/` and `system_files_overrides/gnome/`
   verbatim, preserving the same path structure.

3. **Fedora guard**: TunaOS also supports Fedora (bonito variant). If the upstream change is
   EL10-specific, wrap additions in `if [[ $IS_FEDORA == false ]]; then`.

4. **Do NOT port**: branding changes (`/etc/os-release`, logos, wallpapers), signing keys
   (`cosign.pub`), bluefin-specific services or scripts referencing "bluefin",
   CI/CD files, Renovate config, documentation, or `image.toml`.

5. **gnome50 variant**: TunaOS has both `gnome` (GNOME 49) and `gnome50` flavors. If the
   upstream change is GNOME-version-specific, check whether it applies to both or just one,
   and use `${DESKTOP_FLAVOR:-gnome}` checks as needed.

6. **If nothing to port**: Still commit a file `.github/upstream-notes/bluefin-lts-{SHORT_SHA}.md`
   documenting why the commit was reviewed and skipped.

## Output

After making changes, run:
```
just fix && just check
```

Then commit everything with message:
```
port(gnome): [bluefin-lts] {subject} ({short_sha})

Ported from ublue-os/bluefin-lts@{sha}

Changes:
- {bullet list of what was ported}
```

Do NOT create a PR — the workflow will do that after you finish.
