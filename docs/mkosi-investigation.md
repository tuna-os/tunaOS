# Investigation: mkosi as a build backend, and mkosi DDI output (#999)

> **→ See also [ADR 0003](adr/0003-mkosi-co-build-poc.md)** for concrete mkosi
> profile templates, build/boot commands, and the POC scaffolding that follows
> from this investigation.

Status: **investigation only — no proof-of-concept boot performed, no production
change recommended.** Per the issue's own gate ("no production switch until the
POC boots"), that alone rules out adopting anything here yet: this sandbox has
no podman/buildah/mkosi/QEMU, so the actual "boot both from this repo" half of
the deliverable could not be attempted. What follows is the research half —
read `manifests/desktops/`, `build_scripts/`, and `.github/build-config.yml`
for the parts of this repo's current pipeline referenced below; they aren't
reproduced here.

## Recommendation

**Do not migrate to mkosi. A scoped, single-variant mkosi POC is worth doing
next, run by someone with real build tooling — not a wholesale Containerfile
replacement, and not a DDI adoption in the near term.** The two asks in this
issue's title turn out to be very different in scope, and treating them
separately matters:

1. **mkosi as a bootc/OCI build backend** — plausible, low-risk *if* proven:
   the reference project's own output is a plain OCI image, which should be a
   drop-in replacement for what `buildah build` produces today. See "Finding
   1" below.
2. **mkosi DDI output** — not a drop-in second artifact. The reference
   project's own DDI profile is a *different OS deployment model*
   (`systemd-sysupdate` + dm-verity + UKI, not ostree/bootc), and its own
   maintainers flag it "should not be used by default." See "Finding 2."

## What I checked, and how

No repo-local build tooling was available (no podman/buildah/mkosi/QEMU, no
root, in this sandbox), so this investigation is entirely source-reading: this
repo's own pipeline (`build_scripts/`, `.github/build-config.yml`,
`docs/PIPELINE.md`, `docs/build-pipeline.md`), plus the two reference projects
named in the issue, fetched live via the GitHub API rather than assumed from
memory:

- `zirconium-dev/zirconium` — its actual `mkosi.conf`, `mkosi.conf.d/`, and
  every directory under `mkosi.profiles/`, plus its `Justfile` (the real build
  and boot commands it runs).
- `ublue-os/aurora` — repo contents, branch list, and an org-wide code search
  for `mkosi`.

## Finding 1: mkosi's bootc/ostree output is a plain OCI image, not a new artifact type

`mkosi.profiles/bootc-ostree/mkosi.conf` in zirconium:

```ini
# This profile attempts to replicate what quay.io/fedora/fedora-bootc:latest does.
[Content]
RemoveFiles=
    /usr/etc
    /var/
    /boot/*

[Content]
Bootable=no
KernelCommandLine=

[Output]
OciLabels=containers.bootc=1
Format=oci
```

`Format=oci` with a `containers.bootc=1` label — mkosi is not producing an
ostree repo, a disk image, or anything bootc-specific at the format level. It
produces a rootfs, packages it as a standard OCI image, and labels it the way
`quay.io/fedora/fedora-bootc` is labeled. Their own `Justfile` confirms the
whole downstream chain treats it exactly like any other container image:

```
build-ostree:  mkosi -B --profile=base,base-desktop,bootc-ostree,brew,zirconium-bootc-ostree
load:          podman load -i <mkosi.output oci-archive> | podman tag ... {{image}}
lint:          podman run --rm --entrypoint=bootc {{image}} container lint
ostree-rechunk: bootc-base-imagectl rechunk ... (via quay.io/centos-bootc/centos-bootc:stream10)
rechunk:       quay.io/coreos/chunkah ...   ← the SAME chunkah tool docs/PIPELINE.md cites for this repo
disk-image:    bootc install to-disk --generic-image --bootloader grub --via-loopback ... --wipe
```

