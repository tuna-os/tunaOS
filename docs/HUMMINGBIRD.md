# Hummingbird — what it actually is

Written because this was got wrong repeatedly, in code comments, in
`GREEN-MASTER-PLAN.md`, and in issue triage. Hummingbird is **not** Fedora 43
and **not** EL10, and treating it as either produces conclusions that are
confidently wrong.

## The short version

**Fedora Hummingbird is a rolling-release, security-hardened, bootable-container
OS that tracks Fedora Rawhide and ships no desktop environment.**

It is the OS-scale application of Red Hat's **Project Hummingbird**, an early
access program providing a catalog of minimal, hardened, *distroless* container
images kept at near-zero CVE. Fedora Hummingbird applies that same pipeline
logic to a whole operating system.

| | |
|---|---|
| Upstream tracked | **Fedora Rawhide** — "over 95% of packages from Rawhide", upstream sources where Rawhide lacks a needed version |
| Release model | **Rolling.** Not a numbered release. There is no "Hummingbird 43". |
| Kernel | **ARK** (Always Ready Kernel) from the CKI project, following mainline Linux |
| Delivery | A **bootc / bootable OCI image**, x86_64 + aarch64; container, VM and bare metal |
| Filesystem | Read-only root; writable state confined to `/var` and `/etc`; atomic updates with rollback |
| Desktop | **None.** It ships no desktop environment, by design |
| Audience | Developers and cloud-native workloads — explicitly *not* desktop end users |
| Build | Konflux-based pipeline, isolated reproducible builds from pinned package lists, Syft + Grype scanning, per-package CVE tracking and lifecycle |

