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
| terminal login banner (ublue umotd / uwelcome) links and commands | `BUG_REPORT_URL`, `DOCUMENTATION_URL`; no Bluefin recipe, no upstream tips (`tunaos-login-banner.sh`) | `[defaults.branding]` |

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
| COSMIC | `cosmic-set-branding.sh` writes the cosmic-bg default for `com.system76.CosmicBackground` and its `.Dark` and `.Light` ids | configuration contract (`verify-desktop-wallpaper.sh`); `verify-branding-cosmic.sh` at runtime |
| XFCE | `xfce-set-branding.sh` links xfdesktop's compiled `DEFAULT_BACKDROP` to the wallpaper, so every monitor uses it | configuration contract (`verify-desktop-wallpaper.sh`); `verify-branding-xfce.sh` at runtime |
| Pantheon | `zzzz-tunaos.gschema.override`, with a `:Pantheon` section, read with `XDG_CURRENT_DESKTOP=Pantheon` | configuration contract (`verify-desktop-wallpaper.sh`); `verify-branding-pantheon.sh` at runtime |
| SDDM / PlasmaLogin | `kde-set-look-and-feel.sh` selects installed Breeze and writes `theme.conf.user`; stock fallback is explicitly unsupported for branded-greeter | configuration contract; rendered qualification separate |
| LightDM GTK greeter | `90-tunaos.conf`; `xfce-set-branding.sh` rewrites each `background=` the greeter merges, because `/etc/lightdm/lightdm-gtk-greeter.conf` is read last | configuration contract (`verify-desktop-wallpaper.sh`) |
| gtkgreet | `greetd-gtkgreet.sh` writes a stylesheet with the wallpaper | configuration contract (`verify-desktop-wallpaper.sh`) |
| io.elementary.greeter | `pantheon-set-branding.sh` links `/usr/share/backgrounds/elementaryos-default`, its fixed fallback, to the wallpaper | configuration contract (`verify-desktop-wallpaper.sh`) |
| GDM on XFCE | `xfce-set-branding.sh` runs the GDM-only lettermark setter that Tuna uses | configuration contract (`verify-desktop-wallpaper.sh`) |
| cosmic-greeter | none; before the first login it draws an image compiled into the binary | open |

### COSMIC, XFCE and Pantheon

Each desktop has a `<desktop>-set-branding.sh`. Both install call sites run it,
then run `verify-desktop-wallpaper.sh <desktop>`. The check stops the build when
a default does not resolve to `tunaos-default.jpg`. It reads the consumer, not
our source file:

| desktop | what the check reads |
|---|---|
| COSMIC | the first `cosmic/<id>/v1/all` in the data dirs for each of the three ids, and any `output.*` entry |
| XFCE | the `DEFAULT_BACKDROP` string in the xfdesktop binary, then the link at that path; the system xfconf XML |
| Pantheon | `XDG_CURRENT_DESKTOP=Pantheon GSETTINGS_BACKEND=memory gsettings get org.gnome.desktop.background picture-uri`, and `picture-uri-dark` |
| greeter | the active display manager's greeter: the merged LightDM GTK greeter config, the gtkgreet stylesheet, the elementary fallback file, or the GDM logo |

We measured these defects in built images before the fix:

- xfdesktop has no wildcard monitor key. A monitor without a key draws
  `DEFAULT_BACKDROP`, a path that each distro compiles in: `xfce-x.svg`
  upstream, `default.jxl` on Fedora. A first-login script ran after
  `sleep 3` and set only the monitors it could list. On Wayland it listed none.
- elementary's override has an `[org.gnome.desktop.background:Pantheon]`
  section. A per-desktop section wins over a plain one in any file. On
  gurnard:pantheon the Pantheon session and greeter resolved to
  `elementaryos-default`, a file the image does not have.
- cosmic-bg since pop-os/cosmic-bg d6dcfa9 reads a `.Dark` or `.Light` id.
  Without a system default there, it draws `system76-cosmic-dark.png`.

The output of the check is one of these lines:

```text
TUNAOS_DESKTOP_WALLPAPER_OK desktop=<desktop> wallpaper=/usr/share/backgrounds/tunaos/tunaos-default.jpg greeter=<greeter> greeter_status=<checked|open> mode=build
TUNAOS_DESKTOP_WALLPAPER_FAIL desktop=<desktop> greeter=<greeter> failures=<n> mode=build
```