`podman load`, `bootc container lint`, `bootc-base-imagectl rechunk`,
`chunkah`, and `bootc install to-disk` are all things this repo's own pipeline
already does to its buildah-built images (`docs/PIPELINE.md`'s "Rechunk" step;
the LUKS E2E harness's `sudo fisherman recipe.json` path, which drives the
same `bootc install` machinery). **If mkosi produced an equivalent OCI image
for a TunaOS variant, none of that downstream chain — cosign signing,
`reusable-build-image.yml`'s rechunk step, `iso-e2e.sh`/LUKS E2E, or
tacklebox's ISO builder — would need to know or care that mkosi built it
instead of buildah.** The two build backends would be interchangeable at
exactly the point this repo already treats as a boundary: a tagged OCI image.

This directly de-risks constraint #1 in the issue ("`just iso`/tacklebox ISO
path must keep working... mkosi roots must remain container-installable") —
they would, because the mkosi output already *is* a container image, not a
root tree tacklebox would need new code to understand.

## Finding 2: mkosi's DDI output is a different OS model, not an alternate packaging

`mkosi.profiles/sysupdate/mkosi.conf` — the actual disk-image (`Format=disk`)
profile in the same repo, quoted here because the opening line is the
investigation's single most load-bearing sentence:

```ini
# THIS PROFILE SHOULD NOT BE USED BY DEFAULT
# This is an implementation of sysupdate-based zirconium, everything that
# would be necessary to implement the same idea as systemd's particleOS.

[Output]
SplitArtifacts=uki,partitions
Format=disk

[Content]
Bootable=yes
Bootloader=systemd-boot
...
KernelCommandLine=
    mount.usr=dissect
    root=dissect
    systemd.image_policy=esp=unprotected:xbootldr=unprotected+unused+absent:usr=signed:root=encrypted+absent:...
    systemd.verity_usr_options=root-hash-signature=auto
```

This is **not** "the same rootfs, packaged as a disk image instead of a
container." It's a `/usr`-verity, dm-verity-sealed, UKI-booted,
`systemd-sysupdate`-driven deployment model — the architecture systemd's
*particleOS* experiment explores, built on `systemd-repart`/`systemd-dissect`
image policies with no ostree or bootc involved anywhere. Building this for a
TunaOS variant would mean adopting a second, parallel update mechanism with
its own verity signing, its own A/B partition/update tooling, and its own
boot chain — not adding a second `mkosi build --format=disk` flag next to the
OCI build. Zirconium's own maintainers ship it as opt-in and explicitly say
not to default to it.

**Reading of the issue's premise:** grouping "bootc + mkosi DDI, boot both"
as one build-backend question undersells how different these two outputs
actually are in the one working reference this repo already points at. A DDI
worth having (`systemd-sysext`/portable services, VM images — the issue's own
examples) doesn't need the sysupdate/verity apparatus; it needs `Format=disk`
with `Bootable=no` or a plain UKI, which is a much smaller ask than replicating
zirconium's `sysupdate` profile. That smaller version is plausible follow-up
work; a `systemd-sysupdate`-based *deployment* migration is not what this
issue's three-item POC scope should be trying to prove.

## Correction: ublue-os/aurora shows no mkosi adoption

The issue states "Bluefin/ublue and Aurora are moving the same way [as
zirconium, to mkosi]." Checked directly rather than taken on faith:

- `ublue-os/aurora`'s repo contents still show `Containerfile.in` at the top
  level — the same architecture this repo uses, not mkosi.
- A GitHub code search for `mkosi` across `ublue-os/aurora` returns 0 results.
- An org-wide code search (`org:ublue-os mkosi`) and repo-name search both
  return 0 results — no repository or file anywhere in the `ublue-os` org
  currently references mkosi.

This doesn't mean the claim is false — it may be discussed somewhere this
investigation can't reach (Discord, an unmerged fork, a blog post) — but it is
**not currently verifiable from the ublue-os GitHub org**, so it shouldn't be
treated as a second working reference alongside zirconium. As of this
investigation, zirconium is the only concrete mkosi+bootc precedent available
to learn from.

