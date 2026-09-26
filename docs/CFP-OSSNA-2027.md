# Open Source Summit North America 2027 — CFP Draft

> Status: **draft** — for maintainer review before submission.
> Event: Open Source Summit North America (Linux Foundation). Exact 2027 dates,
> venue, and CFP window are **not confirmed in this draft** — the Linux
> Foundation publishes them per-year on the event site; a maintainer must
> confirm before submitting (see checklist below).
> Tracking issue: [#1135](https://github.com/tuna-os/tunaOS/issues/1135) (2027
> conference CFP season, also covers FOSDEM).

## Talk title (working)

**The Enterprise Linux Desktop Nobody Shipped: bootc, Corral, and Closing the Server/Desktop Gap**

## Suggested track

- **Containers / Cloud Native** (primary) — bootc image model, OCI-native desktop delivery
- **Linux systems / Kernel & OS** (secondary) — atomic update and rollback model
- **Emerging OS / Enterprise Open Source** (fallback)

## Abstract (≈250 words, submission-ready)

Enterprise Linux distributions guarantee ten-year server lifecycles, but their
desktop editions track years-old package sets — so most enterprises run a
different distribution on the desk than in the datacenter. TunaOS closes that
gap using the same technology that already runs the server fleet: bootable
containers (bootc).

TunaOS builds bootc images on AlmaLinux 10, CentOS Stream 10, and Fedora, then
ships current desktop environments — GNOME (backported ahead of the EL point
release), KDE Plasma 6, the Rust-built COSMIC, and the scrollable-tiling Niri
— as atomic, rollback-safe images, alongside variants on Ubuntu, Debian, Arch,
Gentoo, and openSUSE using the same model. Updates apply as a single OCI
transaction with automatic rollback on failure — the same operational model
platform teams already use for container fleets, applied to the desktop
estate.

This talk covers the manifest-driven build pipeline that turns a YAML
definition into a published, multi-arch (amd64+arm64) desktop image; the
keyless (Sigstore/cosign) signing and Rekor-verified supply chain behind every
published artifact; and Corral, a Kubernetes-native VM manager that
declares desktop VMs as cluster resources — schedule, snapshot, and GPU
passthrough as code, same as any other workload.

Attendees leave with a working model for image-based enterprise desktops,
concrete manifest/podman patterns they can reuse, and an honest comparison
against Silverblue, uBlue, NixOS, and MicroOS — no vendor pitch, an
open-source project's architecture talk with a live demo.

## Demo outline (attach to CFP; reuses the FOSDEM/SCaLE recording)

Same beats as the [FOSDEM 2027 draft](./CFP-FOSDEM-2027.md) — see
[CFP-DEMO-SCRIPT.md](./CFP-DEMO-SCRIPT.md) for the shot list, exact commands,
and per-shot timings. One recording serves both submissions; do not shoot a
second one.

1. `podman pull` a TunaOS image; show the layered FS
2. `bootc upgrade` on a live VM → atomic swap; `bootc rollback` on induced failure
3. Corral: declare a desktop VM as a manifest, `kubectl apply`, watch it schedule
4. Boot the updated image; GNOME session running on AlmaLinux 10

## Logistics

- Length: standard OSS NA breakout slot (confirm exact length once the CFP
  portal specifies it — historically 25–40 min across LF events; do not guess
  a number into the submission form)
- Speaker: maintainer or maintainer-designate
- Materials: laptop + prebuilt demo VMs (images already published to GHCR;
  Corral runs anywhere with KubeVirt)

## bootc / CNCF ecosystem angle

bootc is a CNCF Sandbox project ([ADOPTERS.md](../ADOPTERS.md) upstream
table). TunaOS is a production bootc *desktop* deployment built on it. OSS NA
is a Linux Foundation event and a natural venue for a CNCF-ecosystem-adjacent
case study, independent of any FOSDEM submission outcome (different
audiences, different regions).

**Same guardrail as the FOSDEM draft's CNCF section:** this talk should not
claim an existing relationship with CNCF, the Linux Foundation, or the bootc
maintainers beyond "we build on their open-source project." No such
relationship has been verified in this repository as of this draft. Pitching
this talk to Linux Foundation program committees, or pitching a bootc
ecosystem case study to bootc-dev/CNCF channels, is a maintainer decision —
an external, public action on the org's behalf — not something to originate
from this doc.

## Submission checklist

- [ ] Confirm OSS NA 2027 dates, venue, and CFP open/close window from the
      official Linux Foundation event page — **not yet confirmed, do not
      submit against a guessed date**
- [ ] Finalize title + abstract (this draft)
- [ ] Confirm track taxonomy for the year's CFP form (track names vary by
      year; this draft picks the closest analog from recent years)
- [ ] Reuse or re-record the demo video per
      [CFP-DEMO-SCRIPT.md](./CFP-DEMO-SCRIPT.md)
- [ ] Ask 1–2 community members to proof the abstract
- [ ] Submit once the portal opens and track is confirmed
- [ ] (Optional, maintainer call) Coordinate with any FOSDEM submission so the
      two proposals are complementary, not identical, if both are accepted

## Supporting material (for reviewers / talk page)

- Project: [github.com/tuna-os/tunaOS](https://github.com/tuna-os/tunaOS) —
  56 stars, 4 forks (GitHub API, checked at draft time), 64 repos in the org
- Blog: [tunaos.org/blog](https://tunaos.org/blog)
- Tech: bootc (CNCF Sandbox), KubeVirt, QEMU, BuildStream
- ADOPTERS: [tuna-os/tunaOS/ADOPTERS.md](https://github.com/tuna-os/tunaOS/blob/main/ADOPTERS.md) —
  re-check the adopter count before citing it; as of this draft it lists 0
  external production adopters, so lead with the technical architecture, not
  an adoption claim

---

*Draft prepared by the outreach agent. Review, edit, and confirm the actual
CFP dates before submitting.*
