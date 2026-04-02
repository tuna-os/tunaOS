# Zirconium → TunaOS Upstream Port Guide

You are porting a commit from [zirconium-dev/zirconium](https://github.com/zirconium-dev/zirconium)
(a Fedora 44 bootc niri image) into TunaOS's niri flavor.

## Your Task

1. Read the commit details and diff at the bottom of this file.
2. Read the relevant TunaOS files listed below before making any changes.
3. Decide what (if anything) should be ported. Document your reasoning.
4. Apply equivalent changes to TunaOS. If nothing should be ported, explain why clearly.

Always run `just fix && just check` after making changes to validate the build config.

---

## Repository Structure Map

| Zirconium (mkosi) | TunaOS equivalent |
|---|---|
| `mkosi.conf` `[Packages]` section | `build_scripts/niri.sh` — the `dnf install` block for the relevant base (Fedora: `IS_FEDORA == true`, EL10: else branch) |
| `mkosi.extra/usr/...` | `system_files_overrides/niri/usr/...` (niri-specific) or `system_files/usr/...` (all flavors) |
| `mkosi.extra/etc/...` | `system_files_overrides/niri/etc/...` |
| `mkosi.postinst.chroot` | `build_scripts/niri.sh` — `"post"` case block at end of file |
| `mkosi.conf.d/` | Same as above, check which section applies |
| CI, Renovate, docs | **Skip** — do not port these |

## Key Files to Read First

- `build_scripts/niri.sh` — all niri package installs and post-setup
- `system_files_overrides/niri/` — niri-specific config files
- `Containerfile` lines ~154-160 — shows how niri flavor is built
- `build_scripts/lib.sh` — helper functions (`IS_FEDORA` variable, etc.)

## Porting Rules

1. **Packages**: Only port packages that exist in Fedora repos or the active COPRs already configured
   in `niri.sh` (e.g., `yalter/niri-git`, `avengemedia/dms-git`, `zirconium/packages`).
   If a package is Fedora-only and not available on EL10, add it only in the `IS_FEDORA == true` block.

2. **Config files**: Drop config files into `system_files_overrides/niri/` mirroring the path structure
   from `mkosi.extra/`. Create subdirectories as needed.

3. **Post-install scripts**: Add equivalent logic to the `"post"` case in `build_scripts/niri.sh`.

4. **EL10 variants**: TunaOS targets both Fedora (bonito) and EL10 (yellowfin/albacore/skipjack).
   If the change only makes sense for Fedora, wrap it in `if [[ $IS_FEDORA == true ]]; then`.

5. **Do NOT port**: branding changes, hostname changes, zirconium-specific signing keys/policies,
   changes to `os-release`, CI/CD files, Renovate config, or documentation.

6. **If nothing to port**: Still commit a file `.github/upstream-notes/zirconium-{SHORT_SHA}.md`
   documenting why the commit was reviewed and skipped.

## Output

After making changes, run:
```
just fix && just check
```

Then commit everything with message:
```
port(niri): [zirconium] {subject} ({short_sha})

Ported from zirconium-dev/zirconium@{sha}

Changes:
- {bullet list of what was ported}
```

Do NOT create a PR — the workflow will do that after you finish.
