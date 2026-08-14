# Linux YouTuber Review Kit — Gurnard + ARM variants

> Status: **draft** — for maintainer review before any contact is made.
> Tracking issue: [#1535](https://github.com/tuna-os/tunaOS/issues/1535) (Linux YouTuber review campaign).
> Prepared: 2026-08-14. Rides the Gurnard + Apple Silicon + Snapdragon X Elite
> launch trio published 2026-08-12 (blog posts already live).
>
> **This kit is content only.** Per #1535's own process (step 3), a
> contributor agent does not contact creators directly — a maintainer sends
> the first-contact note using the material below. Nothing in this PR emails,
> DMs, or otherwise reaches out to anyone.

## Why now

- Gurnard + ARM content just published (2026-08-12) — the story is fresh
- Stars are flat at ~55 against a Q4 target of ≥100 (ADOPTION-METRICS.md);
  creator coverage is the single highest-leverage lever to move that
- Chris Titus Tech and DistroTube already cover bootc/atomic desktops
  (Fedora Atomic, Bluefin) — proven audience fit, not a cold pitch
- [ADOPTERS.md](../ADOPTERS.md) cross-check (2026-08-14): no creator is
  listed as an adopter — no conflict with an existing relationship

## Creator ranking

Ranked by bootc/immutable-desktop coverage history, per #1535's proposed
first wave of three:

| Rank | Creator | Fit | Angle |
|---|---|---|---|
| 1 | **DistroTube** | Has covered Bluefin (TunaOS's direct upstream lineage) | "Bluefin's cousin" framing — same bootc model, different desktop/base spread |
| 2 | **Chris Titus Tech** | Has covered Fedora Atomic / bootc desktops | Enterprise-Linux-on-desktop angle (AlmaLinux/CentOS Stream base, RHEL compatibility) |
| 3 | **The Linux Experiment** | Broad distro-review coverage, frequent "new distro" segments | Gurnard's Pantheon-on-Ubuntu-LTS story — a genuinely new combination, not just another bootc image |

**Second wave** (after the first wave lands, per #1535 step 4):

| Creator | Angle |
|---|---|
| Michael Horn | ARM-focused audience — Apple Silicon + Snapdragon X Elite roundup |

## What's different (one-page brief)

Use this as the substance of the first-contact note, or forward as-is.

> TunaOS is an immutable, bootable-container desktop Linux distribution.
> Instead of a package-installed root filesystem, it ships complete desktop
> images as OCI containers and applies them atomically with bootc — same
> technology that runs the datacenter, on the desktop. Updates are
> transactional: one image, one rollback, verified upgrades, no half-upgraded
> system.
>
> Three stories are reviewable and differentiated right now:
>
> - **Gurnard** — the Pantheon desktop (elementary OS's shell) on Ubuntu
>   24.04 LTS, wrapped in the same bootc core as the rest of TunaOS. First
>   widely-buildable way to run Pantheon on a standard Ubuntu LTS base
>   instead of elementary OS itself. x86_64 and arm64.
> - **Apple Silicon** — bootc images for M1/M2 Macs via
>   `bootc-installer-asahi`, a recoveryOS-handoff installer explicitly
>   designed to work beyond TunaOS (Dakota, Bluefin, Bazzite could ride the
>   same installer). A sibling to Asahi Linux, not a replacement — different
>   update model (atomic/rollback) on the same hardware-enablement work.
> - **Snapdragon X Elite** — Bonito/Dakota ARM images for X13s-class
>   Copilot+ PC laptops, same atomic toolchain as everything else.
>
> Base layer is RHEL-compatible (AlmaLinux 10, CentOS Stream 10), so the
> desktop story sits on Enterprise Linux stability. Desktop spread covers
> GNOME, KDE Plasma 6, COSMIC, Niri, XFCE 4.20, and now Pantheon. Apache-2.0,
> weekly release cadence, images are Sigstore-signed with SPDX SBOM
> attestations (verification steps: [docs/VERIFY-ARTIFACTS.md](./VERIFY-ARTIFACTS.md)).

**Honesty on status** (do not oversell — creators notice and it costs
credibility): Gurnard and the ARM images are **early/experimental**, not
"stable." Say so up front. Bug reports from a review are welcome and cheap
to act on right now — that is the actual pitch, not "it's finished."

## Review ISOs

Three images matching #1535's proposed kit — one per differentiated story:

| Variant : flavor | Story | Download |
|---|---|---|
| `gurnard:pantheon` | Pantheon on Ubuntu 24.04 LTS | `https://download.tunaos.org/live-isos/gurnard-pantheon-latest.iso` |
| `bonito:niri` | Scrollable-tiling desktop, Fedora base, Snapdragon X Elite ARM build | `https://download.tunaos.org/live-isos/bonito-niri-latest.iso` |
| `yellowfin:gnome` | GNOME baseline for a straight bootc-vs-traditional comparison | `https://download.tunaos.org/live-isos/yellowfin-gnome-latest.iso` |

Each `<name>-latest.iso` has matching sidecars at the same path:
`<name>-latest.iso.sha256` and `<name>-latest.iso.sigstore.json` (Cosign
bundle) — this is the standard publish-pipeline layout
(`.github/workflows/publish-iso-groups.yml`), not a one-off for this kit.

> **Verification note**: these URLs are derived directly from the R2 upload
> path the publish pipeline writes to (`live-isos/<basename>-latest.iso` on
> `download.tunaos.org`, same convention the weekly desktop-screenshots job
> uses for its own R2 keys). They were not fetched live from this sandbox
> (no outbound network access here) — a maintainer should do one `curl -I`
> per link before sending anything to a creator, and swap in the general
> **[tunaos.org/download](https://tunaos.org/download)** page as a fallback
> if any individual link has gone stale.

### Verify a download

```bash
curl -LO https://download.tunaos.org/live-isos/gurnard-pantheon-latest.iso
curl -LO https://download.tunaos.org/live-isos/gurnard-pantheon-latest.iso.sha256
sha256sum -c gurnard-pantheon-latest.iso.sha256
```

For a full signature/SBOM check instead of just the checksum, see
[docs/VERIFY-ARTIFACTS.md](./VERIFY-ARTIFACTS.md) (Cosign keyless
verification against the GitHub Actions build identity — no project signing
key needed).

## Hardware notes: what to test on ARM vs x86

- **x86_64** (Gurnard, Bonito, Yellowfin all have x86_64 builds): standard
  VM or bare-metal review, no special hardware caveats.
- **Apple Silicon (M1/M2)**: install path is the `bootc-installer-asahi`
  recoveryOS handoff, **not** a standard ISO boot — flag this explicitly so
  a reviewer doesn't try to boot the Mac from a USB ISO and conclude it's
  broken. Hardware-testing reports on real Macs are the most valuable
  contribution right now; point creators at
  [tuna-os/bootc-installer-asahi](https://github.com/tuna-os/bootc-installer-asahi)
  issues for the current hardware-support matrix.
- **Snapdragon X Elite (X13s-class)**: Bonito/Dakota ARM build. Early stage —
  set expectations that this is a "does it boot and run atomically" review,
  not a polished daily-driver claim yet.
- General: all images are Sigstore-signed; a reviewer who wants to show a
  supply-chain angle on camera can run the verification steps above live.

## Process (per #1535)

1. **This PR**: the review kit content above — creator ranking, one-page
   brief, ISO links + checksum steps, hardware notes. No file changes
   outside `docs/`.
2. A maintainer reviews this kit and sends the first-contact note to
   DistroTube, Chris Titus Tech, and The Linux Experiment (in ranked order
   or in parallel — maintainer's call). **No agent contacts creators.**
3. Track replies directly on tuna-os/tunaos#1535 (comments), not in this
   file — this file is the static kit, not a running log.
4. After the first wave lands, follow up with the ARM story to Michael Horn
   per #1535 step 4.
5. Log any resulting star/download delta in the next
   [ADOPTION-METRICS.md](../ADOPTION-METRICS.md) monthly snapshot, same as
   the Reddit/Lemmy playbook's post-and-track step
   ([docs/REDDIT-LEMMY-PLAYBOOK.md](./REDDIT-LEMMY-PLAYBOOK.md)).
