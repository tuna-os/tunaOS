# Variant coverage decisions

Tracks tunaOS#4733 (part of #4730). This page records what the project does with
each non-nvidia variant in the browser-built ISO matrix. It records decisions
only. Which cells are declared, built or qualified is derived data. Read it from
`tunaos.toml` and `https://tunaos.org/iso-index.json`, not from this page.

## Rules that apply to every variant

- `nvidia` and `nvidia-hwe` flavors inherit their sibling's receipt (decision
  2026-11-12). They need no cell of their own. An `-hwe` nvidia flavor inherits
  from the hwe sibling.
- Every other variant changes the kernel, drivers, bootloader or installer
  behavior, so it needs its own strict receipt.
- A cell goes through the usual pipeline: current image and overlay, a `main`
  run of `ci.yml` with `strict_install_mode=both`, a committed receipt, then a
  cutover PR.
- The catalog marks a target `hardware-scope-unsupported` when its hardware scope
  is not `generic` (`qualify()` in `scripts/generate-catalog-snapshot.py`).

## Decisions

| Variant | Decision | Reason |
| --- | --- | --- |
| `hwe` | **Qualify.** Every desktop with a qualified std cell gets an hwe receipt. | The kernel and stack differ from std, and a generic guest can boot it. Gnome hwe is done on yellowfin, bonito, skipjack and albacore. |
| `cachyos` | **Qualify.** One receipt for each of marlin's desktops. | Different kernel and repositories, and a generic guest can boot it. |
| `zfs` | **Qualify, after harness work.** Add ZFS coverage to the strict harness first. | A receipt from a non-ZFS install says nothing about a ZFS root. |
| `asahi` | **Keep prebuilt.** Not browser-qualified. | Apple Silicon is arm64 only, and no guest emulates the SoC. See `docs/ASAHI-HARDWARE-TIERS.md`. |
| `t2`, `x13s` | **Keep prebuilt, held where already held.** Not browser-qualified. | They need Apple T2 or Snapdragon X13s hardware. A guest cannot test them. |
| Held flavors (`build_image = false`) | **Stay held** until the base can build them. Then treat them as the variant above. | A held flavor has no image to qualify. |

### The hardware-scoped exception

`asahi`, `t2` and `x13s` cannot satisfy the "no R2 object is needed" goal through
a guest receipt. The proposed exception to the R2 exit is:

1. These variants stay on the prebuilt path.
2. Their catalog status stays `unsupported` with `hardware-scope-unsupported`.
3. The browser builder may offer them only as unverified builds with a visible
   warning. This is optional and is not part of the R2 exit.
4. They become qualifiable only if a hardware tier (see
   `docs/ASAHI-HARDWARE-TIERS.md`) produces a receipt a maintainer accepts.

A maintainer must confirm point 3 before any UI work starts.

## Work that follows

Each item is a separate PR or run. None is done by this page.

- [ ] hwe: for each desktop with a qualified std cell on albacore, bonito,
  bonito-rawhide, skipjack and yellowfin, dispatch, fix, qualify, cut over.
- [ ] cachyos: the same for marlin's five desktops.
- [ ] zfs: add an install-on-ZFS step and cold and warm boot checks to the strict
  harness. Then qualify grouper gnome zfs.
- [ ] nvidia: keep `lanes/.scripts/nvidia-sync.py`-style generation in CI so each
  new qualified sibling gains its `inherits` entry.
- [ ] Large ISOs (for example nvidia-free `kde` on EL10, about 16 GB) need the GPU
  runner.
