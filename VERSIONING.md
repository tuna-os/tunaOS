# Versioning Policy

## Scheme

tunaOS follows a **date-based versioning** scheme with variant prefix:

```
<VARIANT>-<YYYYMMDD>
```

Examples: `gnome-20260606`, `kde-20260606`, `cosmic-20260606`

## Rationale

tunaOS images are rebuilt daily from upstream sources. There are no feature releases — each build incorporates the latest upstream changes. Date-tags provide:

- **Freshness signal**: Users know exactly when the image was built
- **Traceability**: Tag maps directly to build timestamp
- **Simplicity**: No version number negotiation required

## Stability Tiers

| Tier | Pattern | Description |
|------|---------|-------------|
| **Daily** | `<variant>-<YYYYMMDD>` | Every successful daily build. Best freshness, highest change rate. |
| **Weekly** | `<variant>-weekly-<YYYYWW>` | Snapshot of most stable daily build each week. Recommended for regular users. |
| **LTS** | `<variant>-lts-<quarter>` | Quarterly stable snapshot. Recommended for enterprise deployments. |

## Variant Tags

| Tag | Description |
|-----|-------------|
| `gnome` | GNOME (stable) |
| `kde` | KDE Plasma |
| `cosmic` | COSMIC Desktop |
| `niri` | Niri (tiling Wayland) |
| `*-hwe` | Hardware Enablement kernel (suffix, e.g. `gnome-hwe`) |
| `*-nvidia` | NVIDIA drivers + CUDA (suffix, e.g. `gnome-nvidia`) |
| `*-nvidia-hwe` | Combined nvidia + HWE (suffix, e.g. `gnome-nvidia-hwe`) |

Hardware variants append to desktop tags: `<desktop>-hwe-<YYYYMMDD>`, `<desktop>-nvidia-<YYYYMMDD>`

## Breaking Changes

Breaking changes (kernel version bumps, desktop environment major upgrades, filesystem layout changes) are communicated via release notes. There is no major/minor version number — date tags are chronological, not semantic.

## Docker/OCI Tags

Container images follow the same scheme:

```
ghcr.io/tuna-os/yellowfin:gnome-20260606
ghcr.io/tuna-os/albacore:kde-hwe-20260606
```

The `:latest` tag points to the most recent daily build and is **not recommended** for production use.

## Migration

Users migrating from Universal Blue or Fedora Silverblue/Kinoite should rebase to a weekly or LTS tag:

```bash
rpm-ostree rebase ostree-unverified-registry:ghcr.io/tuna-os/yellowfin:gnome-weekly-202622
```

## References

- [AlmaLinux lifecycle](https://almalinux.org/blog/2025-05-27-welcoming-almalinux-10/)
- [bootc documentation](https://containers.github.io/bootc/)
- [Universal Blue](https://universal-blue.org/)

---
*Adopted: 2026-06-06 | Proposed by: strategist agent | Issue: #274*