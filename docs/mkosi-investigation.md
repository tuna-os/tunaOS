# Investigation: mkosi as a build backend, and mkosi DDI output (#999)

> **→ See also [ADR 0003](adr/0003-mkosi-co-build-poc.md)** for concrete mkosi
> profile templates, build/boot commands, and the POC scaffold that follows
> from this investigation.

Status: **investigation only — no proof-of-concept boot performed, no production
change recommended.** The issue's own gate says "no production switch until
the POC boots". That alone rules out adoption of anything here yet. This
sandbox has no podman/buildah/mkosi/QEMU, so nobody could try the "boot both
from this repo" half of the deliverable.

What follows is the research half. Read `manifests/desktops/`,
`build_scripts/`, and `.github/build-config.yml` for the parts of this repo's
current pipeline referenced below; they aren't reproduced here.

## Recommendation

**Do not migrate to mkosi. A scoped, single-variant mkosi POC is worth doing
next. Someone with real build tooling must run it. Do not make a wholesale
Containerfile replacement, and do not adopt a DDI in the near term.**

The two asks in this issue's title turn out to be different in scope, and that
difference matters:

1. **mkosi as a bootc/OCI build backend** — plausible, low-risk *if* proven.
   The reference project's own output is a plain OCI image. That image should
   be a drop-in replacement for what `buildah build` produces today. See
   "Result 1" below.
2. **mkosi DDI output** — not a drop-in second artifact. The reference
   project's own DDI profile is a *different model for OS deployment*
   (`systemd-sysupdate` + dm-verity + UKI, not ostree/bootc). Its own
   maintainers flag it "should not be used by default." See "Result 2."

## What I checked, and how

No repo-local build tooling was available (no podman/buildah/mkosi/QEMU, no
root, in this sandbox). So this investigation reads source only. It covers
this repo's own pipeline (`build_scripts/`, `.github/build-config.yml`,
`docs/PIPELINE.md`, `docs/build-pipeline.md`), plus the two reference projects
that the issue names. I fetched those live via the GitHub API and did not
assume them from memory:

- `zirconium-dev/zirconium` — its actual `mkosi.conf`, `mkosi.conf.d/`, and
  every directory under `mkosi.profiles/`, plus its `Justfile` (the real build
  and boot commands it runs).
- `ublue-os/aurora` — repo contents, branch list, and an org-wide code search
  for `mkosi`.

## Result 1: mkosi's bootc/ostree output is a plain OCI image, not a new artifact type

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

`Format=oci` with a `containers.bootc=1` label — mkosi does not produce an
ostree repo, a disk image, or anything bootc-specific at the format level. It
produces a rootfs, packages it as a standard OCI image, and gives it the same
labels as `quay.io/fedora/fedora-bootc`. Their own `Justfile` confirms that
everything downstream treats it exactly like any other container image:

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
already does to its buildah-built images. Examples are the "Rechunk" step in
`docs/PIPELINE.md`, and the `sudo fisherman recipe.json` path in the LUKS E2E
harness, which drives the same `bootc install` machinery.

**Suppose mkosi produced an equivalent OCI image for a TunaOS variant. That
downstream chain is cosign signatures, `reusable-build-image.yml`'s rechunk
step, `iso-e2e.sh`/LUKS E2E, and tacklebox's ISO builder. None of it would
need to know or care that mkosi built it instead of buildah.**

The two build backends would be interchangeable at exactly the point this repo
already treats as a boundary: a tagged OCI image.

This directly de-risks constraint #1 in the issue ("`just iso`/tacklebox ISO
path must continue to work... mkosi roots must remain container-installable") —
they would. The mkosi output already *is* a container image. It is not a root
tree that tacklebox would need new code to understand.

## Result 2: mkosi's DDI output is a different OS model, not an alternate packaging

`mkosi.profiles/sysupdate/mkosi.conf` — the actual disk-image (`Format=disk`)
profile in the same repo. I quote it here because its first line carries more
weight than any other sentence in this investigation:

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
`systemd-sysupdate`-driven deployment model. It is the architecture that
systemd's *particleOS* experiment explores. It builds on
`systemd-repart`/`systemd-dissect` image policies, with no ostree or bootc
involved anywhere.

To build this for a TunaOS variant would mean a second, parallel update
mechanism. That mechanism has its own verity signatures, its own A/B
partition/update tooling, and its own boot chain. It is not a second `mkosi
build --format=disk` flag next to the OCI build. Zirconium's own maintainers
ship it as opt-in and explicitly say not to default to it.

**How I read the issue's premise:** it groups "bootc + mkosi DDI, boot both"
into one question about the build backend. That undersells how different these
two outputs are in the one reference that works, which this repo already
points at.

A DDI worth having (`systemd-sysext`/portable services, VM images — the
issue's own examples) doesn't need the sysupdate/verity apparatus. It needs
`Format=disk` with `Bootable=no` or a plain UKI. That is a much smaller ask
than a replica of zirconium's `sysupdate` profile. That smaller version is
plausible follow-up work. A *deployment* migration based on
`systemd-sysupdate` is not what this issue's three-item POC scope should be
trying to prove.

## Correction: ublue-os/aurora shows no mkosi adoption

The issue states "Bluefin/ublue and Aurora are moving the same way [as
zirconium, to mkosi]." Checked directly, not taken on faith:

