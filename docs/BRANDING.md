# Branding

TunaOS ships someone else's operating system under our name. This page says how
we make that true. It covers what "branded" means, which parts a variant gets
for free, and which parts each desktop owns.

It exists because `marlin:gnome` looked unbranded, and every check we had still
passed.

## The three layers

The brand lands partly, and the part that lands fools a spot check. We wrote
`verify-branding.sh` after `grouper:gnome` shipped with `HOME_URL` correct and
`LOGO=ubuntu-logo`. Separate the layers, and a test can assert each one alone.

### 1. Identity — what the system calls itself

`/usr/lib/os-release` and `/usr/share/ublue-os/image-info.json`.
`build_scripts/90-image-info.sh` writes both, and every base runs it.

| field | value |
|---|---|
| `PRETTY_NAME`, `NAME` | the variant, never the upstream distro |
| `VERSION_CODENAME` | the variant's fish, e.g. `Makaira nigricans` |
| `LOGO` | `tunaos` |
| `HOME_URL`, `DOCUMENTATION_URL`, `SUPPORT_URL`, `BUG_REPORT_URL` | ours |
| `VARIANT`, `VARIANT_ID`, `IMAGE_ID`, `IMAGE_VERSION`, `DEFAULT_HOSTNAME` | set |

One variant's identity must never name another project. Until 2026-09-17 every
variant pointed `HOME_URL` at `projectbluefin.io`, and the contract did not look
at that field.

### 2. Assets — the files branding needs

`system_files/` carries them, and every Containerfile copies it, so every
variant gets these whether or not anything uses them:

| asset | path |
|---|---|
| logo | `/usr/share/pixmaps/tunaos.svg` |
| wallpaper | `/usr/share/backgrounds/tunaos/tunaos-default.png` |
| boot splash | `/usr/share/plymouth/themes/shark/`, via `default.plymouth` |

### 3. Application — what a user sees

**This is the layer that was missing, and the reason for this page.** A file
under `/usr/share/backgrounds` changes nothing on its own. Something has to tell
the session to use it, and that something differs per desktop.

| desktop | mechanism | state |
|---|---|---|
| GNOME | dconf keyfiles in `/etc/dconf/db/local.d` and `gdm.d` | added 2026-09-17 |
| KDE | `LookAndFeelPackage=org.tunaos.desktop` in `kdeglobals` | done |
| niri | greeter QML, compositor config, a wallpaper daemon | greeter only |
| COSMIC | `experiences/cosmic/files/` | **not done** — the directory holds a README |
| XFCE | `experiences/xfce/files/` | **not done** — the directory holds a README |

## The rule

**Assert the applied state, not the file.** A check that asks whether the
wallpaper exists passes on an image where nobody set it. That is how
`marlin:gnome` stayed green. `verify-branding-gnome.sh` asks whether a dconf
keyfile names the wallpaper, and whether `dconf` compiled the database that holds it.

## Where the code lives

| file | job |
|---|---|
| `build_scripts/90-image-info.sh` | writes layer 1 |
| `system_files/usr/share/…` | carries layer 2 |
| `build_scripts/desktop/gnome-set-branding.sh` | applies layer 3 for GNOME |
| `build_scripts/desktop/kde-set-look-and-feel.sh` | applies layer 3 for KDE |
| `build_scripts/checks/verify-branding.sh` | asserts layers 1 and 2, every desktop |
| `build_scripts/checks/verify-branding-gnome.sh` | asserts layer 3 for GNOME |
| `build_scripts/checks/verify-branding-kde.sh` | asserts layer 3 for KDE |
| `build_scripts/checks/verify-branding-niri.sh` | asserts layer 3 for niri |
| `tests/bats/test_gnome_branding.bats` | covers the GNOME writer, its contract and both call sites |

## Adding a desktop

Two call sites run the desktop install, and your new script must run from both.
`install-desktop.sh` covers the dnf, zypper, pacman and portage bases;
`configure-desktop-runtime.sh` covers Ubuntu and Debian. KDE's look-and-feel fix
lived in one of them for a while, and the other half of the matrix shipped
unbranded.

1. Apply it in `build_scripts/desktop/<desktop>-set-branding.sh`. Make it
   idempotent. Let it take explicit paths, so a test can run it.
2. Assert it in `build_scripts/checks/verify-branding-<desktop>.sh`. Assert what
   the session reads, not what the image contains.
3. Call both from **both** install paths. Add the checker to `BRANDING_EXTRA`,
   so the runtime contract unit runs it under the boot gate.
4. Add a bats case over a temporary tree. Add a test that both call sites
   invoke it.

## What is still open

COSMIC and XFCE apply nothing. Their `experiences/` directories contain a README
and copy that README into `/etc/skel`, so a new user gets a README in
`~/.config` and stock artwork on screen. niri draws no wallpaper at all, which
`verify-branding-niri.sh` documents against a measured image.
