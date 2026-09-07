# GNOME 51 test and rollout plan

**Status**: decision recorded 2026-09-07

**Tracks**: [#1775](https://github.com/tuna-os/tunaOS/issues/1775), [#1717](https://github.com/tuna-os/tunaOS/issues/1717), [#1334](https://github.com/tuna-os/tunaOS/issues/1334)

## Decision

GNOME 51 does not roll out to every TunaOS base at once.

1. **Use `hummingbird:gnome` as the GNOME 51 canary.** Hummingbird gets the
   coherent GNOME stack from Bluefin's `projectbluefin/utah-packages`
   repository image. TunaOS pins that image by digest, mounts its repository
   only while building the GNOME layer, and tests the resulting TunaOS image.
2. **Keep EL10 on the factory-built GNOME 50 tier.** Yellowfin, Albacore, and
   Skipjack must not be advertised as GNOME 51. Their configured source is the
   digest-pinned `gnome50-el10-x86_64` image from `tuna-os/tunaos-packages`.
   The old beta-call proposal depended on an EL10 GNOME 51 HTTP repository
   which never became the image input; waiting on or documenting that URL is
   not a rollout strategy.
3. **Let distro-native variants advance independently.** Fedora, Arch,
   openSUSE, Debian, Ubuntu, and Gentoo consume their own package ecosystems.
   They continue through the normal per-variant build and promotion gates;
   there is no fleet-wide switch that forces all of them to version 51.
4. **Do not create a user-facing beta tag.** Candidates already publish under
   the existing `:gnome-testing` tag. The workflow is the source of truth:
   only its Promote job writes the bare `:gnome` tag after the candidate's
   signing, desktop, boot, and architecture gates complete.

This separates testing a new desktop from replacing the EL10 package platform.
It also keeps rollback ordinary: promotion never mutates an existing booted
deployment, and a tester can retain or return to the previous bootc deployment.

## Why Hummingbird is the canary

Hummingbird is a rolling, hardened Rawhide fork, not EL10. Bluefin builds GNOME
51 in Hummingbird's own build root and publishes the result as an OCI-carried
RPM repository. Reusing that repository avoids a second GNOME 51 build with a
different dependency closure.

The supply path is reviewable in this repository:

- `image-versions.yaml` pins `utah-packages` by digest;
- `registry-map.yaml` names `ghcr.io/projectbluefin/utah-packages`;
- `Containerfile.el10` bind-mounts `/repository` only into the GNOME build;
- `manifests/desktops/gnome.yaml` gives that local repository priority over
  TunaOS's supplemental Hummingbird repository; and
- `tests/test_hummingbird_gnome_consumes_utah_packages.py` holds the pin,
  mount, priority, and local-only signature exception together.

See [HUMMINGBIRD.md](HUMMINGBIRD.md) for the base's package and architecture
constraints.

## Canary procedure

### 1. Build and inspect the candidate

A maintainer dispatches **Build Hummingbird** with `flavor=gnome`, or inspects
the scheduled run. Use the candidate from that run, not a tag left by an older
run:

```text
ghcr.io/tuna-os/hummingbird:gnome-testing
```

Record the workflow URL and resolved image digest. In the run, require:

- the package manifest identifies GNOME Shell, Mutter, GDM, Nautilus, and the
  control center from the expected candidate;
- `gnome-shell --version` reports major version 51;
- the desktop contract has no `TUNAOS_DESKTOP_CONTRACT_WAIVED` result;
- the wishlist reports no unapproved package misses;
- signing and provenance checks pass; and
- the boot gate installs the candidate, boots it in QEMU, and reaches the
  graphical-session marker.

A Hummingbird waiver is not a pass for this rollout. It exists to let an
incomplete port build while it is being bootstrapped; a waived GNOME 51 canary
stays on `:gnome-testing` even if another automated condition would permit
promotion.

### 2. Exercise the desktop

Use a disposable VM or spare machine and keep a known-good deployment. Test at
least:

- GDM login and logout under Wayland;
- Settings, Files, Terminal, Software, and a Flatpak;
- audio, networking, portals, clipboard, and screenshots;
- suspend/resume and multi-monitor or fractional scaling when available;
- `bootc upgrade`, reboot, and `bootc rollback`; and
- one cold boot after rollback.

Capture:

```bash
gnome-shell --version
rpm -q gnome-shell mutter gdm nautilus gnome-control-center gtk4 libadwaita
sudo bootc status
```

Report the image digest, workflow URL, hardware or VM details, commands above,
reproduction steps, logs, and rollback result. Packaging or dependency-closure
problems belong in
[`tuna-os/tunaos-packages`](https://github.com/tuna-os/tunaos-packages/issues);
TunaOS image, boot, and integration problems belong in
[`tuna-os/tunaOS`](https://github.com/tuna-os/tunaOS/issues).

Treat failure to boot, log in, use networking, or roll back as release-blocking.
Remove hostnames, serial numbers, tokens, and other private data from logs.

### 3. Promote or hold

Promote only the exact digest tested above. The normal Promote job copies the
verified `:gnome-testing` manifest to `:gnome` and dated tags. If a blocking
regression appears after promotion, follow
[rollback-a-bad-image-promotion.md](../runbooks/rollback-a-bad-image-promotion.md)
rather than rebuilding an unreviewed hotfix under the same tag.

## EL10 graduation criteria

Moving Yellowfin, Albacore, or Skipjack from GNOME 50 to 51 is a separate
package-platform change. It requires all of the following in one reviewable
rollout:

- a complete GNOME 51 repository image produced by the TunaOS package factory,
  pinned by digest and consumed with the same local-mount trust model as the
  current GNOME 50 tier;
- an explicit architecture decision: provide each declared architecture or
  keep GNOME flavors pinned to architectures the tier actually serves;
- regression coverage equivalent to
  `tests/test_el10_gnome_comes_from_the_github_built_tier.py`, updated for the
  new tier without restoring COPR or an unsigned network repository;
- a candidate proving GNOME major 51, the desktop and wishlist contracts, image
  signing, boot-to-GDM, installer media, upgrade, and rollback; and
- an announcement naming the tested image digest and any architecture or
  hardware limitations.

Until those criteria pass, EL10's GNOME 50 images continue normally. GNOME 51's
upstream release date alone is not a reason to bypass package-factory or image
promotion gates.
