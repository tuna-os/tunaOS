# Linux Podcast Tour Strategy & Pitch Kit

> Status: **draft** — for maintainer review. Do **not** send external pitches without
> maintainer sign-off.  
> Tracking: [#1758](https://github.com/tuna-os/tunaOS/issues/1758).  
> Supports: [#1534](https://github.com/tuna-os/tunaOS/issues/1534) (Tech Press),
> [#1646](https://github.com/tuna-os/tunaOS/issues/1646) ([PRESSKIT.md](../PRESSKIT.md)).  
> Fact-checked 2026-08-30 against `ROADMAP.md` and `PRESSKIT.md` per [#1667](https://github.com/tuna-os/tunaOS/issues/1667).

---

## 1. Outreach Purpose & Channel Advantage

While written tech press and YouTube review hardware kits require extensive preparation and logistics, **Linux podcasts** represent the highest-trust, most authentic channel for reaching experienced Linux power users, developers, sysadmins, and homelabbers.

A 15-minute maintainer interview or segment discussion provides the nuance required to explain container-native (`bootc`) desktops, Enterprise Linux lifecycles, and atomic rollback workflows.

---

## 2. Target Podcast Matrix & Segment Fit

| Podcast | Host(s) / Network | Audience Profile | Recommended Pitch Angle |
|---|---|---|---|
| **Destination Linux** | Michael, Ryan, Jill (TuxDigital) | Desktop Linux users, gamers, open-source enthusiasts | "The future of immutable desktops: How bootc makes desktop Linux unbreakable." Focus on daily usability, gaming, and multiple desktop environments. |
| **Late Night Linux** | Joe, Félim, Will, Mike | Pragmatic developers, sysadmins, open-source realists | "Enterprise Linux stability with modern desktops." Candid discussion on EL10 backports, container immutability, and fork architecture. |
| **Linux Unplugged** | Chris Fisher, Wes Payne (Jupiter Broadcasting) | Power users, homelabbers, Nix/Atomic/bootc enthusiasts | Deep technical dive: OCI container layering, DDI smoke testing, Sigstore keyless supply chain security, and ARM/Snapdragon developments. |
| **This Week in Linux** | Michael Tunnell (TuxDigital) | Linux news followers & distro watchers | News hook: "TunaOS ships GNOME 51 backports on Enterprise Linux 10 and expands multi-distro bootc matrix." |
| **Linux Action News** | Jupiter Broadcasting | Industry and open-source news listeners | Concise news brief pitch on bootc adoption across desktop distributions and release milestones. |

---

## 3. Standard Show Pitch Template

**Subject:** Segment idea / Interview pitch: How TunaOS brings container-native bootc desktops to Enterprise Linux

```text
Hi [Host Name / Show Team],

I've been a longtime listener of [Show Name] and appreciate your coverage of [recent topic / segment relevant to the show].

I wanted to share a story that fits right into your ongoing discussions around immutable Linux and desktop reliability: TunaOS (https://github.com/tuna-os/tunaOS).

In brief:
Servers run on decade-long enterprise lifecycles; desktops move at six-month release cadences. TunaOS bridges that gap by packaging complete desktop environments as bootable, container-native OCI images using bootc. 

Why your listeners will find this compelling:
1. Enterprise Base + Modern Desktop: Albacore & Yellowfin ship modern GNOME, KDE, COSMIC, and Niri directly on top of AlmaLinux 10 / RHEL 10.
2. Unbreakable Updates & Rollback: System upgrades are single atomic image pulls. If an update causes an issue, `bootc rollback` instantly restores the previous working state.
3. Modern Supply Chain: Every image is signed keylessly using Sigstore/cosign with verifiable SBOMs.
4. Multi-Distro & Architecture: Beyond EL10, TunaOS builds images across Fedora (Bonito), Arch/CachyOS (Marlin), and Ubuntu LTS (Gurnard), alongside experimental ARM Snapdragon X Elite builds.

I've attached our one-page Press Kit ([docs/PRESSKIT.md]) with full technical specs and variant lifecycle tables.

Would you be open to a short 15-minute maintainer interview or segment discussion on where container-native desktops are headed?

Best regards,

[Maintainer Name]
TunaOS Project Maintainer
https://github.com/tuna-os/tunaOS
```

---

## 4. Key Interview Talking Points

- **The Problem:** The traditional package manager dilemma (`dnf`/`apt`/`pacman` roulette vs. stale software).
- **The Solution:** OCI container-native system architecture via `bootc` (CNCF sandbox project).
- **Supply Chain Security:** Eliminating static GPG keys in favor of Sigstore/cosign keyless verification.
- **Hardware Diversity:** Supporting modern x86-64 hardware, vintage legacy laptops (e-waste revival), and experimental ARM platforms (Snapdragon X Elite).
- **Honest Status:** Highlighting stable GA lines (Albacore/Yellowfin) while being candid about beta/experimental variants (Marlin, Gurnard, Apple Silicon).

---

## 5. Execution & Tracking

1. **Review:** All outgoing pitches must receive maintainer sign-off.
2. **Pacing:** Send pitches in small batches (1–2 per week) to ensure prompt responses and calendar coordination.
3. **Record Keeping:** Track pitch dates, host responses, scheduled recording dates, and published episode links in `docs/ADOPTION-OUTREACH-STATUS.md`.