- `ublue-os/aurora`'s repo contents still show `Containerfile.in` at the top
  level — the same architecture this repo uses, not mkosi.
- A GitHub code search for `mkosi` across `ublue-os/aurora` returns 0 results.
- An org-wide code search (`org:ublue-os mkosi`) and repo-name search both
  return 0 results. No repository or file anywhere in the `ublue-os` org now
  refers to mkosi.

This doesn't mean the claim is false. People may discuss it somewhere this
investigation can't reach (Discord, an unmerged fork, a blog post). But it is
**not verifiable now from the ublue-os GitHub org**. So nobody should treat it
as a second reference that works, alongside zirconium. As of this
investigation, zirconium is the only concrete mkosi+bootc precedent available
to learn from.

## What today's zirconium coupling actually is (context for "why now")

`build_scripts/install-zirconium.sh` — the stopgap this issue wants to
replace — does not invoke mkosi at all. It downloads zirconium's *source
tarball* and reads `mkosi.extra`. That is a static overlay tree for the root
filesystem — the `mkosi.extra` directory mkosi would otherwise copy verbatim
into a build. It then `cp`/`install`s a hand-picked subset of files into the
TunaOS image during a normal Containerfile `RUN`. It never runs zirconium's
own `mkosi.conf`, profiles, or package resolution — it reaches past mkosi and
takes one static ingredient.

So the *current* link to zirconium is thinner than "we depend on their build
system". It is "we depend on one fixed tree of files from a project that has a
build system we don't use". That is arguably more fragile than a
Containerfile-only approach, or than proper adoption of mkosi. Nothing at the
package-manager level guarantees that those files stay consistent with
whatever niri/DMS version TunaOS's own manifests install.

## Toolchain feasibility

Zirconium pins `MinimumVersion=26~devel`. I checked this against the actual
releases of `systemd/mkosi`: **v26 shipped as a stable release on
2025-12-17**. So this is not a version that doesn't exist yet. But it is
recent enough that it won't be the default `mkosi` package on older/LTS-pinned
distros. So any CI runner image that adopts this would need a current mkosi
install, not whatever ships by default. That means pip/pipx, or a Fedora
release that is recent enough to carry mkosi.

This point is minor. Even so, a POC should budget for it in its CI setup, and
not discover it mid-build.

## What this investigation could not do

- **No proof-of-concept boot.** I could not build anything with mkosi. I could
  not boot a bootc image or a DDI in QEMU. So I cannot confirm any of the
  above beyond what's directly readable in zirconium's own committed config.
  The issue's deliverable explicitly gates a production switch on a successful
  POC boot — none has happened, by me, here.
- **No dry run of the signature step** against constraint #4 (signature of
  mkosi output, cosign keyless). `docs/build-pipeline.md` confirms that cosign
  already signs this repo's *current* (buildah-built) images. Nobody has
  tested whether an mkosi-produced OCI image gets the same signature through
  the same `reusable-build-image.yml` step. Result 1 suggests it should,
  since it is the same OCI format at the point where cosign signs.
- **No RHSM / overlay-stage (hwe/nvidia/cachyos/asahi) compatibility check.**
  The issue calls these out as open questions. This investigation did not
  reach far enough into zirconium's `mkosi.conf.d/fedora/` or subprojects to
  answer them.
- **No build-time or output-size comparison** against the current
  buildah/Containerfile path.

## Suggested next step

A single-variant spike, run with real tooling (not this investigation). Start
from a Fedora base (`bonito`, since zirconium already targets the same distro
family). Model an mkosi profile stack on zirconium's `bootc-ostree` profile
(OCI output, `containers.bootc=1` label). Then `podman load` the result. Then
run it through this repo's *unmodified* `bootc container lint`, rechunk step,
and `iso-e2e.sh`/LUKS E2E harness, exactly as if it were a buildah build.

Suppose that spike boots and passes the existing gate unmodified. That
confirms Result 1 in practice, and a hybrid becomes a reasonable follow-up
proposal. That hybrid is mkosi as an alternate backend for one variant, behind
a flag, with Containerfiles everywhere else. A DDI POC is a separate, later
piece of work. It should not block this one, and nobody should bundle it with
this one — see Result 2.

## Alignment with Image Factory Completion Gate (#1283)

Any eventual POC or adoption of an mkosi-built variant must pass the
[completion gate](IMAGE-FACTORY-GATE.md) of the Image Factory (`docs/IMAGE-FACTORY-GATE.md`).
Specifically:
- OCI Build & Publish reproducibility with keyless Cosign signatures and SPDX SBOMs.
- Full LUKS install-to-disk and bootc update/rebase/rollback verification (`bootc-lifecycle.yml`).
- Compatibility with on-demand and browser-based ISO generators (`publish-iso-groups.yml`).