## What today's zirconium coupling actually is (context for "why now")

`build_scripts/install-zirconium.sh` — the stopgap this issue wants to
replace — does not invoke mkosi at all. It downloads zirconium's *source
tarball*, reads `mkosi.extra` (a static root-filesystem overlay tree — the
`mkosi.extra` directory mkosi would otherwise copy verbatim into a build), and
`cp`/`install`s a hand-picked subset of files into the TunaOS image during a
normal Containerfile `RUN`. It never runs zirconium's own `mkosi.conf`,
profiles, or package resolution — it reaches past mkosi and takes one static
ingredient. So the *current* coupling to zirconium is thinner than "we depend
on their build system" — it's "we depend on one fixed file tree from a project
that has a build system we don't use," which is arguably more fragile (no
package-manager-level guarantee those files stay consistent with whatever
niri/DMS version TunaOS's own manifests install) than either staying
Containerfile-only or adopting mkosi properly.

## Toolchain feasibility

Zirconium pins `MinimumVersion=26~devel`. Checked against `systemd/mkosi`'s
actual releases: **v26 shipped as a stable release on 2025-12-17**, so this is
not a version that doesn't exist yet — but it is recent enough that it won't
be the default `mkosi` package on older/LTS-pinned distros, meaning any CI
runner image adopting this would need a current mkosi install (pip/pipx, or a
Fedora release recent enough to carry it), not whatever ships by default.
Minor, but worth budgeting for in a POC's CI setup rather than discovering it
mid-build.

## What this investigation could not do

- **No proof-of-concept boot.** Could not build anything with mkosi, could not
  boot a bootc image or a DDI in QEMU, and therefore cannot confirm any of the
  above beyond what's directly readable in zirconium's own committed config.
  The issue's deliverable explicitly gates a production switch on a POC boot
  succeeding — none has happened, by me, here.
- **No signing dry run** against constraint #4 (mkosi output signing, cosign
  keyless). `docs/build-pipeline.md` confirms cosign signing already works for
  this repo's *current* (buildah-built) images; whether an mkosi-produced OCI
  image signs identically through the same `reusable-build-image.yml` step is
  untested, though Finding 1 suggests it should, since it's the same OCI
  format at the point signing happens.
- **No RHSM / overlay-stage (hwe/nvidia/cachyos/asahi) compatibility check.**
  The issue calls these out as open questions; this investigation did not
  reach far enough into zirconium's `mkosi.conf.d/fedora/` or subprojects to
  answer them.
- **No build-time or output-size comparison** against the current
  buildah/Containerfile path.

## Suggested next step

A single-variant spike, run with real tooling (not this investigation):
Fedora-based (`bonito`, since it's the same distro family zirconium already
targets) → an mkosi profile stack modeled on zirconium's `bootc-ostree`
profile (OCI output, `containers.bootc=1` label) → `podman load` the result →
run it through this repo's *unmodified* `bootc container lint`, rechunk step,
and `iso-e2e.sh`/LUKS E2E harness exactly as if it were a buildah build. If
that boots and passes the existing gate unmodified, Finding 1 is confirmed in
practice and a hybrid (mkosi as an alternate backend for one variant, behind a
flag, Containerfiles everywhere else) becomes a reasonable follow-up proposal.
A DDI POC is a separate, later piece of work and should not block or be
bundled with this one — see Finding 2.

## Alignment with Image Factory Completion Gate (#1283)

Any eventual POC or adoption of an mkosi-built variant must pass the unified
[Image Factory Completion Gate](IMAGE-FACTORY-GATE.md) (`docs/IMAGE-FACTORY-GATE.md`).
Specifically:
- OCI Build & Publish reproducibility with keyless Cosign signatures and SPDX SBOMs.
- Full LUKS install-to-disk and bootc update/rebase/rollback verification (`bootc-lifecycle.yml`).
- Compatibility with on-demand and browser-based ISO generators (`publish-iso-groups.yml`).

