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
| `build_files/base/01-packages.sh` `FEDORA_PACKAGES[]` | `manifests/desktops/kde.yaml` — `packages.fedora.packages` |
| `build_files/base/01-packages.sh` `EXCLUDED_PACKAGES[]` | `manifests/desktops/kde.yaml` — `packages.fedora.exclude` |
| `build_files/base/01-packages.sh` `NEGATIVO_PACKAGES[]` | `manifests/desktops/kde.yaml` — `packages.fedora.packages` |
| `build_files/dx/00-dx.sh` | `manifests/desktops/kde.yaml` or `system_files_overrides/kde/` (DX is a separate flavor in TunaOS) |
| `system_files/shared/` | `system_files/` |
| `build_files/base/0X-*.sh` post-install steps | `manifests/desktops/kde.yaml` — `post_install` / `post_install_inline` |
| `build_files/base/nvidia.sh` | `build_scripts/overlay/nvidia.sh` (nvidia is an overlay, not a KDE concern) |

## Key Files to Read First

KDE is installed from a **declarative manifest**, not a shell script. There is no
`build_scripts/kde.sh` — it was deleted once every base moved onto the generic
installer. Edit the manifest; the installer needs no changes to pick up a new
package, a new exclude, or a new COPR.

- `manifests/desktops/kde.yaml` — all KDE package sets, per package manager
- `build_scripts/desktop/install-desktop.sh` — the generic installer that reads it
- `system_files_overrides/kde/` — KDE-specific config files
- `system_files/` — shared config files for all flavors
- `Containerfile.el10` / `Containerfile.ubuntu` — the `kde` build stages
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
   | ✅ Available in EL10 | Add to **both** `packages.fedora.packages` **and** `packages.el10.packages` in `manifests/desktops/kde.yaml` |
   | ❌ Not available in EL10 | Add **only** under `packages.fedora.packages` — a tracking issue has already been opened |

   For a package that may or may not resolve, `packages.el10.optional` is
   installed best-effort and never fails the build.

   Active EL10 repos in TunaOS: base AlmaLinux/CentOS Stream 10, EPEL 10, CRB,
   `ublue-os/packages` COPR, `tuna-os/tunaos-packages` COPR (formerly `github-copr`; see `build_scripts/lib.sh`).

2. **COPR packages**: Aurora uses `ublue-os/packages`, `ublue-os/staging`, `ledif/kairpods`,
   `lizardbyte/beta`. TunaOS has `ublue-os/packages` for EL10. Add Fedora-only COPRs
   under `packages.fedora.copr`, EL10-only ones under `packages.el10.copr`.

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