The image installs it as `/usr/libexec/tunaos/verify-desktop-wallpaper`.

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

### fastfetch

`90-image-info.sh` writes `/etc/xdg/fastfetch/config.jsonc`. Plain `fastfetch`
finds it by itself, after `~/.config/fastfetch`. So a user's config wins.

projectbluefin/common aliases `fastfetch` to `ublue-fastfetch`. That helper
runs Bluefin's config with `--config`. `90-image-info.sh` deletes the aliases
for sh and fish, and the helper. No TunaOS alias names `fastfetch`, because
`--config` would hide a user's config. `neofetch` runs plain `fastfetch`.

`verify-fastfetch.sh` runs `fastfetch --pipe -l none` in interactive bash, zsh
and fish, login and non-login, from a copy of `/etc/skel`. It stops the build
unless the output names `PRETTY_NAME` and "part of TunaOS". It also fails when
the output names an upstream desktop project, or when a user config does not
win:

```text
TUNAOS_FASTFETCH_OK shells=<list> system="<the system line>"
TUNAOS_FASTFETCH_OK status=not-installed
TUNAOS_FASTFETCH_FAIL failures=<n> shells=<list>
```

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
### GNOME Initial Setup (#4408)

GDM starts Initial Setup with `DCONF_PROFILE=gnome-initial-setup`. It does not
use the `gdm` or `user` profile. The packaged profile names no system database.
So the schema default colours the Next button: slate on Fedora bases. Ubuntu's
libadwaita turns slate into the olive Yaru "sage".

`gnome-set-branding.sh` writes `/etc/dconf/profile/gnome-initial-setup`. That
file is the packaged profile plus `system-db:gnome-initial-setup`. The new
database holds only the variant's `accent-color`. This applies on every GNOME
and Tuna image that ships Initial Setup.

Ubuntu's build adds pages that show or sell Ubuntu. The writer skips them in
`/etc/gnome-initial-setup/vendor.conf`, because Initial Setup ignores the
`/usr/share` file when the `/etc` file exists:

| page id | what it shows |
|---|---|
| `ubuntu_pro` | Ubuntu Pro offer and attach |
| `ubuntu_insights` | "Help Improve Ubuntu" telemetry |
| `welcome` | the Ubuntu mascot and an ubuntu.com release-notes link |
| `appearance` | the Yaru accent picker |
| `apps` | a button that opens App Center |

The writer finds these pages by their ids in the binary, so Stingray gets the
same skips. `verify-gnome-initial-setup.sh` stops the build when the profile
reads another accent, or when `skip=` lacks an Ubuntu page:

```text
TUNAOS_INITIAL_SETUP_OK variant=<canonical> accent='<gnome_accent>' ubuntu_pages=skipped|absent
TUNAOS_INITIAL_SETUP_OK variant=<canonical> status=not-installed
TUNAOS_INITIAL_SETUP_FAIL variant=<canonical> failures=<n>
```


## The running system

The build-time checks prove what the image tree contains. Some surfaces
exist only on a booted system: firmware boot entries, the hostname, the
flatpak remotes from boot units, and account settings. Each of them showed an upstream name while every build check passed.
Examples: `Boot000A "AlmaLinux Kitten"` on installed yellowfin, `fedora login:`
on bonito, and the Fedora flatpak remotes on bonito.

`tunaos-branding-contract.service` runs `/usr/libexec/tunaos/verify-branding
--runtime` on every boot of every image, base flavors included.
`install-branding-contract.sh` installs it from `90-image-info.sh`, the one
script every base runs; the two desktop install paths add a drop-in naming the
desktop. The unit has no leading `-`: a failure fails the unit. It prints

```text
TUNAOS_BRANDING_REPORT {"schema":1,"variant":…,"desktop":…,"result":"ok|fail","failed":[…],"checks":[{"id":…,"status":"pass|fail|skip","detail":…}]}
TUNAOS_BRANDING_OK variant=<v> desktop=<d> checks=<n> skipped=<k>
TUNAOS_BRANDING_FAIL variant=<v> desktop=<d> failed=<id,id,…>
```

The verdict line is enough to act on; the JSON is the evidence. The check ids:

