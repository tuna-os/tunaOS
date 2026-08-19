# Edition → variant-page checklist

Cross-references every published `variant × desktop` edition from the
[tuna-os/tunaos-packages#133](https://github.com/tuna-os/tunaos-packages/issues/133)
desktop-parity audit against:

* the variant pages served at [tunaos.org](https://tunaos.org) — source
  [`tuna-os/docs`](https://github.com/tuna-os/docs) `src/data/variants.ts` +
  `src/pages/<variant>.tsx`, and
* the download links on [`tunaos.org/download`](https://tunaos.org/download) —
  source [`tuna-os/docs` `static/iso-index.json`](https://github.com/tuna-os/docs/blob/main/static/iso-index.json)
  (generated from the `download.tunaos.org` R2 bucket).

This is the bounded documentation-parity audit requested in
[tuna-os/tunaos#1308](https://github.com/tuna-os/tunaos/issues/1308) (context:
[tuna-os/tunaos#1294](https://github.com/tuna-os/tunaos/issues/1294)).

## Sources of truth

| # | Source | What it provides |
|---|--------|------------------|
| 1 | [tunaos-packages#133](https://github.com/tuna-os/tunaos-packages/issues/133) | Size matrix of every published edition (GHCR, amd64, 2026-07-30) and the suspect flags |
| 2 | [tunaos-packages#132](https://github.com/tuna-os/tunaos-packages/issues/132) | GNOME-only precursor (`:base` vs `:gnome` deltas) |
| 3 | [tuna-os/docs `src/data/variants.ts`](https://github.com/tuna-os/docs/blob/main/src/data/variants.ts) | The tunaos.org variant catalog — which desktops each variant page lists |
| 4 | [tuna-os/docs `src/pages/`](https://github.com/tuna-os/docs/tree/main/src/pages) | The per-variant landing pages (`/yellowfin`, `/bonito`, …) |
| 5 | [`.github/build-config.yml`](../.github/build-config.yml) | Current build matrix (`build_image` / `build_iso` per flavor) |
| 6 | [tuna-os/docs `static/iso-index.json`](https://github.com/tuna-os/docs/blob/main/static/iso-index.json) | The download page's live ISO links (`download.tunaos.org`) |

## The audit's edition count (37 vs 40)

The #133 title reads "24 of 37 published editions". Its size matrix enumerates
**40 published desktop images** (the `–` cells are not published), of which
**24 are flagged suspect** (bold in the matrix). The matrix is the audit's
primary data, so this checklist follows it and enumerates all 40.

The 3-image difference between the headline "37" and the matrix's 40 coincides
with the three EL10 XFCE images (`albacore:xfce`, `yellowfin:xfce`,
`skipjack:xfce`): they were measured on GHCR and flagged thin, and they are the
three editions the tunaos.org catalog does **not** list — `variants.ts` filters
XFCE out of the EL10 trio pending
[tunaos-packages#65](https://github.com/tuna-os/tunaos-packages/issues/65).
They are marked in the checklist below.

## Audit matrix (source of truth)

Reproduced verbatim from tunaos-packages#133 (GB, summed compressed layer
sizes, amd64, 2026-07-30). **Bold** = desktop adds < 0.45 GB over its own
`:base` (the audit's suspect flag).

| variant | base | gnome | kde | cosmic | niri | xfce |
|---|---|---|---|---|---|---|
| yellowfin | 2.78 | 3.77 | 4.55 | 3.19 | 3.15 | **2.86** |
| bonito | 3.21 | 3.91 | 4.76 | 3.96 | **3.58** | 3.96 |
| sailfin | 1.48 | **1.64** | **1.92** | – | **1.49** | **1.58** |
| flounder | 1.11 | **1.44** | **1.28** | **0.73** | **0.71** | **1.04** |
| grouper | 1.84 | **2.16** | **2.06** | – | **2.10** | **1.85** |
| marlin | 1.49 | 2.17 | **1.51** | **1.51** | **1.51** | **1.51** |
| skipjack | 2.58 | 3.57 | 4.36 | 3.29 | **2.95** | **2.67** |
| albacore | 2.58 | 3.58 | 4.33 | **3.00** | **2.95** | **2.67** |
| guppy | 3.14 | 4.90 | 5.61 | – | – | – |

## Variant pages

Every variant in the audit has a tunaos.org landing page. The "desktops
listed" column is what `variants.ts` exposes on that page — the column where
the gaps below show up.

| Variant | tunaos.org variant page | Desktops listed on page | Audit desktops published |
|---|---|---|---|
| albacore | [/albacore](https://tunaos.org/albacore) | gnome, kde, cosmic, niri, pantheon | gnome, kde, cosmic, niri, xfce |
| yellowfin | [/yellowfin](https://tunaos.org/yellowfin) | gnome, kde, cosmic, niri, pantheon | gnome, kde, cosmic, niri, xfce |
| skipjack | [/skipjack](https://tunaos.org/skipjack) | gnome, kde, cosmic, niri, pantheon | gnome, kde, cosmic, niri, xfce |
| bonito | [/bonito](https://tunaos.org/bonito) | gnome, kde, cosmic, niri, xfce, pantheon | gnome, kde, cosmic, niri, xfce |
| sailfin | [/sailfin](https://tunaos.org/sailfin) | gnome, kde, niri, xfce | gnome, kde, niri, xfce |
| flounder | [/flounder](https://tunaos.org/flounder) | gnome, kde, cosmic, niri, xfce, pantheon | gnome, kde, cosmic, niri, xfce |
| grouper | [/grouper](https://tunaos.org/grouper) | gnome, kde, niri, xfce | gnome, kde, niri, xfce |
| marlin | [/marlin](https://tunaos.org/marlin) | gnome, kde, cosmic, niri, xfce, pantheon | gnome, kde, cosmic, niri, xfce |
| guppy | [/guppy](https://tunaos.org/guppy) | gnome, kde | gnome, kde |

## Edition checklist

40 published desktop editions from the #133 matrix, checked against the
tunaos.org catalog and download page.

Legend: **Page lists desktop** — does the variant page expose that desktop
(`variants.ts`)? **Download link** — is an ISO for that desktop surfaced on
`tunaos.org/download` (`iso-index.json`)?

| Edition (`ghcr.io/tuna-os/…`) | Audit size (GB) | Audit flag | Page lists desktop? | Download link | Gap note |
|---|---|---|---|---|---|
| `yellowfin:gnome` | 3.77 | ok | ✅ | ✅ grouped default ISO | — |
| `yellowfin:kde` | 4.55 | ok | ✅ | ✅ NVIDIA flavor ISO only | — |
| `yellowfin:cosmic` | 3.19 | ok | ✅ | ✅ NVIDIA flavor ISO only | — |
| `yellowfin:niri` | 3.15 | ok | ✅ | ✅ NVIDIA flavor ISO only | — |
| `yellowfin:xfce` | 2.86 | suspect | ❌ | ✅ NVIDIA flavor ISO only | No XFCE row on `/yellowfin` — EL10 XFCE filtered pending tunaos-packages#65; image published & flagged thin in #133 |
| `bonito:gnome` | 3.91 | ok | ✅ | ✅ grouped default ISO | — |
| `bonito:kde` | 4.76 | ok | ✅ | ❌ none surfaced | no `bonito-kde` ISO in `iso-index.json` |
| `bonito:cosmic` | 3.96 | ok | ✅ | ❌ none surfaced | no `bonito-cosmic` ISO in `iso-index.json` |
| `bonito:niri` | 3.58 | suspect | ✅ | ❌ none surfaced | no `bonito-niri` ISO in `iso-index.json` |
| `bonito:xfce` | 3.96 | ok | ✅ | ❌ none surfaced | no `bonito-xfce` ISO in `iso-index.json` |
| `sailfin:gnome` | 1.64 | suspect | ✅ | ❌ none | no sailfin ISO in `iso-index.json` |
| `sailfin:kde` | 1.92 | suspect | ✅ | ❌ none | no sailfin ISO in `iso-index.json` |
| `sailfin:niri` | 1.49 | suspect | ✅ | ❌ none | no sailfin ISO in `iso-index.json` |
| `sailfin:xfce` | 1.58 | suspect | ✅ | ❌ none | no sailfin ISO in `iso-index.json` |
| `flounder:gnome` | 1.44 | suspect | ✅ | ✅ grouped default ISO | — |
| `flounder:kde` | 1.28 | suspect | ✅ | ❌ none surfaced | — |
| `flounder:cosmic` | 0.73 | suspect | ✅ (stale) | ❌ not built | Page lists COSMIC, but `build-config.yml` removed it — smaller than base, no Debian packages (#133, tunaOS#964) |
| `flounder:niri` | 0.71 | suspect | ✅ (stale) | ❌ not built | Page lists Niri, but `build-config.yml` removed it — published with no compositor (tunaOS#915) |
| `flounder:xfce` | 1.04 | suspect | ✅ | ✅ dated ISO only (`flounder-xfce`) | — |
| `grouper:gnome` | 2.16 | suspect | ✅ | ❌ none | no grouper ISO in `iso-index.json` |
| `grouper:kde` | 2.06 | suspect | ✅ | ❌ none | no grouper ISO in `iso-index.json` |
| `grouper:niri` | 2.10 | suspect | ✅ (stale) | ❌ not built | Page lists Niri, but `build-config.yml` removed it — not packaged for apt (tunaOS#915) |
| `grouper:xfce` | 1.85 | suspect | ✅ | ❌ none | no grouper ISO in `iso-index.json` |
| `marlin:gnome` | 2.17 | ok | ✅ | ✅ | — |
| `marlin:kde` | 1.51 | suspect | ✅ | ✅ | — |
| `marlin:cosmic` | 1.51 | suspect | ✅ | ❌ none surfaced | no `build_iso` for cosmic; no marlin-cosmic ISO in index |
| `marlin:niri` | 1.51 | suspect | ✅ | ❌ none surfaced | no `build_iso` for niri; no marlin-niri ISO in index |
| `marlin:xfce` | 1.51 | suspect | ✅ | ❌ none surfaced | no `build_iso` for xfce; no marlin-xfce ISO in index |
| `skipjack:gnome` | 3.57 | ok | ✅ | ✅ grouped default ISO | — |
| `skipjack:kde` | 4.36 | ok | ✅ | ❌ none surfaced | no `skipjack-kde` ISO in `iso-index.json` |
| `skipjack:cosmic` | 3.29 | ok | ✅ | ❌ none surfaced | no `skipjack-cosmic` ISO in `iso-index.json` |
| `skipjack:niri` | 2.95 | suspect | ✅ | ❌ none surfaced | no `skipjack-niri` ISO in `iso-index.json` |
| `skipjack:xfce` | 2.67 | suspect | ❌ | ❌ none surfaced | No XFCE row on `/skipjack` (EL10 XFCE filtered pending tunaos-packages#65); no `skipjack-xfce` ISO in `iso-index.json` |
| `albacore:gnome` | 3.58 | ok | ✅ | ✅ grouped default ISO | — |
| `albacore:kde` | 4.33 | ok | ✅ | ✅ NVIDIA flavor ISO only | — |
| `albacore:cosmic` | 3.00 | suspect | ✅ | ✅ NVIDIA flavor ISO only | — |
| `albacore:niri` | 2.95 | suspect | ✅ | ✅ NVIDIA flavor ISO only | — |
| `albacore:xfce` | 2.67 | suspect | ❌ | ✅ NVIDIA flavor ISO only | No XFCE row on `/albacore` — EL10 XFCE filtered pending tunaos-packages#65; image published & flagged thin in #133 |
| `guppy:gnome` | 4.90 | ok | ✅ | ❌ none | no guppy ISO in `iso-index.json` |
| `guppy:kde` | 5.61 | ok | ✅ | ❌ none | no guppy ISO in `iso-index.json` |

## Gap summary

### 1. Missing variant-page listing (published, but no desktop row on the page)

Three editions are published on GHCR and measured in #133, but their variant
page does not list the desktop:

| Edition | Why |
|---|---|
| `albacore:xfce` | EL10 XFCE filtered out of `variants.ts` pending [tunaos-packages#65](https://github.com/tuna-os/tunaos-packages/issues/65) |
| `yellowfin:xfce` | same |
| `skipjack:xfce` | same |

All three were flagged **suspect (thin)** in #133.

### 2. Stale variant-page listing (page lists an edition that is no longer built)

Three editions are still listed on their variant page but were removed from
`build-config.yml` after #133:

| Edition | Why |
|---|---|
| `flounder:cosmic` | smaller than `:base`; no Debian COSMIC packages ([tunaOS#964](https://github.com/tuna-os/tunaos/issues/964)) |
| `flounder:niri` | published with no compositor ([tunaOS#915](https://github.com/tuna-os/tunaos/issues/915)) |
| `grouper:niri` | niri not packaged for apt ([tunaOS#915](https://github.com/tuna-os/tunaos/issues/915)) |

### 3. No working download link on `/download`

Editions with no ISO surfaced in `iso-index.json` (the download page's source):

* **Whole variants with zero ISOs:** `sailfin` (gnome, kde, niri, xfce),
  `grouper` (gnome, kde, niri, xfce), `guppy` (gnome, kde) — 10 editions.
* **Long-tail desktops not surfaced:** `bonito` kde/cosmic/niri/xfce,
  `skipjack` kde/cosmic/niri/xfce, `marlin` cosmic/niri/xfce,
  `flounder` kde — 11 editions.

Several of these have `build_iso: true` in `.github/build-config.yml`, but the
community desktop ISO group is declared `publish: false` (only the default
GNOME group is published as `<variant>.iso`), and no per-desktop ISO reaches the
R2 index for them. The browser ISO builder (`iso.tunaos.org`) can still produce
on-demand ISOs from the published OCI images.

## Regenerating

The catalog and download columns above are derived from live sources, not
hand-maintained numbers:

* Variant-page listings: `tuna-os/docs` → `src/data/variants.ts`.
* Download links: `tuna-os/docs` → `static/iso-index.json` (refreshed by the
  docs repo's `update-iso-index` workflow).
* Build reality: `.github/build-config.yml` (`build_image` / `build_iso`).

Re-check those three when a cell here looks stale.