Sources: [Red Hat press release](https://www.redhat.com/en/about/press-releases/red-hat-introduces-project-hummingbird-zero-cve-strategies),
[Project Hummingbird docs](https://hummingbird-project.io/docs/using/overview/),
[Help Net Security](https://www.helpnetsecurity.com/2026/05/13/fedora-hummingbird-linux/),
[It's FOSS](https://itsfoss.com/news/fedora-hummingbird-images/).

## Why the `.fc43` version strings mislead

Packages in hummingbird's repos carry versions like `gtk4-4.22.1-2.fc43` and
`NetworkManager-1.58.0-1.hum1`. The `.fc43` dist tag is **Rawhide's current
numbering**, not evidence that this is the Fedora 43 stable release. Reading
`.fc43` as "this is Fedora 43" is the single easiest mistake to make here, and
it leads directly to expecting Fedora 43's package set to be present. It is not.

## What this means for tunaOS

tunaOS builds `hummingbird:{base,gnome,kde,niri,cosmic}` (see
`.github/build-config.yml`). Everything except `base` asks a distribution that
**deliberately ships no desktop environment** to host a full desktop, layered
from tunaOS's own package snapshot.

That is a legitimate thing to attempt — it is most of what tunaOS does for every
variant — but it is a *port*, not a *rebuild*, and the difference matters:

- There is no upstream desktop package set to fall back on. Anything the desktop
  needs either exists in tunaOS's hummingbird snapshot or does not exist at all.
- Upstream rolls. A snapshot taken once drifts away from the base image
  continuously, and the failure mode is unresolvable dependencies rather than
  missing packages (see below).
- Hardening and minimalism are the *point*. A package being absent is often a
  deliberate upstream choice, not an oversight to be reported as a bug.

### Measured state of the snapshot (2026-08-25)

Against the live index that `build_scripts/10-base-packages.sh` configures,
`https://repo.tunaos.org/hummingbird/20251124-x86_64/` — **8,100 packages**, of
which only 43 names match `gnome-*`:

| package | served? |
|---|---|
| `gtk4`, `gdk-pixbuf2`, `mutter`, `gvfs` | yes |
| `gnome-shell`, `gdm`, `nautilus` | **no** |
| `harfbuzz`, `gnome-desktop3` | **no** |
| `flatpak` | **no** |

`gtk4` is present *and* requires `harfbuzz`, which is not. That is why dnf
reports gtk4 and 17 other packages as having **broken dependencies** rather than
being unavailable — and why `--skip-unavailable` silently drops them.

The consequence, measured on `ghcr.io/tuna-os/hummingbird:gnome-testing` built
2026-08-25: **410 packages, and no GNOME.** The only `gnome`-matching names in
the image are `gnome-backgrounds`, `gnome-user-docs`,
`desktop-backgrounds-gnome`, `f45-backgrounds-gnome` and `pinentry-gnome3` —
wallpapers and documentation.

The same absence blocks the ISO: `live-iso/common/src/customize-live.sh` needs
`flatpak` to pre-install the installer, and hummingbird has no `flatpak`.

## The rolling/pinned mismatch

`build_scripts/10-base-packages.sh` pins:

```
baseurl=https://repo.tunaos.org/hummingbird/20251124-$basearch/
```

**The datestamp is a label, not a snapshot.** This prefix is where
tunaos-packages' factory *publishes into* (`r2_path:
hummingbird/20251124-$arch`), so it is a living repository whose name
happens to carry the date it was seeded. Measured 2026-08-25: the URL's name
is 274 days old while its repomd `<revision>` — the indexing epoch — is
**8 days** old. An earlier revision of this document called it "a
datestamped, immutable snapshot"; that reading produced a false STALE
verdict and bad advice ("the snapshot needs refreshing"), both since
corrected. Judge this repo by its *content* age, never its name.

The genuine mismatch is between the two halves: `.github/build-config.yml`
pins the upstream base image by digest while the package prefix grows on the
factory's own cadence. They drift apart with every upstream roll, and the
drift surfaces as dependency breakage inside the layered desktop rather than
as anything that looks like a pin problem.

`scripts/check-package-repo-pins.py` verifies the URL resolves **and** fails
datestamped prefixes whose repomd revision is older than 180 days — content
age, precisely so a living repo with a dated name is never miscalled stale.

## Its published images claim to be version 10

Measured on the 2026-08-25 build (run 32813037866). The image's own os-release:

```
NAME="Hummingbird OS"   VERSION="20251124"   VERSION_ID="20251124"
ID="hummingbird"        ID_LIKE="fedora rhel"
CPE_NAME="cpe:/a:redhat:hummingbird:1"      VENDOR_NAME="Red Hat"
```

The build ran with `MAJOR_VERSION: 10`, and `reusable-build-image.yml` stamps

```yaml
org.opencontainers.image.version=${{ env.MAJOR_VERSION }}
```

so `hummingbird:gnome-testing` is published claiming to be version **10**.

The cause is not hummingbird-specific. `reusable-build-image.yml` declares:

```yaml
major-version:
  description: "The version of CentOS to build the image on"
  default: "10"
```

and `build-variant.yml` never passes it, so **every** variant inherits `10` —
Arch, Ubuntu 26.04, Debian 13, Tumbleweed and Gentoo included. It is the same
EL10-shaped assumption this document exists to correct, just at the metadata
layer.

Note there are two different values with confusingly similar names, and only
one of them is wrong:

| | source | hummingbird's value |
|---|---|---|
| `MAJOR_VERSION` (workflow env) | `inputs.major-version`, default `"10"` | `10` — wrong |
| `MAJOR_VERSION_NUMBER` (`build_scripts/lib.sh`) | the image's own `VERSION_ID` | `20251124` — right |

So the build *scripts* already see the correct value; it is the OCI label that
lies. Anyone fixing this should know that `MAJOR_VERSION_NUMBER` feeds
`epel-release-latest-N`, `codeready-builder-for-rhel-N` and a numeric
`-ge 9` comparison, so it is not a free variable to redefine.

Not fixed here: correcting the label is a fleet-wide metadata change across
thirteen variants with downstream consumers, which wants its own change and its
own review rather than being folded into a hummingbird documentation pass.

## What actually blocks a hummingbird ISO (measured 2026-08-25)

The chain from "packages exist" to "a laptop runs Hummingbird GNOME" has six
links. Five of them were opaque this morning; they are not any more, and the
binding constraint is smaller and more specific than "the desktop is missing".

| # | link | state |
|---|---|---|
| 1 | build the desktop packages | 673 in `build-order-hummingbird-desktops.yml`, 570 served, 103 left — 53 before layer-07, 19 more in layer-07 itself (measured 2026-08-25 15:30). **Read the caveat below before using this number.** |
| 2 | publish that wave to R2 | dispatch-only; the nightly builds and caches but **never publishes** (no `rclone`/`R2_` anywhere in `package-factory.yml`) |
| 3 | image build installs them | fixed: the `IS_HUMMINGBIRD` branch of `10-base-packages.sh` never listed `flatpak` |
| 4 | Gate: `bootc install to-disk` + boot | **proven fixed** — ext4 drop-in, installs in 1m54s and boots to `graphical.target` |
| 5 | Promote publishes `hummingbird:gnome` | blocked only by the Gate's boot-verify, which needs a real desktop |
| 6 | overlay → ISO → install | blocked by `flatpak`, see below |
| 7 | the installed system works on the target laptop | **no device firmware exists anywhere** — see below (#2064) |

### Confirmed by running it: iso-e2e run 32866334376

Link 6 is no longer inferred. A gate dispatch of `iso-e2e.yml`
(`variant=hummingbird, flavors=base, source=build`) built the ISO on the runner
and reached exactly the predicted line, from inside the real base image:

```
15:35:46  + dnf5 install -y flatpak
15:35:46  No match for argument: flatpak
15:35:46  ERROR: flatpak not installed and could not be installed;
          cannot pre-install org.bootcinstaller.Installer
15:35:46  + exit 1
```

Two things follow. First, **everything before flatpak works**: the base image
pulls, buildah builds, `ensure_dbus_daemon` installs and starts the classic bus,
and the whole customize path runs — in 3.5 minutes. flatpak is the *first* thing
to fail, not one of many. Second, the "No match for argument" comes from dnf
inside the image itself, which is stronger evidence than index scraping that
flatpak is in neither repository.

### A second, independent blocker the same run exposed

The run did not fail at 15:35:46. It failed at **16:32:26**, on
`##[error]The action 'Build the ISO on this runner' has timed out after 60
minutes` — 57 minutes of complete silence after the script exited 1.

The cause is in our script, not in tacklebox. `customize-live.sh` forks a system
`dbus-daemon` before the flatpak block. A forked bus outlives the script, and
the stdout it inherited keeps the build's output pipe open, so the reader waits
long after the script is gone. Demonstrated in isolation: a shell that forks a
child and exits returns immediately when the child is reaped and blocks for the
child's full lifetime when it is not.

This matters beyond one misleading message. `build_artifacts_s2` allows an ISO
cell **90 minutes**. Any failure below that fork — today's missing flatpak, or
whatever fails next once flatpak lands — consumes the cell's entire budget and
then reports itself as a timeout. Fixed by redirecting the daemons' output to
`/dev/null` so they cannot pin the pipe, plus pidfiles and an `EXIT` trap to
reap them; `tests/test_a_failing_live_customize_fails_fast.py` runs the script's
own helpers against a daemon that outlives its caller and fails if the wedge
returns.

### Both of those were confirmed again in production: run 32907940350

Build Hummingbird #66 is the first nightly to run with the fail-fast fix, and
it settled two questions at once.

**The wedge is gone, measured.** `iso:cosmic (linux-amd64)` reached the same
flatpak line and failed in **56 seconds** (03:03:22 → 03:04:18), against the
57 minutes of silence the same failure cost on 32866334376. The `EXIT` trap
fired in the log — `+ _reap_live_buses` — and the cell reported a real exit 1
rather than a timeout.

**The flatpak gate is not an artefact of the e2e harness.** The identical
three lines came out of `ghcr.io/tuna-os/hummingbird:cosmic-linux-amd64`, a
real published image, in the real nightly's real ISO job — not a dispatched
probe of `base`:

```
03:04:18  + dnf5 install -y flatpak
03:04:18  No match for argument: flatpak
03:04:18  ERROR: flatpak not installed and could not be installed;
          cannot pre-install org.bootcinstaller.Installer
```

Everything above it in that job worked: the provenance gate passed (cosmic
published a digest in this run), the image pulled, `ensure_dbus_daemon`
installed and started the bus from `public-hummingbird-x86_64-rpms`. flatpak
is still the first and only thing that fails.

### gnome cannot get as far as cosmic: it wedges in the build

The same run's `gnome / linux-amd64` cell never published at all, so the
`iso:gnome` job was refused by the provenance gate in 0 seconds — correctly,
rather than building media from a stale tag.

The gnome cell did not fail. It stopped:

```
23:12:27  [13/30] pcre2-utf32-0:10.47-1.2.hum1 100% | 247.5 KiB | 00m00s
03:00:31  ##[error]The operation was canceled.
```

Seventeen packages still in flight, then 3h48m without one further line, then
the job's 240-minute ceiling. Compare cosmic, which finished the same stage in
**14 minutes**. The difference is not the desktop — it is that one dnf
download stalled and nothing bounded it. librepo treats a connection
delivering less than 1000 B/s as healthy and waits indefinitely, and
`repo.tunaos.org` is a single small host.

Two bounds now exist: `minrate`/`timeout`/`retries` in `/etc/dnf/dnf.conf`
(written by `10-base-packages.sh`, so every downstream `RUN` layer inherits
them), and a `timeout --kill-after=60s 210m` around the build itself so a
wedge anywhere else fails 30 minutes inside the ceiling with an annotation
instead of a bare cancellation.

The same job also exposed a second, quieter fault: `install-desktop.sh` passed
`--skip-unavailable` *before* `install`, which dnf5 rejects outright. The
call site is `dnf_retry … || install_available …`, so the `||` swallowed our
own usage error and ran all 52 gnome packages through the fallback — which
drops the manifest's `exclude:` list and forces `install_weak_deps=False`. The
build would have composed a different image than the manifest describes even
if it had finished.

### "N packages left" is not a measure of progress

That figure counts the **served index**, which is cumulative across past
publishes. It says nothing about what a chain run accomplishes, and on
2026-08-25 the two came apart completely.

Run [32842254545](https://github.com/tuna-os/tunaos-packages/actions/runs/32842254545)
built for **4h01m** and reached **tier 5 of 22**:

```
11:27:19  [resume] found `hummingbird-x86_64-partial` from 11:26:17Z (429 MB)
11:27:24  [resume] action key differs — the inputs changed, so building from scratch
11:28:58  ===== Tier: bootstrap-00 =====
11:40:54  ===== Tier: layer-00 =====
          (still in layer-00 when cancelled at 15:28:55)
```

`Skipping: 0`. It rejected a 429 MB partial written **thirty-four seconds
earlier** and rebuilt from nothing, because the action key included the whole
of `manifests/package-factory.yaml` — twice, by two independent paths — and an
unrelated edit to another target had moved it.

**The chain was not failing to finish. It was failing to accumulate.** Every
merge that touched the manifest sent a 22-tier chain back to tier 0, which is
why the remaining count never moved however many nightlies ran.

Both manifest paths are closed in tunaos-packages#529. One coupling remains
and is deliberately open in tunaos-packages#528: `scripts/build-chain.sh` is a
whole-file `renderer_inputs` entry, so *any* factory improvement still costs a
full chain restart — #512's mock root-cache change was a pure speedup with no
effect on any package's contents and invalidated every partial in the
repository.

Practical consequence while that stands: **do not edit
`manifests/package-factory.yaml`, `scripts/build-chain.sh`, or
`scripts/run-package-factory-cell.sh` while a chain is converging.** And when
reading a chain run, the `[resume]` line is the single most informative line
in the log — it is the difference between a run that accumulates and one that
starts over, and it went unnoticed for as long as it did because a restarted
run looks identical to a merely slow one.

### `flatpak` is the single package gating the whole ISO axis

Not `gnome-shell`. `flatpak` is **layer-07**, and it blocks three consecutive
steps rather than one:

* the **live-overlay** build — `customize-live.sh` pre-installs the installer
  app and `exit 1`s if flatpak cannot be made present;
* the **CI ISO build** — `build-iso-tacklebox.sh` passes that *same* script as
  the recipe's `live_customize` step;
* the **installer itself** — gnome has no TunaOS-branded frontend fork, so it
  ships upstream `org.bootcinstaller.Installer`, which is a Flatpak.

`ensure_flatpak()`'s `dnf install flatpak` fallback rescues guppy, grouper and
bonito-rawhide, whose distributions package it and whose images merely omit it.
It cannot rescue Hummingbird: flatpak is absent from **both** indexes —
`public-hummingbird` (3510 binary names, revision 1787670929) and our rebuild
snapshot (7986, revision 1786989380), re-measured live on 2026-08-25 at 15:30.
Upstream has not adopted it, so waiting for upstream is not a strategy; it has
to be built.

#### How to re-measure this, and one trap in doing so

Read both indexes and compare BUILD-ORDER SOURCE NAMES against the source of
each binary we serve (`srpm_name(pkg["srpm"])`), not against served binary
names — most of the chain's sources ship under different binary names, and
matching on binary names undercounts what is built.

The trap is the tier INDEX. `flatpak` sits in `layer-07`, which is **tier
index 11**, because the list opens with four bootstrap tiers before `layer-00`.
Filtering on `index <= 7` silently answers a different question and reports far
too little work remaining — measured 15 instead of 53 when this was last
computed. Match on the tier `name`, or find flatpak's index first.

### Re-measured 2026-08-26 03:28: what is actually in each index

Both indexes read live, side by side. The two have moved in opposite
directions since 08-25, and the difference matters more than either number.

| | `public-hummingbird` (upstream) | `tunaos-hummingbird` (ours) |
| :--- | :--- | :--- |
| binary names | 3510 | 7986 |
| repomd revision | 1787711680 = **2026-08-26 02:34** | 1786989380 = **2026-08-17 17:56** |

**Ours has not been republished in eight days and ten hours** — the revision
is byte-identical to the one recorded at 08-25 15:30, and the name count has
not moved either.

That is not a regression. It is that the hummingbird index has never been
published by the publisher at all. `publish-build-chain-rpms.yml` has seven
runs in its whole history: one failed on 08-21 at 05:22 (#463's first
dispatch), three succeeded that morning, one was cancelled, one failed that
night — all of them xfce/gnome50/el10 targets — and run 7 is the hummingbird
one, dispatched 08-26 00:14 and still building. The 08-17 17:56 content
predates the publisher's existence entirely.

So the pipe everything below waits on has not stalled; it has not yet run to
completion once. "N packages left" cannot distinguish those two, because the
served index is exactly what that figure counts.

The shape of the problem is a job budget. Run 32842254545 built for 4h01m and
reached tier 5 of 22. At that rate the chain wants something like seventeen
hours, against a six-hour cap on a hosted job — so it can only ever finish
across several runs, each resuming the last one's partial. That makes the
partial-resume key the whole ballgame, which is why #528/#529 sit on the
critical path to an ISO and not off to one side, and why `build-chain.sh` in
`renderer_inputs` must not be touched while a chain is converging: it would
restart run 7 at bootstrap-00.

Package by package, against what a hummingbird GNOME ISO needs:

| | upstream | ours | union |
| :--- | :---: | :---: | :---: |
| `flatpak` | no | no | **no** |
| `ostree`, `ostree-libs` | **yes** | no | yes |
| `bubblewrap` | yes | yes | yes |
| `appstream` | no | yes | yes |
| `mutter` | no | **yes** | yes |
| `gnome-shell` | no | no | **no** |
| `gdm` | no | no | **no** |
| `gnome-session`, `nautilus` | no | no | **no** |
| `xdg-desktop-portal{,-gnome,-gtk}` | no | no | **no** |
| `NetworkManager-wifi` | yes | no | yes |
| `linux-firmware`, `wpa_supplicant`, `sof-firmware` | no | no | **no** |

Two corrections to what is written above this section.

**flatpak's dependencies are already in reach.** `ostree` is in upstream today
(with `ostree-libs`, `ostree-devel`, `ostree-grub2`), `bubblewrap` is in both,
`appstream` is in ours. flatpak itself is the gap, not a closure behind it.
That is a smaller job than "flatpak plus everything it needs".

**`mutter` arrived in our rebuild** since the 08-15 measurement in #1755, which
listed it as missing. The rest of that issue's §2 list still holds.

### What that means for the goal: 14 of 52, measured on the image itself

Run 32925587829 built `hummingbird:gnome` in **11m33s** and pushed it to
GHCR — the dnf-flag and stalled-download fixes work, and the cell that ran
3h57m and was cancelled the night before now completes in twelve minutes.

That makes the question answerable from the image rather than from the
indexes. Its own published package manifest
(`packages-hummingbird-gnome-linux-amd64`, 405 packages) against the 52 the
manifest asks for:

    requested        52
    present          14
    silently dropped 38

The fourteen: ModemManager, NetworkManager-adsl, NetworkManager-wwan, avahi,
dconf, glib-networking, gnome-backgrounds, gnome-user-docs, mesa-dri-drivers,
mesa-libEGL, mesa-vulkan-drivers, polkit, desktop-backgrounds-gnome,
pinentry-gnome3.

Everything that makes it a desktop is in the other thirty-eight — `gdm`,
`gnome-shell`, `gnome-session-wayland-session`, `gnome-settings-daemon`,
`gnome-control-center`, `nautilus`, `ptyxis`, both xdg-desktop-portals, all
six gvfs backends, `librsvg2`, `yelp`. The only packages in the image whose
names begin with "gnome" are `gnome-backgrounds` and `gnome-user-docs`.

**`hummingbird:gnome` is a 405-package base with wallpapers and
documentation.** Installed to a laptop it reaches a text console. Every
build-side fix in this document is necessary and none of them changes that.

Two details worth keeping. `mutter` IS in our rebuild index but is not in the
image, because nothing requests it directly — it would arrive as a dependency
of `gnome-shell`, which does not exist to depend on it. And `ostree` IS in the
image, from upstream, so flatpak's main dependency is already present.

The ISO axis and the desktop axis are therefore blocked on the same producer
from two directions: no ISO can be built at all without `flatpak`, and the
image one would carry is not a desktop without those thirty-eight. All of it
is the package chain's to produce.

#### 16 of the 38 are built and served — they fall over behind one package

Splitting the 38 against both live indexes gives two very different groups:

* **22 genuinely absent** from both — `gdm`, `gnome-shell`, `nautilus`,
  `ptyxis`, `gnome-control-center`, the portals, `librsvg2` and so on;
* **16 present in an index and dropped anyway** — all six `gvfs-*` backends,
  `gnome-settings-daemon`, `gnome-system-monitor`, `gnome-classic-session`,
  `gnome-browser-connector`, `yelp`, and four NetworkManager VPN plugins.

The second group is not unbuilt. dnf says so itself, in the gnome cell of run
32925587829:

```
Skipping packages with broken dependencies:
 gnome-settings-daemon  x86_64 50.0-4.fc43      tunaos-hummingbird   6.1 MiB
 gtk4                   x86_64 4.22.1-2.fc43    tunaos-hummingbird  28.1 MiB
 gvfs                   x86_64 1.61.90-1.fc43   tunaos-hummingbird   1.2 MiB
 …
 yelp                   x86_64 2:49.1-1.fc43    tunaos-hummingbird   2.2 MiB
```

`gtk4` is in that list, and every other entry is a GTK application. Resolving
gtk4's 71 requires against the union of both indexes leaves exactly two
unmet, and they are the same package:

    gstreamer1-plugins-bad-free-libs(x86-64)
    libgstplay-1.0.so.0()(64bit)

**One missing package takes down gtk4, and gtk4 takes down sixteen.**
`gstreamer1-plugins-bad-free` is in the build order — `layer-05`, alongside
`gstreamer1-plugins-base`, `gtk3` and `gtk4`, all three of which ARE served.
It is one of seven sources that tier is short.

### How far the chain actually is: 570 of 673

Comparing build-order SOURCE names against the source of every binary we
serve (`sourcerpm`, not served binary names — see the trap below):

| tier | sources | served | missing |
| :--- | ---: | ---: | ---: |
| bootstrap-00…03 | 10 | 10 | 0 |
| layer-00 | 190 | 187 | 3 |
| layer-01 | 76 | 71 | 5 |
| layer-02 | 27 | 27 | 0 |
| layer-03 | 22 | 15 | 7 |
| layer-04 | 31 | 27 | 4 |
| layer-05 | 93 | 86 | 7 |
| layer-06 | 90 | 63 | 27 |
| layer-07 | 46 | 27 | 19 |
| layer-08 | 19 | 8 | 11 |
| layer-09 | 17 | 7 | 10 |
| layer-10 | 15 | 11 | 4 |
| layer-11…17 | 37 | 31 | 6 |
| **total** | **673** | **570** | **103** |

The chain is **85% served**, and the gaps are scattered rather than sitting
behind a clean frontier. "Reached tier 5 of 22" describes a from-scratch
rebuild restarting, not how much is actually published — which is why that
figure and this one have felt irreconcilable.

### What the goal needs, by tier

Where each package a working GNOME laptop install requires sits:

| tier | still missing, and what it gates |
| :--- | :--- |
| layer-05 | **`gstreamer1-plugins-bad-free`** → gtk4 → 16 packages; `librsvg2` |
| layer-06 | `gnome-session`, `xdg-user-dirs-gtk` |
| layer-07 | **`flatpak`** → the entire ISO axis; `gdm`, `ptyxis`, `gnome-bluetooth` |
| layer-08 | `gnome-control-center`, `xdg-desktop-portal`, `gnome-disk-utility`, `gnome-initial-setup`, `fprintd` |
| layer-09 | **`gnome-shell`**, `xdg-desktop-portal-gnome`, `xdg-desktop-portal-gtk` |
| layer-10 | `nautilus` |

So an ISO needs the chain through **layer-07**, and a desktop worth
installing needs it through **layer-10**.

Two of the 38 can never arrive as the build order stands: `evince` and
`totem` are not in it at all, so `evince-thumbnailer`, `evince-previewer` and
`totem-video-thumbnailer` have no producer. Either add them or stop asking
for them in `manifests/desktops/gnome.yaml`.

#### Reproducing all of the above

```bash
# both indexes
curl -s https://repo.tunaos.org/hummingbird/20251124-x86_64/repodata/repomd.xml
curl -s https://packages.redhat.com/api/pulp-content/public-hummingbird/x86_64/repodata/repomd.xml
# what the image actually got: the build job's own artifact, no image pull
#   packages-hummingbird-<flavor>-<platform>  (405 lines for gnome)
```

Compare build-order SOURCE names against `sourcerpm` from the index, never
against served binary names — most sources ship under different binary names
and matching on those undercounts what is built. The other trap, tier INDEX
vs tier NAME, is described under "flatpak is the single package gating the
whole ISO axis" above.

#### Why 38 dropped packages went unremarked

`install_available` records them to `/usr/share/tunaos/missing-on-*.txt`
inside the image, and the only thing that reads that is
`generate-boot-report.py`, run by `weekly-boot-report.yml` — weekly, and by
pulling each published image. Meanwhile every build job already uploads its
own `packages-<image>-<flavor>-<platform>.txt` artifact on every run, which
is what the numbers above were computed from, at no cost and with no image
pull. A per-run completeness count against the manifest would turn this from
a weekly archaeology exercise into a number on the build.

### Link 7: firmware, and why CI can never tell you about it

`linux-firmware` and every per-device firmware package are absent from
`hummingbird:base` (287 packages) and `hummingbird:gnome` (405), from
`public-hummingbird`, from our published snapshot, **and from the 673-entry
build order**. Nothing is scheduled to build them. Measured 2026-08-25 against
the images' own rpm manifests and both repodata indexes; full table in #2064.

QEMU cannot surface this, and that is the point. virtio needs no firmware, so
`installer-smoke` and `iso-e2e` pass on media that would reach a laptop with:

* **no wifi** — no firmware, no `wpa_supplicant`, and NetworkManager present
  without its wifi plugin (`NetworkManager-wifi` exists in `public-hummingbird`
  and is simply not requested);
* **no GPU initialisation** on amdgpu or recent i915/xe, which need firmware
  blobs before the display comes up at all;
* **no audio** on any modern Intel laptop, which needs `sof-firmware`.

The driver *userspace* is fine — the gnome layer already brings
`mesa-dri-drivers`, `libdrm` and `mesa-libgbm`. This is specifically a firmware
gap.

It is also not obviously a Hummingbird bug. A hardened, desktop-less
server/container base omitting ~500 MB of unauditable vendor blobs is a
defensible choice; the gap only appears when the desktop flavors point it at
a laptop. #2064 lays out the four options and deliberately does not pick one,
because the choice trades the hardening premise against hardware support and
that is a maintainer's call.

**Do not read a green `installer-smoke` cell as evidence that a laptop install
works.** Every passing cell in `docs/MATRIX-STATUS.md`, including the single
`yellowfin gnome` one, is QEMU.

### The precedent that says this is achievable

`docs/MATRIX-STATUS.md` records **one** passing installer-smoke cell out of 36:
`yellowfin gnome`. The same matrix records that cosmic, niri, xfwl4 and kde do
not bring a session up on hosted CI, while gnome does. So gnome is the only
desktop with a working end-to-end precedent, and hummingbird gnome runs the
identical installer. Its gap to that precedent is links 1 and 6 above, not the
machinery in between.

Worth keeping honest: installer smoke runs in QEMU. It proves an ISO boots, the
installer appears, and the walkthrough can drive it. **No variant has a proven
install on physical hardware** — that step is manual and nothing in CI stands in
for it.

### Our own repo can shadow upstream's fixes

The desktop manifests and the base stage both add our rebuild repo at
`priority: 5`, and dnf priority is *absolute* rather than a tie-break. So for
any package present in both indexes, ours installs even when upstream's is
newer. Measured: 30 names overlap, **16 of them older on our side**, including
`sudo` fifteen releases behind. The gap measurement drops adopted packages from
the BUILD ORDER but nothing withdraws the already-published copy.
`scripts/check-upstream-shadowing.py` in tunaos-packages now fails on this.

## Rules of thumb for future work here

1. **Do not call it a Fedora rebuild.** It is a hardened rolling fork tracking
   Rawhide with its own CVE lifecycle per package.
2. **Do not infer the package set from Fedora.** Measure the actual index. The
   repodata is public and small: fetch `repodata/repomd.xml`, then the
   `primary.xml.gz` it names, and grep. That takes seconds and beats any
   assumption.
3. **A missing package may be intentional.** Before filing it as a packaging
   bug, consider that minimalism is the product.
4. **Desktop flavors are a port onto a desktop-less base.** Expect gaps; expect
   them to be structural rather than accidental.
5. **Both pins move.** Refreshing one without the other is how the halves drift.

## Related

- `build_scripts/10-base-packages.sh` — where the snapshot repo is configured
- `scripts/check-package-repo-pins.py` — pin reachability *and* snapshot age
- `build_scripts/checks/verify-desktop-experience.sh` — carries a blanket
  hummingbird exemption; it reports a **waiver**, not a pass, when requirements
  are unmet
- tunaos-packages#401, #406, #412 — hummingbird desktop package builds not
  completing; the reason the snapshot lacks a desktop set
