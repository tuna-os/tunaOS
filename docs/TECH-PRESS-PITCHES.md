# Linux Tech-Press Pitch Pack

> Status: **draft** — maintainer review is required before any external
> contact. Tracking issue: [#1534](https://github.com/tuna-os/tunaOS/issues/1534).
> Prepared: 2026-08-14.

This pack is for a maintainer to send through each outlet's current official
editorial or contact channel. It keeps the four pitches short and gives an
editor enough links and facts to decide whether to pursue a longer interview
or review.

## Outlet pitches

### It's FOSS — Gurnard and the Ubuntu/Pantheon angle

**Subject:** Story idea: Pantheon on Ubuntu 24.04 as an atomic desktop image

Hi It's FOSS editors — TunaOS has just shipped **Gurnard**, an experimental
Ubuntu 24.04 LTS image with the Pantheon desktop and bootc's atomic update and
rollback model. It is a timely Ubuntu-family story about taking a familiar,
polished desktop beyond its usual distribution while keeping x86_64 and arm64
images available. We can provide a maintainer interview, screenshots, and
hands-on download links; the announcement is at
<https://tunaos.org/blog/2026/08/12/announcing-gurnard-ubuntu-pantheon>.

### OMG! Linux — a practical Pantheon experiment

**Subject:** Gurnard brings Pantheon to an Ubuntu 24.04 bootc image

Hi OMG! Linux — would you be interested in a short news item or hands-on
look at Gurnard, TunaOS's new Ubuntu 24.04 LTS + Pantheon image? The hook is
practical: readers can try the elementary-style desktop on a standard Ubuntu
LTS base, with image-based updates and rollback, rather than reading about a
new desktop concept. Gurnard is explicitly experimental, and a maintainer can
answer questions or supply a current ISO/image link from
<https://tunaos.org/download>.

### Linux Magazine — immutable desktops for administrators

**Subject:** Feature idea: bootc images across enterprise and community Linux

Hi Linux Magazine editors — TunaOS is building desktop images as bootable OCI
containers, so updates are transactional and the installed system can roll
back instead of being left half-upgraded. A feature could use Gurnard as the
Ubuntu/Pantheon case study, then compare it with the project's Enterprise
Linux and Fedora variants and the operational trade-offs for administrators.
We can provide the variant matrix, reproducible registry references, artifact
verification notes, and a maintainer for a technical interview; background is
at <https://tunaos.org> and in the repository's
[artifact-verification guide](VERIFY-ARTIFACTS.md).

### Phoronix — ARM laptop enablement

**Subject:** TunaOS brings bootc desktops to Apple Silicon and Snapdragon X Elite

Hi Phoronix editors — TunaOS now has two timely ARM laptop stories: M1/M2
Apple Silicon images installed through [bootc-installer-asahi](https://github.com/tuna-os/bootc-installer-asahi),
and Bonito/Dakota support for Snapdragon X Elite, including X13s-class
hardware. The angle is the convergence of hardware enablement and an atomic
desktop update model; we can arrange a maintainer interview, provide the
published technical posts, and clearly identify the early-testing status and
hardware limitations. Sources: [Apple Silicon](https://tunaos.org/blog/2026/08/12/tunaos-on-apple-silicon),
[Snapdragon X Elite](https://tunaos.org/blog/2026/08/12/tunaos-on-snapdragon-x-elite),
and the [hardware table in the README](../README.md#supported-hardware-arm-laptops).

## Media kit

### Canonical links

| Resource | Link | Use |
|---|---|---|
| Project home | <https://tunaos.org> | One-line project context |
| Downloads and ISOs | <https://tunaos.org/download> | Current try-it link; verify before sending |
| Source repository | <https://github.com/tuna-os/tunaOS> | Code, issues, and release context |
| Gurnard announcement | [Announcing Gurnard](https://tunaos.org/blog/2026/08/12/announcing-gurnard-ubuntu-pantheon) | Ubuntu/Pantheon story |
| Apple Silicon announcement | [TunaOS on Apple Silicon](https://tunaos.org/blog/2026/08/12/tunaos-on-apple-silicon) | M1/M2 story |
| Snapdragon announcement | [TunaOS on Snapdragon X Elite](https://tunaos.org/blog/2026/08/12/tunaos-on-snapdragon-x-elite) | ARM laptop story |
| Community | [Matrix #tunaos](https://matrix.to/#/%23tunaos:reilly.asia) | Reader questions and testing |

### At-a-glance facts

| Story | Current fact | Reader action |
|---|---|---|
| Gurnard | Ubuntu 24.04 LTS; Pantheon; experimental; x86_64 + arm64 | Try `ghcr.io/tuna-os/gurnard:base` or `:pantheon`, then check the download page |
| Apple Silicon | M1/M2 Macs; Asahi-based installer; M3+ not yet supported | Read the installer documentation and hardware-specific guidance before testing |
| Snapdragon X Elite | Bonito/Dakota family; X13s-class ARM laptop support; early | Check the hardware matrix and report results in the relevant tracker |
| Common model | bootc images; atomic updates; rollback; signed images and SBOMs | Use the verification instructions before treating an image as trusted |

### Screenshots and technical references

- Existing installer gallery: [docs/INSTALLER-SCREENSHOTS.md](INSTALLER-SCREENSHOTS.md)
  and the PNG assets under [`docs/images/installer/`](images/installer/).
- Apple Silicon hardware safety and test tiers:
  [ASAHI-HARDWARE-TIERS.md](ASAHI-HARDWARE-TIERS.md).
- Variant and architecture overview: [README.md](../README.md).
- Image signatures and SBOM verification: [VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md).
- Existing community-ready technical copy:
  [REDDIT-LEMMY-PLAYBOOK.md](REDDIT-LEMMY-PLAYBOOK.md).

The maintainer should attach or link only screenshots and artifacts that still
match the current release. Do not promise review hardware, publication dates,
or a non-experimental support tier until those details are confirmed.

## Maintainer handoff checklist

- [ ] Confirm the current download page, image tags, ISO availability, and
      architecture claims on the day of outreach.
- [ ] Select one maintainer contact and confirm interview availability,
      preferred timezone, and whether email or Matrix is appropriate.
- [ ] Review each pitch for the outlet's current submission format and send it
      through the official channel; the agent does not contact outlets.
- [ ] Record the date, outlet, pitch angle, contact route, and response in
      issue #1534. Do not add private contact details to the public issue.
- [ ] Follow up once after roughly two weeks unless the outlet requests a
      different cadence.
- [ ] Re-pitch the Gurnard/immutable-desktop angle around Fedora 45 and GNOME
      51 only after those release hooks and relevant artifacts are confirmed.
- [ ] Record any pickup, referral signal, or testing lead in the project's
      adoption/outreach tracking rather than treating a sent pitch as coverage.

No media outlet appears in the current `ADOPTERS.md` ecosystem list, so this
campaign is separate from existing adopter relationships. The maintainer still
owns approval, sending, replies, and any follow-up commitments.