| id | asserts |
|---|---|
| `image` | layers 1 and 2, the build-time checks, on the running root |
| `os-release.agree` | `/etc/os-release` and `/usr/lib/os-release` agree on every user-visible key |
| `os-release.name` | `NAME` and `PRETTY_NAME` are the variant (`image-name` in image-info.json, capitalised) |
| `os-release.denylist` | no upstream name in `NAME`, `PRETTY_NAME`, `VARIANT`, `VARIANT_ID`, `VERSION_CODENAME`, `DEFAULT_HOSTNAME`, `LOGO` or the URLs. `ID`, `ID_LIKE` and `VERSION_ID` name the base on purpose. |
| `hostname` | `DEFAULT_HOSTNAME` or the installer-set `/etc/hostname`, never an upstream name or `localhost` |
| `boot.bls` | every boot loader entry title starts with `PRETTY_NAME` |
| `boot.efi` | no firmware `Boot####` label names upstream (efibootmgr, else efivarfs) |
| `initramfs.plymouth` | the booted initramfs holds `themes/<branding.plymouth>/`, on every base family |
| `flatpak.remotes` | system remotes, disabled ones included, equal `/usr/share/tunaos/flatpak-remotes.expected` |
| `installer.catalog` | every image in `/etc/bootc-installer/images.json` is under this project's namespace |
| `fastfetch` | `fastfetch --pipe -l none`, as a fresh user, names the variant |
| `issue` | `/etc/issue` names the variant |
| `desktop.<d>` | the per-desktop checker: applied wallpaper and greeter configuration |
| `desktop.<d>.user` | each account's applied look, read back from its own settings |
| `desktop.<d>.initial-setup` | GNOME and Tuna: `verify-gnome-initial-setup` (Initial Setup accent, no Ubuntu pages, tunaOS#4408) |
| `desktop.niri.greeter` | niri: `verify-dms-greeter` (the DMS greeter's wallpaper and mark) |

The check finds each upstream name as a whole word. `BRANDING_DENYLIST` in
`verify-branding-runtime.sh` holds the list. Only the attribution "built on
<base>" can name the base (see
[Each variant has its own look](#each-variant-has-its-own-look)).

An account's wallpaper fails when it is a system file that is not the
variant's. TunaOS ships only the variant's wallpaper, so any other system path
is an upstream leftover. A picture of the user's own passes.

`scripts/corral-boot-gate.sh` waits `BRANDING_GRACE` seconds for the verdict
after its ready marker. It writes `branding-report.json` and
`branding-verdict.txt`. With `BRANDING_GATE=report`, the Gate keeps the verdict
as evidence only. With `block`, a FAIL or a missing verdict fails the Gate. The
Gate job records the verdict as a step name,
`branding: status=<ok|fail|absent> failed=<ids>`.
`scripts/gen-matrix-status.py` reads that step and gives each cell a score.

## Where the code lives

| file | job |
|---|---|
| `build_scripts/90-image-info.sh` | writes layer 1 |
| `system_files/usr/share/…` | carries layer 2 |
| `build_scripts/desktop/gnome-set-branding.sh` | applies layer 3 for GNOME |
| `build_scripts/desktop/kde-set-look-and-feel.sh` | applies layer 3 for KDE |
| `build_scripts/desktop/{cosmic,xfce,pantheon}-set-branding.sh` | apply layer 3 for COSMIC, XFCE, Pantheon and their greeters |
| `build_scripts/checks/verify-branding.sh` | asserts layers 1 and 2, every desktop |
| `build_scripts/checks/verify-branding-gnome.sh` | asserts layer 3 for GNOME |
| `build_scripts/checks/verify-branding-kde.sh` | asserts layer 3 for KDE |
| `build_scripts/checks/verify-branding-niri.sh` | asserts layer 3 for niri |
| `build_scripts/desktop/dms-greeter-set-branding.sh` | applies layer 3 for the DMS greeter |
| `build_scripts/checks/verify-dms-greeter.sh` | asserts layer 3 for the DMS greeter |
| `build_scripts/efi-boot-label.sh` | names the UEFI boot entry after the variant. It points `/etc/system-release` (bootupd's label source) at `/usr/lib/tunaos-release` and relabels the shim fallback CSVs in bootupd's payload. `90-image-info.sh` runs it (tunaOS#4864) |
| `build_scripts/checks/verify-efi-boot-label.sh` | asserts bootupd's product name and every payload CSV label equal os-release `NAME` |
| `build_scripts/checks/verify-desktop-wallpaper.sh` | asserts layer 3 for COSMIC, XFCE, Pantheon and their greeters |
| `build_scripts/checks/verify-plymouth-initramfs.sh` | asserts the variant's own splash is in each initramfs an image ships. It runs after every build-time dracut run: EL10 and Fedora, Arch, Debian, Gentoo, openSUSE, Ubuntu, and the cachyos and nvidia overlays. Images that ship no plymouth on purpose are listed in its `no_splash_reason`, with the reason (tunaOS#4866) |
| `build_scripts/checks/verify-fastfetch.sh` | asserts what plain `fastfetch` prints in each shell |
| `build_scripts/initrd-hostname.sh` | sets `DEFAULT_HOSTNAME` in os-release before each dracut run that precedes `90-image-info.sh`. dracut copies os-release into the initramfs, and PID 1 sets the hostname there first. It also installs the `99tunaos-identity` dracut module (`build_scripts/dracut/`), which sets the initramfs `NAME` and `PRETTY_NAME` that systemd's "Welcome to" line prints (tunaOS#4865) |
| `build_scripts/checks/verify-initrd-hostname.sh` | after dracut, asserts the initramfs `initrd-release` names the variant's `DEFAULT_HOSTNAME`, never an upstream name |
| `build_scripts/checks/verify-branding-cosmic.sh`, `-xfce.sh`, `-pantheon.sh` | assert layer 3 for COSMIC, XFCE and Pantheon (runtime) |
| `build_scripts/checks/verify-branding-runtime.sh` | the runtime assertions `verify-branding.sh --runtime` runs |
| `build_scripts/install-branding-contract.sh` | installs the checker and `tunaos-branding-contract.service` on every image |
| `tests/bats/test_branding_runtime.bats` | covers each runtime assertion and the new desktop checkers over fixture roots |
| `tests/bats/test_gnome_branding.bats` | covers the GNOME writer, its contract and both call sites |
| `tests/bats/test_dms_greeter_branding.bats` | covers the DMS greeter writer, its contract and both call sites |
| `tests/bats/test_desktop_wallpaper.bats` | covers the COSMIC, XFCE and Pantheon writers, their check and both call sites |
| `build_scripts/checks/verify-gnome-initial-setup.sh` | asserts the Initial Setup accent and the skipped Ubuntu pages |

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
3. Call both from **both** install paths. Add the checker to the loop in
   `install-branding-contract.sh` and to the desktop `case` in
   `verify-branding.sh`, so `tunaos-branding-contract.service` runs it on every
   boot.
4. Add a bats case over a temporary tree. Add a test that both call sites
   invoke it.

## What is still open

- Plymouth: no boot gate renders the splash. e2e boots with
  `plymouth.enable=0`. The hardware-profile overlay (X13s) rebuilds the
  initramfs without the splash check; the runtime `initramfs.plymouth` check
  still covers it on a booted system.
- hummingbird and guppy:base ship no plymouth. They are exempt in
  `verify-plymouth-initramfs.sh`. hummingbird:tuna installs plymouth after
  its initramfs is built, so its splash is the text console.
- The UEFI entry name changes only on a new install. bootupd writes the
  firmware entry in `bootupctl backend install`, not on update. An existing
  install keeps "AlmaLinux Kitten" or "Fedora". Reinstall, or rename the entry
  with `efibootmgr`.
- GDM keeps the styles from its package. Tuna adds an accent for its variant.
  These checks do not prove what the greeter draws.
- cosmic-greeter draws a background compiled into its binary
  (`src/common.rs` `fallback_background`) until the user's first login. No
  config reaches it. After that login it shows the user's cosmic-bg wallpaper.
  The check reports `greeter_status=open`. A fix needs cosmic-greeter to fall
  back to the system cosmic-bg config.
- `verify-desktop-wallpaper.sh` asserts configuration. No gate renders the
  COSMIC, XFCE or Pantheon desktop or greeter.
- Initial Setup's language page shows a logo picked by the os-release `ID`.
  Fedora bases show the Fedora logo, Debian bases the Debian swirl, and Ubuntu
  bases the Ubuntu logo. Nothing replaces it yet.
- The Initial Setup check reads configuration. A strict run must still show
  the accent on the Next button, and no "Ubuntu" in the frames.
