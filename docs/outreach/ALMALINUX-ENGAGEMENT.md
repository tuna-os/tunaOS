# AlmaLinux Community Engagement & Atomic SIG Showcase Playbook

> Status: **draft** — for maintainer review. Do **not** post externally without
> maintainer sign-off.  
> Tracker: [#1757](https://github.com/tuna-os/tunaOS/issues/1757).  
> Fact-checked 2026-08-30 against `README.md`, `ROADMAP.md`, and `ADOPTERS.md`
> per the maintainer's press-claim guard ([#1667](https://github.com/tuna-os/tunaOS/issues/1667)).

---

## 1. Context & Strategic Alignment

TunaOS builds its flagship variants directly on AlmaLinux:
- **Albacore:** Enterprise Linux desktop on **AlmaLinux 10 / RHEL 10** (GNOME, KDE Plasma, COSMIC, Niri flavors; x86_64 and arm64).
- **Yellowfin:** Next-generation enterprise desktop with **AlmaLinux Kitten 10** as its base (it tracks CentOS Stream 10).

AlmaLinux maintains an active **Atomic SIG** that works to advance container-native, image-mode `bootc` systems. The SIG already has good representation for server and edge deployments. TunaOS provides the missing showcase: a complete, daily-rebuilt, daily-tested immutable workstation and desktop built on AlmaLinux 10.

---

## 2. Community Outreach Pillars

```mermaid
graph TD
    A["AlmaLinux Community Outreach"] --> B["Pillar 1: Discourse Intro Post"]
    A --> C["Pillar 2: Atomic SIG Integration"]
    A --> D["Pillar 3: Community Call Lightning Talk"]
```

### Pillar 1: AlmaLinux Discourse Post (`lists.almalinux.org` / Forum)
**Goal:** Introduce TunaOS to the wider AlmaLinux user and sysadmin community.

**Draft Post Copy:**
````markdown
**Title:** TunaOS: A Container-Native Immutable Desktop on AlmaLinux 10

Hello AlmaLinux Community,

We are excited to introduce **TunaOS**, an open-source, image-based desktop distribution built directly on AlmaLinux 10 and AlmaLinux Kitten 10.

### Why an Immutable Desktop on Enterprise Linux?
Enterprise Linux is renowned for decade-long stability, robust server performance, and hardware reliability. However, workstation users often struggle with the balance between platform stability and access to modern desktop environments and zero-maintenance updates.

TunaOS solves this by packaging the entire desktop as a bootable OCI container via `bootc`:
- **Albacore:** AlmaLinux 10 (RHEL 10 base) with GNOME, KDE Plasma, COSMIC, and Niri desktop environments.
- **Yellowfin:** AlmaLinux Kitten 10 with bleeding-edge upstream desktop backports.
- **Atomic Reliability:** System updates are single transactional image downloads. Instant `bootc rollback` guarantees a known good system if anything goes wrong.
- **Keyless Supply Chain:** Every image build is signed with Sigstore/cosign keyless signatures and verifiable SBOMs.

### Try Albacore GNOME:
```bash
bootc switch ghcr.io/tuna-os/albacore:gnome
```

We would love to collaborate closely with the AlmaLinux community and gather your feedback!

- GitHub Repository: https://github.com/tuna-os/tunaOS
- Docs & Guides: https://tunaos.org
````

---

### Pillar 2: AlmaLinux Atomic SIG Collaboration
**Goal:** Position TunaOS as a flagship reference implementation for the Atomic SIG.

- **Action Items:**
  1. Join the official communication channel of the Atomic SIG (`chat.almalinux.org/almalinux/channels/sigatomic`).
  2. Share TunaOS's Containerfile patterns, workflows for DDI smoke tests, and lessons from custom initramfs generation.
  3. Offer TunaOS as an upstream-adjacent testbed to test `bootc`, `composefs`, and keyless container validation on EL10.

---

### Pillar 3: Monthly Community Call Lightning Talk
**Goal:** Deliver a 10-minute presentation and live demo at an AlmaLinux Community Call.

**Talk Outline (10 Minutes):**
1. **Introduction (2 min):** The evolution of image-based desktops and why AlmaLinux 10 is the ideal foundation.
2. **Architecture (3 min):** Bootc container lifecycle, image layers, and immutable `/usr`.
3. **Live Demo (3 min):**
   - Boot Albacore GNOME on AlmaLinux 10.
   - Do a transactional `bootc upgrade`.
   - Show instant reboot rollback (`bootc rollback`).
4. **Q&A and Call for Contributors (2 min):** Ways to connect through GitHub Discussions and Matrix.

---

## 3. Governance & Fact-Check Guardrails (per #1667)

- **Relationship Integrity:** AlmaLinux is TunaOS's upstream base dependency. Do not claim a formal partnership between the organizations or commercial endorsement from the AlmaLinux OS Foundation unless officially formalized.
- **Sign-Off:** Review post copy with project maintainers before you publish on Discourse or join the community call.
- **Logging:** Update `docs/ADOPTION-OUTREACH-STATUS.md` with thread URLs and notes from SIG meetings.
