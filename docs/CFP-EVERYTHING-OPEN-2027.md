# Everything Open 2027 — CFP Draft

> **Status: draft for maintainer review and submission.**
>
> | | |
> |---|---|
> | Event | Everything Open 2027, 20–22 January 2027, QUT Gardens Point, Meanjin / Brisbane |
> | Theme | Building the Future Together |
> | CFP deadline | **11:59pm, 6 September 2026, Anywhere on Earth** |
> | Format | 20- or 45-minute talk |
>
> Dates and formats verified against the
> [official proposal page](https://2027.everythingopen.au/programme/proposals/)
> on 2026-08-22. Tracking issue:
> [#1974](https://github.com/tuna-os/tunaOS/issues/1974).

## Talk title

**One image factory, five package managers: building bootable Linux desktops
across distributions**

## Suggested format

**20-minute talk.** The proposal focuses on engineering lessons and a compact
recorded demonstration. A 45-minute version could add a live matrix walkthrough
and a deeper comparison of the package-manager adapters.

## Abstract

Building one bootable-container desktop is straightforward. Building the same
desktop contract across AlmaLinux, Fedora, Debian, Ubuntu, Arch, openSUSE, and
Gentoo exposes every assumption hidden in a conventional distribution build.

TunaOS is an open-source image factory for bootc desktops. A manifest-driven
pipeline combines Linux bases, desktop environments, kernels, and hardware
layers into signed OCI images that boot as complete operating systems. The
same desktop manifest has to cross dnf, apt, pacman, zypper, and portage while
preserving atomic upgrades, rollback, and a testable image contract.

This talk presents the failures that shaped that pipeline: separating package
intent from package-manager syntax, resolving flavors without multiplying
build scripts, scheduling a dependency-aware image matrix, and deriving public
health status from CI instead of maintaining it by hand. A short demonstration
shows an OCI desktop image being inspected, staged as an atomic upgrade, and
rolled back to its previous digest.

Attendees leave with reusable patterns for cross-distribution image builds,
honest boundaries for what can be normalized, and a practical approach to
making build health visible. This is an engineering case study from an early
project, not an adoption claim or vendor pitch.

## Outline

1. **The contract (2 min):** a desktop is a signed OCI image that can upgrade
   atomically and roll back.
2. **Where abstraction breaks (5 min):** package names, repositories, service
   defaults, and filesystem expectations across five package managers.
3. **Manifest-driven assembly (5 min):** desktop intent in YAML, OS-family
   adapters, and flavor resolution.
4. **Matrix as dependency graph (4 min):** staged builds, shared layers, and
   generated health evidence.
5. **Recorded demo (3 min):** inspect, upgrade, and roll back one image.
6. **Lessons and questions (1 min).**

## Reviewer-facing evidence

- Architecture and contributor guide:
  [docs/AGENT_GUIDE.md](./AGENT_GUIDE.md)
- Generated matrix status: [docs/MATRIX-STATUS.md](./MATRIX-STATUS.md)
- Demo recording runbook: [docs/CFP-DEMO-SCRIPT.md](./CFP-DEMO-SCRIPT.md)
- Source repository: [github.com/tuna-os/tunaOS](https://github.com/tuna-os/tunaOS)

The public matrix is active evidence, not a promise that every cell is green.
Re-check it on submission day and avoid quoting a hand-copied cell count.

## Honesty and scope

- `ADOPTERS.md` lists zero external adopters as of 2026-08-22. Describe TunaOS
  as an engineering case study, not a proven enterprise deployment.
- Upstream projects and Linux distributions in `ADOPTERS.md` are dependencies,
  not partners or users.
- Do not claim reproducibility until the recorded demo run has produced the
  image digest and successful rollback evidence.
- A maintainer or maintainer-designate owns the external submission and travel
  decision. Outreach agents do not submit CFPs or contact organizers.

## Submission checklist

- [ ] Confirm a speaker who can attend in Brisbane, 20–22 January 2027.
- [ ] Re-check deadline, format, and portal status on the official proposal
      page.
- [ ] Choose the 20- or 45-minute format and trim or expand the outline.
- [ ] Run [CFP-DEMO-SCRIPT.md](./CFP-DEMO-SCRIPT.md); record real digest and
      rollback evidence.
- [ ] Re-check architecture claims against current `main` and generated matrix
      status.
- [ ] Ask one technical reviewer to proof the abstract.
- [ ] Submit before **6 September 2026 at 11:59pm AoE**.

---

*Draft prepared by outreach agent (ACMM L6 — full mode). Human review and
submission required.*
