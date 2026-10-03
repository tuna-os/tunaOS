# Design contributions: wallpapers and variant artwork

TunaOS ships 18 variants, each named for a fish species, but today every
variant uses the same single default wallpaper:
`system_files/usr/share/backgrounds/tunaos/tunaos-default.jpg` (mirrored for
KDE at `system_files/usr/share/wallpapers/TunaOS/contents/images/tunaos-default.jpg`).
See [`docs/BRANDING.md`](BRANDING.md) for how that one asset gets applied
across desktops (GNOME dconf keyfiles, KDE `LookAndFeelPackage`, the niri DMS
shell, COSMIC, XFCE, Pantheon, SDDM, LightDM).

This contribution path needs no code experience: a wallpaper, a variant
mascot illustration, or a themed icon set. If you can use image editing
software and want to contribute to open source, this is a real gap you can
help close.

## What's needed

Submit per-variant wallpapers for any of the fish below. You need not cover
every variant — even one accepted wallpaper contributes meaningfully.

| Variant | Base OS | Fish |
|---|---|---|
| Yellowfin | AlmaLinux Kitten 10 | Yellowfin tuna |
| Albacore | AlmaLinux 10 (RHEL 10) | Albacore tuna |
| Skipjack | CentOS Stream 10 | Skipjack tuna |
| Bonito | Fedora 44 | Bonito |
| Hummingbird | Fedora Hummingbird (experimental) | — |
| Wahoo | Fedora ELN / EL11 preview | Wahoo |
| Redfin | RHEL 10 | Redfin |
| Grouper | Ubuntu 26.04 | Grouper |
| Gurnard | Ubuntu 24.04 | Gurnard |
| Marlin | Arch Linux | Marlin |
| Flounder | Debian 13 | Flounder |
| Flounder Sid | Debian Sid | Flounder |
| Bonito Rawhide | Fedora Rawhide | Bonito |
| Sailfin | openSUSE Tumbleweed | Sailfin |
| Guppy | Gentoo Linux | Guppy |
| Tromsø | freedesktop-sdk / KDE | — |
| XFCE Linux | freedesktop-sdk / XFCE | — |

(Table current as of this PR; check [`README.md`](../README.md)'s variant
table for the live list before starting, since variants are added and
retired.)

## Design brief

For each wallpaper submission, include:

- **Variant name** and which fish (or theme) it represents
- **Resolution**: minimum 3840x2160 (4K), landscape orientation
- **Format**: PNG or high-quality JPEG
- **Theme direction**: a sentence or two on the visual concept (e.g. "deep
  ocean gradient with a stylized yellowfin tuna silhouette")
- **Color palette**: 3-5 representative colors (hex codes are helpful but not
  required)

No mandated style exists — abstract, illustrated, photographic, and
gradient-based wallpapers all work well. Keep in mind the wallpaper must
work behind desktop icons and a top bar or panel, so avoid busy detail in
the corners and top edge.

## Submission guidelines

1. **License**: submissions must be CC0 (public domain dedication) or an
   equivalent permissive license compatible with the project's Apache 2.0
   code license. Do not submit AI-generated images if the generating
   service's terms restrict commercial use or redistribution — check before
   submitting.
2. **Attribution**: optional. If you want credit, include your name or handle
   in the PR description; we will add it to a contributors list.
3. **Where to submit**: open a PR adding your image under
   `docs/design/wallpapers/<variant>/` (create the directory if needed)
   along with a short `SOURCE.md` noting the license and your attribution
   preference. A maintainer wires accepted wallpapers into
   `system_files/usr/share/backgrounds/tunaos/` and the per-desktop
   mechanisms in `BRANDING.md` — you need not modify build scripts or
   Containerfiles.
4. **Review**: since this changes what every user of a variant sees by
   default, wallpaper submissions get a visual review pass in addition to
   the usual PR review. Expect to iterate on crop, contrast, or file size.

## Questions

Open a discussion or ask on [Matrix](https://matrix.to/#/%23tunaos:reilly.asia)
before investing significant time, especially if you're unsure whether a
concept fits. See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the general
contribution workflow.
