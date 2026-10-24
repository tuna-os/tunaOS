# Linux Plumbers Conference — CFP Proposal

| Field | Value |
|---|---|
| Status | Draft for maintainer review. Do not submit without maintainer and speaker sign-off. |
| Target event | Next announced Linux Plumbers Conference (LPC 2027). Both LPC 2025 and LPC 2026 have ended. |
| CFP status | Not announced as of 2026-10-24. No 2027 dates, city, track list, or portal deadlines are public. |
| Tracking | [#3299](https://github.com/tuna-os/tunaOS/issues/3299) (see also closed [#2754](https://github.com/tuna-os/tunaOS/issues/2754)) |

## Timeline and CFP research record (2026-10-24)

Issue [#3299](https://github.com/tuna-os/tunaOS/issues/3299) targets LPC 2025 with a September 2025 estimate in Portland and a January 2025 deadline. Official records from the organizer show that both the 2025 and 2026 editions have already ended.

| Edition | Official dates and venue | CFP history | Status on 2026-10-24 |
|---|---|---|---|
| [LPC 2025](https://lpc.events/event/19/) | December 11–13, 2025 at Toranomon Hills Forum in Tokyo, Japan | [CFP](https://lpc.events/event/19/abstracts/) opened May 15, 2025. Refereed Track and Kernel Summit proposals closed September 10, 2025 at 23:59 UTC (notifications September 28, 2025). | Past event |
| [LPC 2026](https://lpc.events/event/20/) | October 5–7, 2026 at the Prague Congress Centre in Prague, Czechia | [CFP](https://lpc.events/event/20/abstracts/) opened March 9, 2026. Microconference proposals closed April 23, 2026. Refereed Track and Kernel Summit proposals closed June 28, 2026 at 23:59 UTC (notifications July 14, 2026). Microconference subtopics closed August 7, 2026 at 23:59 UTC (July 10 for preregistration). | Past event |
| LPC 2027 | Not announced on [lpc.events](https://lpc.events/) or the [Linux Foundation page](https://events.linuxfoundation.org/linux-plumbers-conference/) | `/event/21/` returns HTTP 404. No 2027 CFP dates or tracks are public yet. | Hold this draft for the 2027 call |

### LPC format and review rules

The [2026 CFP](https://lpc.events/event/20/abstracts/) sets three rules that differ from `#3299`:

1. **Session length:** Refereed Track talks are **45 minutes in total (talk plus questions)**, not 45–60 minutes plus 15 minutes.
2. **Problem focus:** LPC wants problem statements, proposals, or proof-of-concept work that need live debate among developers of Linux system software. It does not want a product tour of finished work.
3. **Microconferences and attendance:** The committee can send strong Refereed entries that miss the cut to a suitable Microconference. A speaker can also send a short subtopic to an accepted [Microconference](https://lpc.events/event/20/page/269-microconferences) (`System Boot and Security`, `Containers and checkpoint/restore`, `Build Systems`, or `Live Update`). Presenters and subtopic leads must attend in person except in an emergency.

---

## Repository architecture and claim rules

Keep four boundaries from this repository intact when you adapt the proposal:

| Area | Issue `#3299` draft | Repository reality and rule |
|---|---|---|
| Build engine and `BuildStream` | Implies that `BuildStream` builds the multi-variant matrix | `tuna-os/tunaos` builds its OS matrix from `Containerfile.*`, [`scripts/resolve-flavor.sh`](../scripts/resolve-flavor.sh), and [`build_scripts/desktop/install-desktop.sh`](../build_scripts/desktop/install-desktop.sh), which reads YAML manifests in `manifests/desktops/` generated from [`tunaos.toml`](../tunaos.toml). Only the two separate sibling repositories—[`tuna-os/tromso`](https://github.com/tuna-os/tromso) (KDE Plasma 6) and [`tuna-os/xfce-linux`](https://github.com/tuna-os/xfce-linux) (XFCE Wayland), listed under `[[sibling_images]]` in `tunaos.toml`—use `BuildStream` on `freedesktop-sdk`. |
| Package sources and COPR | Lists COPR as part of the build infrastructure | [`PACKAGE-SOURCING.md`](../PACKAGE-SOURCING.md) (#1319) puts base system repositories first and in-org builds second, including digest-pinned OCI package bundles in [`image-versions.yaml`](../image-versions.yaml) (`ghcr.io/tuna-os/tunaos-packages:gnome50-el10-x86_64`, `ghcr.io/projectbluefin/utah-packages`). Ad-hoc COPRs and PPAs are policy gaps under migration. |
| Reproducibility | Claims reproducible builds | `image-versions.yaml` pins base images and package bundles by digest, and `tunaos.toml` declares the matrix, while `Containerfile.*` runs `dnf`, `apt`, `pacman`, `zypper`, and `portage`. Call the builds digest-pinned and configuration-driven, not bit-for-bit reproducible. |
| Matrix scope and readiness | Claims 10 variants, 6+ desktops, and upstream integration | `tunaos.toml` defines 14 CI variants plus local-build `redfin` ([`rhel-setup.md`](rhel-setup.md)) across six desktop families (`gnome`, `kde`, `cosmic`, `niri`, `xfce`, and `pantheon` on `gurnard`). Per [`HUMMINGBIRD.md`](HUMMINGBIRD.md), `hummingbird` ships no desktop by design except its `utah-packages` GNOME path. Cite [`GREEN-CRITERIA.md`](GREEN-CRITERIA.md), [`MATRIX-STATUS.md`](MATRIX-STATUS.md), and [`ADOPTERS.md`](../ADOPTERS.md) without claiming external enterprise deployments. |

---

## Option A: Refereed Track proposal (45 minutes in total)

### Working title

**Desktop Systems in Bootable Containers: Cross-Distro Assembly, Session Contracts, and Rollback Boundaries**

Alternative title (with the sibling comparison): **Two Paths to a `bootc` Desktop: Package-Manager Matrices and `freedesktop-sdk` Siblings**.

### Abstract

Teams now ship Linux servers as bootable OCI containers (`bootc`). When you apply that model to a graphical workstation across distribution families, new boundary problems appear. Container builds, init and login services, and runtime verification checks do not share one contract.

This talk uses TunaOS, an open-source image factory for `bootc` desktops, to show where image-based desktop abstractions hold and where they break. One primary configuration (`tunaos.toml`), a flavor resolver (`scripts/resolve-flavor.sh`), and a desktop installer (`build_scripts/desktop/install-desktop.sh`) build desktops across `dnf`, `apt`, `pacman`, `zypper`, and `portage` bases. Two separate sibling repositories (`tromso` and `xfce-linux`) build `bootc` desktops on `freedesktop-sdk` with `BuildStream`. To replace mutable third-party repositories, CI builds desktop stacks such as GNOME on EL10 and Hummingbird as OCI package bundles and mounts them by digest.

An image that builds is not yet a desktop that works. We trace real failures where the OCI build succeeded but the booted session failed. Examples include uncompiled schemas for GLib, wrong autologin defaults in the display manager, `graphical.target` checks that waited on their own transaction, and live-ISO checks without `sshd` (`scripts/iso-e2e.sh --published`). We close with concrete design questions for `bootc`, `systemd`, distribution, and desktop maintainers about state across `/usr`, `/etc`, and `/var`, OCI package mounts, and graphical boot gates.

### Timed 45-minute outline (35 minutes of talk plus 10 minutes of questions)

| Segment | Time | Focus and repository evidence |
|---|---|---|
| 1. Problem statement and state boundaries | 5 min | What `bootc` updates in `/usr` versus what stays in `/etc`, `/var`, firmware, and user home directories during `bootc upgrade` and `bootc rollback`. |
| 2. Cross-distro assembly and OCI package bundles | 8 min | How `tunaos.toml`, `scripts/resolve-flavor.sh`, and `build_scripts/desktop/install-desktop.sh` assemble desktops across five package managers, how digest-pinned OCI package mounts (`image-versions.yaml`) replace ad-hoc COPRs, and how that compares with the separate `freedesktop-sdk` `BuildStream` siblings (`tromso`, `xfce-linux`). |
| 3. Where build success and session readiness diverge | 8 min | Measured defects from [`AGENTS.md`](../AGENTS.md) and [`ci-troubleshooting.md`](ci-troubleshooting.md): last-writer overrides in `90-image-info.sh`, uncompiled GLib schemas, and silent display-manager defaults in `customize-live.sh`. |
| 4. Session and live-media checks without SSH | 9 min | Why a unit inside `graphical.target` cannot wait for its own transaction, and how `scripts/iso-e2e.sh --published` checks production live ISOs (where `40-services.sh` disables `sshd`) through QEMU `sendkey`, `screendump`, and OCR. |
| 5. Recorded or live `bootc` update and rollback | 5 min | Stage an update, show both deployments in `bootc status`, reboot, and roll back to the prior digest with [`CFP-DEMO-SCRIPT.md`](CFP-DEMO-SCRIPT.md). |
| 6. System discussion and questions | 10 min | Debate open questions with `bootc`, `systemd`, distribution, and desktop maintainers. |

---

## Option B: Microconference subtopic proposal (15–25 minutes)

Use this short format for a direct subtopic submission after LPC posts the annual Microconference list, or if the committee forwards the Refereed proposal.

- **Candidate Microconferences:** *System Boot and Security*, *Containers and checkpoint/restore*, *Build Systems*, or *Live Update* (confirm against the 2027 list).
- **Proposed title:** **Desktop Session Contracts and State Boundaries in `bootc` Images**

### Problem statement and discussion prompts

1. **Rollback state boundaries:** A `bootc` rollback reverts `/usr`, while `/etc` merges and `/var` stays in place. What rules or tools should distributions use when desktop schemas, user state, or display-manager config drift across a rollback?
2. **OCI package mounts by digest:** A `podman build` can mount an OCI package bundle by digest instead of a mutable third-party repo. How should build tools and `bootc` record provenance for those multi-stage mounts?
3. **Graphical boot gates without `sshd`:** Published images for desktops disable `sshd`, and a oneshot unit inside `graphical.target` cannot wait for `graphical.target` to become `active`. What standard `systemd` or compositor readiness signals should VM and live-ISO checks read instead?
4. **Package matrices and `BuildStream` siblings:** When does a `Containerfile` adapter work better than a `freedesktop-sdk` `BuildStream` tree? When is a separate `BuildStream` image cleaner?

---

## Speaker bio template and consent rules

James Reilly (`@hanthor`, listed in [`MAINTAINERS.md`](../MAINTAINERS.md)) or a willing contributor who worked on the build pipeline, desktop manifests, or verification gates can lead this session.

- Do not submit any person's name, bio, or contact details without explicit consent in [#3299](https://github.com/tuna-os/tunaOS/issues/3299).
- Do not infer speaker availability or travel approval from commit history.
- Do not list upstream `bootc`, `systemd`, `BuildStream`, distribution, or desktop maintainers as co-speakers without their explicit consent.

### Reusable speaker bio template

> `[Speaker Name]` works on `[verified area, such as the manifest-driven build pipeline or bootc verification gates]` in TunaOS, an open-source image factory for bootable container desktops across Enterprise Linux, Fedora, Debian, Ubuntu, Arch, openSUSE, and Gentoo bases (`github.com/tuna-os/tunaOS`). Their work includes `[linked PR or subsystem]`. This session shares engineering lessons and open system questions from `bootc` desktop builds and verification gates.

---

## Submission handoff checklist and issue ledger

An authorized speaker or maintainer must complete these steps after LPC announces the next edition:

- [ ] Check [lpc.events](https://lpc.events/) and the [Linux Foundation page](https://events.linuxfoundation.org/linux-plumbers-conference/) for the 2027 dates, city, Indico URL, Refereed deadline, and Microconferences.
- [ ] Record speaker consent in [#3299](https://github.com/tuna-os/tunaOS/issues/3299) and confirm in-person travel and budget before you submit.
- [ ] Select Option A (45-minute Refereed Track), Option B (Microconference subtopic), or both under the 2027 CFP rules.
- [ ] Check all claims against [`CONTENT-CLAIM-CHECKLIST.md`](CONTENT-CLAIM-CHECKLIST.md), [`MATRIX-STATUS.md`](MATRIX-STATUS.md), [`PACKAGE-SOURCING.md`](../PACKAGE-SOURCING.md), and [`ADOPTERS.md`](../ADOPTERS.md) on the day you submit.
- [ ] Run the dry run in [`CFP-DEMO-SCRIPT.md`](CFP-DEMO-SCRIPT.md) on a VM if you include the 5-minute `bootc` update and rollback demo.
- [ ] Submit through the speaker's Indico account on `lpc.events` and record the public-safe receipt in `#3299`.

Copy this ledger block into [#3299](https://github.com/tuna-os/tunaOS/issues/3299) when you update status:

```text
Event / Indico CFP URL:
Event dates and location:
Refereed / Microconference deadline and time zone (checked YYYY-MM-DD):
Proposal track and option (Refereed 45-min | Microconference subtopic):
Confirmed speaker(s) and consent comment link:
In-person attendance and travel decision:
State: waiting-for-2027-cfp | preparing | submitted | forwarded-to-mc | accepted | declined | withdrawn
Submission date and public-safe Indico contribution ID:
Accepted session URL and schedule slot:
Slides, demo artifact digest, and post-event notes:
```
