# Branding

TunaOS ships someone else's operating system under our name. This page says how
we make that true. It covers what "branded" means, which parts a variant gets
for free, and which parts each desktop owns.

It exists because `marlin:gnome` looked unbranded, and every check we had still
passed.

## Fork branding

A fork sets its own name, URLs, codenames, accents and splash theme in
`tunaos.toml`, the same file and compiler TunaOS uses. Its wallpapers are files
named by the convention in [Wallpapers](#wallpapers). The earlier fork preview in YAML
and its single shared-wallpaper override no longer exist. Convert an old
file with `python3 scripts/config.py migrate-fork-config --legacy OLD.yaml`
([migration](PRIMARY-CONFIG-MIGRATION.md#migrating-a-legacy-fork-config)).
Tests of source files do not prove what an image displays.

## The three layers

The brand lands partly, and the part that lands fools a spot check. We wrote
`verify-branding.sh` after `grouper:gnome` shipped with `HOME_URL` correct and
`LOGO=ubuntu-logo`. Separate the layers, and a test can assert each one alone.

### 1. Identity — what the system calls itself

`/usr/lib/os-release` and `/usr/share/ublue-os/image-info.json`.
`build_scripts/90-image-info.sh` writes both, and every base runs it. The name,
URLs, CPE and codenames come from `[project]`, `[defaults.branding]` and each
variant's `codename` in `tunaos.toml`, through the generated
`build_scripts/lib/identity.env`. `verify-branding.sh` checks against the same
file, so a fork's values pass the contract.

| field | value |
|---|---|
| `PRETTY_NAME`, `NAME` | the variant, never the upstream distro |
| `VERSION_CODENAME` | the variant's `codename`, e.g. `Makaira nigricans` |
| `LOGO` | `tunaos` |
| `HOME_URL`, `DOCUMENTATION_URL`, `SUPPORT_URL`, `BUG_REPORT_URL` | `[defaults.branding]` |
| `CPE_NAME` | `cpe:/o:<cpe_vendor>:<image name>-<project id>`; the image name is the publish name (`bonito` for `bonito-rawhide`) |
| `VARIANT`, `VARIANT_ID`, `IMAGE_ID`, `IMAGE_VERSION`, `DEFAULT_HOSTNAME` | set |

Beyond os-release, the same adapter fills the other places an image names its
project, so a fork edits `tunaos.toml` and nothing else:

| where | value | from |
|---|---|---|
| installer `recipe.json` `imgref`, `local_imgref` | `<registry>/<namespace>/<project id>:latest` | `[build.publish]` or the repository owner, `[project] id` |
| installer `images.json` (the image list) | one leaf: the variant name and the `recipe.json` `imgref` | the same ref; `checks/verify-installer-catalog.sh` rejects another registry or namespace |
| OCI labels `url`, `documentation`, artifacthub keyword; final-image `title` | `website`, `<docs_url>/intro`, project id; `<name> <image> (<flavor>)` | `[project]` |
| SBOM `Organization` and namespace | `name`, `<website>/spdxdocs` | `[project]` |
| release notes title, project name, docs URL, signing identity | `name`, `docs_url`, the repository | `[project]`, `github.repository` |
| KDE theme and wallpaper metadata (`Description`, `Authors`, `Website`), live-ready unit | `@TUNAOS_*@` tokens in `system_files`, filled by `90-image-info.sh` | `[project]`, `[defaults.branding]` |
| live-ISO launchers, polkit action text, ISO media names | `Install <name>`, `<name> <Variant>`, `<id>-<variant>-<flavor>` | `[project]` |
| usage-report endpoint and page; Flatpak remote | `countme_endpoint`, `countme_metrics_url`; `[flatpak_preinstall] remote_url` | `tunaos.toml` |
| Flatpak remotes on the image | `tuna-os` and `flathub` only; `flatpak-add-fedora-repos.service` is masked | `[flatpak_preinstall] remote_url`; `checks/verify-flatpak-remotes.sh` writes `/usr/share/tunaos/flatpak-remotes.expected` |

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
| GNOME | dconf profiles and compiled `local`/`gdm` databases; canonical wordmark and wallpaper byte checks | configuration contract; rendered qualification separate |
| Tuna | the same GDM wordmark setter; packaged GNOME Shell CSS plus a variant-accent resource overlay scoped to `org.gnome.Shell@gdm.service` | configuration contract; rendered qualification separate |
| KDE | `LookAndFeelPackage=org.tunaos.desktop` in `kdeglobals` | done |
| niri | the DMS shell sets the wallpaper at the first login | done |
| DMS greeter | `dms-greeter-set-branding.sh` gives the greeter cache a `session.json` that names the wallpaper; the fallback mark is the variant logo | configuration contract (`verify-dms-greeter.sh`) |
| COSMIC | `cosmic-set-branding.sh` writes the cosmic-bg default | done |
| XFCE | an autostart entry sets the wallpaper at the first login | done |
| Pantheon | `zzzz-tunaos.gschema.override` | done |
| SDDM / PlasmaLogin | `kde-set-look-and-feel.sh` selects installed Breeze and writes `theme.conf.user`; stock fallback is explicitly unsupported for branded-greeter | configuration contract; rendered qualification separate |
| LightDM, gtkgreet | the wallpaper of the variant | done |

## The variant is the brand

The user sees the variant name: Marlin, Sailfin, Albacore. The name
"TunaOS" shows in two places only:

- the About page of the desktop (KDE shows "part of TunaOS")
- fastfetch

Do not add "TunaOS" to a login screen, a splash, a wallpaper or the installer.

### Live media

A live ISO has three names. Each one follows a different rule.

| name | value | why |
|---|---|---|
| boot menu entry | `<PRETTY_NAME> (live)`, e.g. `Yellowfin (live)`; a medium with several flavors adds the flavor, `Yellowfin GNOME (live)` | the user boots the variant, and the installed boot entry has the same name |
| volume label | `TUNAOS` (ISO Builder) or `<id>-<variant>-<flavor>` | the label is on the kernel command line as `root=tbox:CDLABEL=…`, so it stays plain ASCII |
| download and file name | `<name> <Variant>`, `<variant>-<flavor>-<version>-<arch>.iso` | download pages list every variant, so the project name groups them |

The boot menu showed `TunaOS browser-live (live)` until 2026-11 (strict run
log `strict-plain-live-serial.log:7`, yellowfin:xfce). That name had both the
project name and an internal id. tacklebox now reads the menu title from the
image's os-release (`purefs.LiveMenuTitle`).
`scripts/build-iso-tacklebox.sh` and `scripts/build-iso-group.sh` set the
same title through `tunaos_live_menu_title`.

## Each variant has its own look

A variant is TunaOS first. It also shows the distro it is built on.
Each variant's `branding` in `tunaos.toml` gives it an accent colour, which
`scripts/config.py generate-variant-identity` writes to
`build_scripts/lib/variant-identity.tsv` for the build and the art generators.
The colour comes from that distro: Arch blue for marlin, Ubuntu orange for
grouper, openSUSE green for sailfin. The mark is the variant's Noto Emoji.

| surface | what the variant gets |
|---|---|
| logo | its emoji, in `/usr/share/tunaos/logos/<variant>.svg` |
| lettermark | its emoji and name, on GDM and the Plasma splash |
| boot splash | an animation of its emoji |
| wallpaper | an anime painting of its emoji by the sea |
| GNOME, KDE | the accent colour |
| `ANSI_COLOR`, `/etc/issue`, fastfetch | the accent colour |

`90-image-info.sh` writes `/usr/share/tunaos/identity.env` from the table.
The desktop scripts read that file.

### Wallpapers

Each variant has one anime wallpaper,
`system_files/usr/share/backgrounds/tunaos/<variant>.jpg`. TunaOS ships only
these anime images as wallpapers. The
[anime wallpaper record](branding/anime-wallpapers.md) gives their source,
prompts and checksums.

`tunaos-default.jpg` is the path that each desktop config names. In the
repository, it is a copy of the albacore image. Albacore has the generic 🐟
emoji. `build_scripts/desktop/select-wallpaper.sh` copies the variant's
wallpaper over it during the build. If a known variant has no `<variant>.jpg`,
the build fails and names the missing file.

Painted art can replace the wallpaper for one desktop. Put it at
`system_files/usr/share/backgrounds/tunaos/<variant>-<desktop>.jpg`.
`select-wallpaper.sh` uses that file first. `scripts/branding/art-prompts.mjs`
prints a prompt for each variant and desktop. The prompt joins the emoji, the
colour of the base and the style of the desktop.

### Generated assets

These scripts make files that are in the repository. The build does not run
them. The first three read `tunaos.toml`, and
`scripts/branding/check-artwork.py` (run in CI) fails if their committed
output does not match it; `--write` regenerates them. They need the pinned
`requirements-branding.txt`.

| script | output | from |
|---|---|---|
| `scripts/branding/make-logos.py` | `/usr/share/tunaos/logos/` | each variant's `emoji` |
| `scripts/branding/make-lettermarks.py` | `/usr/share/tunaos/lettermarks/` | mark, name, `branding.accent` |
| `scripts/branding/make-fastfetch-logos.py` | `/usr/share/tunaos/fastfetch/` | name |
| `scripts/branding/make-plymouth-theme.py` | `/usr/share/plymouth/themes/<theme>/` | drawn; `branding.plymouth` picks it |

The same lettermark script also writes the project wordmark,
`lettermarks/tunaos.svg` and `tunaos-dark.svg`. It shows "TunaOS" next to the
generic 🐟 mark (`/usr/share/pixmaps/tunaos.svg`), with an albacore-blue
`#0069DA` underline. Albacore uses the same fish. The website, the ISO Builder
(`/wordmark.svg`) and other tuna-os repositories copy it from there. Images
do not use it: the build installs only `lettermarks/<variant>.svg`, and no
variant is named `tunaos`.

No script can make the drawn art from `tunaos.toml`. `scripts/config.py
check-drawn-artwork` (in `just check`) makes sure each variant has its
`<variant>.jpg` (a real JPEG) and its `branding.plymouth` theme, and that the
theme's `.plymouth` file names its own folder in `ImageDir` and `ScriptFile`.

## The rule

**Assert the applied state, not the file.** A check that asks whether the
wallpaper exists passes on an image where nobody set it. That is how
`marlin:gnome` stayed green. `verify-branding-gnome.sh` reads compiled defaults
through the installed profiles with an empty user database. The database is private.
The check uses `dconf read`, which reads the database files directly.
It does not need a session D-Bus or an installed schema.

### Greeter and wallpaper consumer contract (#4105)

`TUNAOS_VARIANT` must match the canonical variant argument, not its display name
or publish alias, such as `bonito` for `bonito-rawhide`.
The checks compare bytes with the canonical asset; declared shared artwork remains valid.

GDM/Breeze use the wide wordmark from
`/usr/share/tunaos/lettermarks/<variant>.svg`, normally through
`/usr/share/pixmaps/tunaos-lettermark.svg`.
Small icons retain the Noto Emoji mark from
`/usr/share/tunaos/logos/<variant>.svg`.

The GNOME wallpaper default must match the first available asset:
`<variant>-gnome.jpg`, `<variant>-anime.jpg`, then `<variant>.jpg`.
Both compiled background keys must select
`file:///usr/share/backgrounds/tunaos/tunaos-default.jpg`.
The check does not change user preferences or set locks.

Tuna installed the wordmark bytes before this change, but its GDM helper selected only the accent.
Tuna now uses the shared setter for the GDM wordmark/profile only.
It preserves packaged styles, the greeter-only accent scope and all user-session defaults.

KDE reports stock themes as `unsupported`, not branded.
`TUNAOS_REQUIRE_BRANDED_GREETER=1` rejects any status other than `config-verified`.

The KDE check reads `Current` and `ThemeDir` from the same files as the greeter, in the same order.
It then reads `theme.conf` and `theme.conf.user` in the theme that the greeter loads.
A key, its `=` and its value can have spaces between them.
If the variant has no canonical wallpaper, the status is `blocked` with reason `canonical-wallpaper-missing`.
The exact output contract is:

```text
TUNAOS_BRANDING_GNOME_OK variant=<canonical> scope=compiled-defaults rendered=not-run existing_user=not-modified wallpaper=compiled-defaults
TUNAOS_BRANDING_GNOME_OK variant=<canonical> scope=compiled-greeter rendered=not-run existing_user=not-modified wallpaper=not-run
TUNAOS_BRANDING_GNOME_FAIL variant=<canonical> failures=<n>
TUNAOS_BRANDING_GNOME_FAIL variant=<canonical> reason=early_exit rc=<n>
TUNAOS_BRANDING_KDE_GREETER variant=<canonical> status=config-verified reason=canonical-assets-selected rendered=not-run
TUNAOS_BRANDING_KDE_GREETER variant=<canonical> status=unsupported reason=stock-or-unverified-theme rendered=not-run
TUNAOS_BRANDING_KDE_GREETER variant=<canonical> status=blocked reason=<reason> rendered=not-run
TUNAOS_BRANDING_KDE_OK variant=<canonical> greeter=<status> scope=configuration rendered=not-run
TUNAOS_BRANDING_KDE_FAIL variant=<canonical> failures=<n>
TUNAOS_BRANDING_KDE_FAIL variant=<canonical> reason=early_exit rc=<n>
```

Tuna uses `compiled-greeter`; it does not qualify session wallpaper.
KDE's generic `OK` does not qualify an unsupported or blocked greeter.
These contracts and their fixtures do not prove pixels, greeter UID/session or authentication.
The #4103 journey supplies that runtime evidence for one exact image.

### DMS greeter (niri)

The DMS greeter runs on the Fedora and EL10 niri images.
On Arch and openSUSE, greetd runs gtkgreet, so this section does not apply.
Niri has no apt base, but both install call sites run the setter and the check.

The greeter reads `wallpaperPath` from `session.json` in its cache dir.
The cache dir is the `--cache-dir` value in the greetd command, normally `/var/cache/dms-greeter`.
With no wallpaper, the greeter draws DankBackdrop: two grey bands and the DMS mascot.
The mascot is DMS's own `assets/danklogonormal.svg`.
It is not from os-release or the icon theme.

Zirconium's `99-dms-greeter.conf` linked `session.json` into `/usr/share/zirconium/zdots`.
We ship that directory empty, so the link went nowhere.
Every first boot of bonito:niri showed the mascot (strict run 44851254596).

`dms-greeter-set-branding.sh` runs after the desktop install. It does three things:

- It writes `/usr/share/tunaos/dms-greeter/session.json`, which names `tunaos-default.jpg`.
- It writes a tmpfiles `L` line that links `<cache dir>/session.json` to that file at boot.
  `L` does not replace a file that `dms greeter sync` wrote.
- It links the greeter's `danklogonormal.svg` to `/usr/share/pixmaps/tunaos.svg`.

With a wallpaper, the greeter draws no logo.
The wallpaper shows the variant's emoji.
The mark appears only if the wallpaper does not load.

`verify-dms-greeter.sh` reads what the greeter reads, in the same order.
At build time `/var` is empty, so the check finds the tmpfiles line that creates `session.json`.
Like systemd-tmpfiles, it takes the first file by name, so `99-…` comes before `tunaos-…`.
At `--runtime` it reads the file in the cache dir.
It fails if `settings.json` sets `greeterWallpaperPath` or `lockScreenWallpaperPath` to a different image.
The output is one of these lines:

```text
TUNAOS_DMS_GREETER_OK variant=<canonical> wallpaper=/usr/share/backgrounds/tunaos/tunaos-default.jpg logo=/usr/share/pixmaps/tunaos.svg session=<source> mode=<build|runtime>
TUNAOS_DMS_GREETER_SKIP variant=<canonical> reason=greeter-not-dms greeter=<argv0> mode=<build|runtime>
TUNAOS_DMS_GREETER_FAIL variant=<canonical> failures=<n> mode=<build|runtime>
```

The image installs the check as `/usr/libexec/tunaos/verify-dms-greeter`.
The desktop contract unit runs it with `--runtime`.


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
| `build_scripts/desktop/dms-greeter-set-branding.sh` | applies layer 3 for the DMS greeter |
| `build_scripts/checks/verify-dms-greeter.sh` | asserts layer 3 for the DMS greeter |
| `build_scripts/checks/verify-plymouth-initramfs.sh` | asserts the variant's own splash is in the initramfs (EL10, after dracut in `26-packages-post.sh`) |
| `tests/bats/test_gnome_branding.bats` | covers the GNOME writer, its contract and both call sites |
| `tests/bats/test_dms_greeter_branding.bats` | covers the DMS greeter writer, its contract and both call sites |

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

- Plymouth: `verify-plymouth-initramfs.sh` runs only on the EL10 path. The
  Arch, Debian, Gentoo, Ubuntu and openSUSE bases select the theme but do not
  yet check which theme dracut put in the initramfs. No boot gate renders the
  splash either: e2e boots with `plymouth.enable=0`.
- GDM keeps the styles from its package. Tuna adds an accent for its variant.
  These checks do not prove what the greeter draws.
- cosmic-greeter and the Pantheon greeter use the wallpaper default. Nobody
  has checked them on a built image.
- COSMIC, XFCE, Pantheon and the login screens have no
  `verify-branding-<desktop>.sh`.
