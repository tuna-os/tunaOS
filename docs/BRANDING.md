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
| wallpaper | `/usr/share/backgrounds/tunaos/tunaos-default.jpg` |
| boot splash | `/usr/share/plymouth/themes/tunaos/`, via `default.plymouth` |

### 3. Application — what a user sees

**This is the layer that was missing, and the reason for this page.** A file
under `/usr/share/backgrounds` changes nothing on its own. Something has to tell
the session to use it, and that something differs per desktop.

| desktop | mechanism | state |
|---|---|---|
| GNOME | dconf keyfiles in `/etc/dconf/db/local.d` and `gdm.d` | added 2026-09-17 |
| KDE | `LookAndFeelPackage=org.tunaos.desktop` in `kdeglobals` | done |
| niri | greeter QML, compositor config, a wallpaper daemon | greeter only |
| COSMIC | `cosmic-set-branding.sh` writes the cosmic-bg default | done |
| XFCE | an autostart entry sets the wallpaper at the first login | done |
| Pantheon | `zzzz-tunaos.gschema.override` | done |

## The variant is the brand

The user sees the variant name: Marlin, Sailfin, Albacore. The name
"TunaOS" shows in two places only:

- the About page of the desktop (KDE shows "part of TunaOS")
- fastfetch

Do not add "TunaOS" to a login screen, a splash, a wallpaper or the installer.

## Each variant has its own look

A variant is TunaOS first. It also shows the distro it is built on.
`build_scripts/lib/variant-identity.tsv` gives each variant an accent colour.
The colour comes from that distro: Arch blue for marlin, Ubuntu orange for
grouper, openSUSE green for sailfin. The mark is the variant's Noto Emoji.

| surface | what the variant gets |
|---|---|
| logo | its emoji, in `/usr/share/tunaos/logos/<variant>.svg` |
| lettermark | its emoji and name, on GDM and the Plasma splash |
| boot splash | an animation of its emoji |
| wallpaper | a scene around its emoji, in its accent colour |
| GNOME, KDE | the accent colour |
| `ANSI_COLOR`, `/etc/issue`, fastfetch | the accent colour |

`90-image-info.sh` writes `/usr/share/tunaos/identity.env` from the table.
The desktop scripts read that file.

### Wallpapers

`scripts/branding/render-wallpapers.mjs` draws one scene for each variant,
from `scripts/branding/wallpaper.svg.mjs`. The output is in the repository,
so the build does not draw anything. Run the script again when you change a
scene, a colour or an emoji.

The scenes are placeholders. We want art from people: see the call for
artwork in the issue tracker. Until then, art from an image model can fill a
slot.

Painted art can replace a scene for one desktop. Put it at
`system_files/usr/share/backgrounds/tunaos/<variant>-<desktop>.jpg`.
`select-wallpaper.sh` uses that file first. `scripts/branding/art-prompts.mjs`
prints a prompt for each variant and desktop. The prompt joins the emoji, the
colour of the base and the style of the desktop.

### Generated assets

These scripts make files that are in the repository. The build does not run
them.

| script | output |
|---|---|
| `scripts/branding/make-lettermarks.py` | `/usr/share/tunaos/lettermarks/` |
| `scripts/branding/make-fastfetch-logos.py` | `/usr/share/tunaos/fastfetch/` |
| `scripts/branding/make-plymouth-theme.py` | `/usr/share/plymouth/themes/<theme>/` |
| `scripts/branding/render-wallpapers.mjs` | `/usr/share/backgrounds/tunaos/` |

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

- Plymouth: `verify-branding.sh` does not check which theme dracut used.
- Login screens: SDDM, cosmic-greeter and LightDM show the upstream look.
- niri draws no wallpaper. `verify-branding-niri.sh` records this for a
  measured image.
- COSMIC, XFCE and Pantheon have no `verify-branding-<desktop>.sh`.
