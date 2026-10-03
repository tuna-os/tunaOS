# Organization Release Inventory

**Measured 2026-10-03** from the GitHub API by
[`scripts/gen-org-release-inventory.py`](../scripts/gen-org-release-inventory.py).

This reproducible audit covers GitHub distribution for active public
repositories in the `tuna-os` organization. It reports tags, published
GitHub Releases, and the assets attached to each latest release. It does
**not** infer OCI, Flatpak, package-repository, app-store, or notarization
status: those planes need their own authenticated inventories. An asset
signal below is based on its filename and is not a cryptographic validation.

## Current snapshot

- Active public repositories: **44**
- Repositories with a published GitHub Release: **15**
- Repositories with no Git tag or GitHub Release: **27**
- Latest visible version pattern: **11 SemVer**, **2 date-based**

| Repository | Latest Git tag | Latest GitHub Release | Version pattern | Latest release assets |
|---|---|---|---|---|
| [.github](https://github.com/tuna-os/.github) | — | — | none | 0 |
| [bluefin-cli](https://github.com/tuna-os/bluefin-cli) | `v0.11.5` | [`v0.11.5`](https://github.com/tuna-os/bluefin-cli/releases/tag/v0.11.5) | SemVer | 17 (checksum, installer/package) |
| [blueshell](https://github.com/tuna-os/blueshell) | `tip` | [`tip`](https://github.com/tuna-os/blueshell/releases/tag/tip) (pre-release) | other | 2 (installer/package) |
| [bootc-installer](https://github.com/tuna-os/bootc-installer) | `v2026.09.26-253d6938` | [`v2026.09.26-253d6938`](https://github.com/tuna-os/bootc-installer/releases/tag/v2026.09.26-253d6938) | date-based | 3 (installer/package) |
| [bootc-installer-asahi](https://github.com/tuna-os/bootc-installer-asahi) | — | — | none | 0 |
| [bootc-migrate](https://github.com/tuna-os/bootc-migrate) | `v0.6.0` | [`v0.6.0`](https://github.com/tuna-os/bootc-migrate/releases/tag/v0.6.0) | SemVer | 4 (checksum) |
| [branding](https://github.com/tuna-os/branding) | — | — | none | 0 |
| [bst-ci](https://github.com/tuna-os/bst-ci) | — | — | none | 0 |
| [ccleft](https://github.com/tuna-os/ccleft) | — | — | none | 0 |
| [changelog-action](https://github.com/tuna-os/changelog-action) | — | — | none | 0 |
| [compass](https://github.com/tuna-os/compass) | `v0.28.2` | [`v0.28.2`](https://github.com/tuna-os/compass/releases/tag/v0.28.2) | SemVer | 0 |
| [corral](https://github.com/tuna-os/corral) | `v0.6.0` | [`plugins-dff3acc926118a7c969d67daaa6933c31366e669`](https://github.com/tuna-os/corral/releases/tag/plugins-dff3acc926118a7c969d67daaa6933c31366e669) | other | 18 (no integrity marker in name) |
| [docs](https://github.com/tuna-os/docs) | — | — | none | 0 |
| [dualcut](https://github.com/tuna-os/dualcut) | `v0.27.1` | [`v0.27.1`](https://github.com/tuna-os/dualcut/releases/tag/v0.27.1) | SemVer | 2 (installer/package) |
| [finupdate](https://github.com/tuna-os/finupdate) | — | — | none | 0 |
| [fisherman](https://github.com/tuna-os/fisherman) | `v0.4.0` | [`v0.4.0`](https://github.com/tuna-os/fisherman/releases/tag/v0.4.0) | SemVer | 3 (checksum) |
| [flatpak-index](https://github.com/tuna-os/flatpak-index) | — | — | none | 0 |
| [gnome-hive-monitor](https://github.com/tuna-os/gnome-hive-monitor) | — | — | none | 0 |
| [gtk-office-suite](https://github.com/tuna-os/gtk-office-suite) | `v2.1.0` | [`v2.1.0`](https://github.com/tuna-os/gtk-office-suite/releases/tag/v2.1.0) | SemVer | 0 |
| [hive](https://github.com/tuna-os/hive) | — | — | none | 0 |
| [hive-operator](https://github.com/tuna-os/hive-operator) | — | — | none | 0 |
| [homebrew-tap](https://github.com/tuna-os/homebrew-tap) | — | — | none | 0 |
| [iced](https://github.com/tuna-os/iced) | — | — | none | 0 |
| [iso-builder](https://github.com/tuna-os/iso-builder) | — | — | none | 0 |
| [libcosmic](https://github.com/tuna-os/libcosmic) | — | — | none | 0 |
| [mandelbrot](https://github.com/tuna-os/mandelbrot) | `v14.1.1` | — | SemVer | 0 |
| [mariner](https://github.com/tuna-os/mariner) | — | — | none | 0 |
| [PaperWM](https://github.com/tuna-os/PaperWM) | — | — | none | 0 |
| [protota](https://github.com/tuna-os/protota) | — | — | none | 0 |
| [quickcast](https://github.com/tuna-os/quickcast) | `v2.3.2` | — | SemVer | 0 |
| [rdocx](https://github.com/tuna-os/rdocx) | — | — | none | 0 |
| [remora](https://github.com/tuna-os/remora) | `v0.4.3` | [`v0.4.3`](https://github.com/tuna-os/remora/releases/tag/v0.4.3) | SemVer | 3 (checksum) |
| [rust-atomicwrites](https://github.com/tuna-os/rust-atomicwrites) | — | — | none | 0 |
| [scoop-bucket](https://github.com/tuna-os/scoop-bucket) | — | — | none | 0 |
| [spindle](https://github.com/tuna-os/spindle) | `v0.0.2` | [`v0.0.2`](https://github.com/tuna-os/spindle/releases/tag/v0.0.2) (pre-release) | SemVer | 6 (checksum, SBOM) |
| [suite-common](https://github.com/tuna-os/suite-common) | — | — | none | 0 |
| [suite-common-rust](https://github.com/tuna-os/suite-common-rust) | — | — | none | 0 |
| [tacklebox](https://github.com/tuna-os/tacklebox) | — | — | none | 0 |
| [Tavern](https://github.com/tuna-os/Tavern) | `v0.1.64` | [`v0.1.64`](https://github.com/tuna-os/Tavern/releases/tag/v0.1.64) | SemVer | 5 (checksum, SBOM, installer/package) |
| [tromso](https://github.com/tuna-os/tromso) | — | — | none | 0 |
| [tunaOS](https://github.com/tuna-os/tunaOS) | `xfce-nvidia-20260705` | [`xfce-20261003`](https://github.com/tuna-os/tunaOS/releases/tag/xfce-20261003) | date-based | 3 (SBOM) |
| [tunaos-packages](https://github.com/tuna-os/tunaos-packages) | `xfwl4-vendor-465880f6` | [`roost-vendor-5eee55c`](https://github.com/tuna-os/tunaos-packages/releases/tag/roost-vendor-5eee55c) | other | 1 (no integrity marker in name) |
| [wootc](https://github.com/tuna-os/wootc) | `v0.1.0-alpha.1` | [`auto-v20260831-37152bc`](https://github.com/tuna-os/wootc/releases/tag/auto-v20260831-37152bc) (pre-release) | other | 12 (checksum, installer/package) |
| [xfce-linux](https://github.com/tuna-os/xfce-linux) | — | — | none | 0 |

## How to use this inventory

- Treat `none` and `other` as triage inputs, not automatic defects. Some
  repositories do not publish a consumer artifact.
- Follow a repository's release tracker before adding another issue. The
  inventory measures state; it does not replace release ownership or gates.
- Do not edit status by hand. Regenerate it with
  `GH_TOKEN=… ./scripts/gen-org-release-inventory.py`.
- Use `--check` only against a fixed `--repos-json` fixture. Live org state
  can change independently of a pull request.

## Tracked adoption gaps

- [finupdate#141](https://github.com/tuna-os/finupdate/issues/141) — first versioned release
- [iso-builder#214](https://github.com/tuna-os/iso-builder/issues/214) — release pipeline for the native writer
- [bootc-installer-asahi#77](https://github.com/tuna-os/bootc-installer-asahi/issues/77) — versioned, hardware-verified first release
- [`.github`#170](https://github.com/tuna-os/.github/issues/170) — shared workflow that fails closed and verifies releases

## Standard

[tunaOS#2731](https://github.com/tuna-os/tunaOS/issues/2731) defines the
organization-wide version identifiers, release gates, immutable references,
support, and EOL contract. Operating-system images retain the separate
[date-based image policy](../VERSIONING.md).
