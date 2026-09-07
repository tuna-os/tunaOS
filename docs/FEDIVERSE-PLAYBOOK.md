# Mastodon / Fediverse Playbook

> Status: **draft** — for maintainer review before account registration or first toot.
> Tracking issue: [#1634](https://github.com/tuna-os/tunaOS/issues/1634) (Mastodon/Fediverse presence).
> Prepared: 2026-08-14. First toot targets: Q3 checkpoint recap (08-22) / GNOME 51 release week (~09-12).

## Why this exists

Stars are flat (~55) and the Q4 target is ≥100 ([ADOPTION-METRICS.md](../ADOPTION-METRICS.md)). The
immutable-desktop conversation (ublue/Bluefin/Bazzite ecosystem) has a
disproportionately strong Fediverse presence — distro maintainers, bootc
contributors, and the r/linux-adjacent crowd overlap heavily with
fosstodon.org and linux.social. Today TunaOS has **zero** Fediverse
presence, and it is the cheapest channel to operate: no algorithm, no
self-promotion rules beyond the instance's, and a release is a 1-toot
operation.

This playbook makes Fediverse posting a copy-paste operation, like the
[Reddit/Lemmy playbook](REDDIT-LEMMY-PLAYBOOK.md).

## Rules of engagement

- **One human account**, clearly the maintainer (e.g. `@tunaos@fosstodon.org`)
  — no bots, no astroturf, no engagement bait
- **Max ~4-6 toots/month** — releases, milestone posts, GFI calls; no noise
- **Toot links point at tunaos.org first** (blog post or download), GitHub
  second; hashtags: `#Linux #ImmutableLinux #bootc` + variant-specific
  (`#GNOME`, `#Fedora`, `#AsahiLinux`, `#Pantheon`)
- **Reply and boost** — engage honestly in comments; boost community
  milestones and related projects (Asahi, elementary, bootc-dev)
- **Image alt-text always** — screenshots get alt text (accessibility is a
  Linux-community norm on the Fediverse)

## When to post (candidate hooks)

| Hook | Date | Toot angle |
|---|---|---|
| Q3 checkpoint recap | 08-22 | Milestones, variants, GFI pool, honest numbers |
| GNOME 51 release week | ~09-12 | GNOME 51 on EL10 before upstream |
| Hacktoberfest | 10-01 | Curated starter-task pool, DCO-signed |
| Fedora 45 | ~10-20 | Bonito on Fedora 45, bootc desktop story |
| Gurnard / ARM follow-ups | as blog posts publish | Every blog publish → RSS→toot pattern |

## Toot template

```
[1-line what] — [1-line why it matters] + [hook]

Bullet 1
Bullet 2
Bullet 3

🔗 https://tunaos.org/blog/<slug> (or /download)
#Linux #ImmutableLinux #bootc #<topic>

Alt: <image description> (when attaching a screenshot)
```

## Ready-to-post toots

### Toot 1 — Q3 checkpoint recap (08-22)

> TunaOS Q3 checkpoint: the catalog is now a genuinely multi-desktop,
> multi-base line — Gurnard (Ubuntu 24.04 LTS + Pantheon), Hummingbird
> (container-native Fedora), plus GNOME/KDE/COSMIC/Niri/XFCE on Enterprise
> Linux lifecycles. Every variant is an atomic, rollback-safe bootc image.
>
> Honest numbers: ~55 GitHub stars (flat — growth is a Q4 focus), 34+
> outreach opportunities filed, and a good-first-issue pool growing to 8
> tasks ahead of Hacktoberfest. We also corrected an early "first external
> contributor" claim that turned out to be an agent misattribution — that
> gap is exactly why the starter-task backlog exists.
>
> Full recap: https://tunaos.org/blog/2026/08/22/q3-2026-community-checkpoint
> #Linux #ImmutableLinux #bootc
>
> Alt: TunaOS Q3 checkpoint banner.

### Toot 2 — GNOME 51 on EL10 (release week, ~09-12)

> GNOME 51 ships September 12 — and TunaOS is packaging it for Enterprise
> Linux *before* the upstream release lands. Albacore and Yellowfin GNOME
> variants pick up GNOME 51 on the upstream schedule instead of waiting
> for an EL point release.
>
> The gnome-51 tier covers the full stack: gnome-shell, mutter, gtk4,
> libadwaita, nautilus, gdm, orca, ptyxis — built through the same mock-
> based, distributed tier workflow that carried GNOME 49/50.
>
> Test it: https://tunaos.org/blog/2026/09/12/gnome-51-coming-to-tunaos
> #Linux #GNOME #EL10 #AlmaLinux #CentOSStream #bootc

### Toot 3 — Hacktoberfest 2026 (10-01)

> Hacktoberfest is back — TunaOS is participating with a curated pool of
> starter tasks. Mostly docs, testing, and small polish work; sized so a
> first-time contributor can finish one in an evening. No prior bootc or
> Rust experience needed.
>
> 1. Pick a task from the good-first-issue pool
> 2. Comment to claim it
> 3. Open a PR, DCO-signed (git commit -s)
> 4. Maintainers review quickly; merged PRs count toward your goal
>
> Pool: https://github.com/tuna-os/tunaOS/labels/good%20first%20issue
> #Hacktoberfest #OpenSource #Linux #bootc

### Toot 4 — Fedora 45 / Bonito (~10-20)

> Bonito — TunaOS's Fedora-based variant — tracks the Fedora 45 cycle:
> atomic bootc images, verified upgrades, rollback, on the Fedora schedule.
> Enterprise Linux lifecycles for servers; current desktops for people.
>
> Try the beta: https://tunaos.org/download
> #Fedora #Fedora45 #Linux #ImmutableLinux #bootc

### Toot 5 — Gurnard (Pantheon) spotlight

> Gurnard: TunaOS on Ubuntu 24.04 LTS with the Pantheon desktop — the
> elementary-OS experience, as an atomic bootc image. Immutable updates +
> Pantheon's clean GNOME-based shell.
>
> https://tunaos.org/blog/2026/08/12/announcing-gurnard-ubuntu-pantheon
> #Linux #Pantheon #elementaryOS #bootc #Ubuntu

### Toot 6 — Apple Silicon (M1/M2) — experimental preview

> Apple Silicon support is an **experimental engineering preview**: the
> bootc-installer-asahi installer ships kernel + glue for M1/M2 (built to
> work beyond TunaOS — Dakota, Bluefin, Bazzite could all ride it), but
> boot payloads are still pending, so it is not a shipped product yet.
>
> Hardware testing reports from real Macs are the most useful contribution
> right now: https://github.com/tuna-os/bootc-installer-asahi
> #Linux #AppleSilicon #AsahiLinux #ARM #bootc

### Toot 7 — Snapdragon X Elite (X13s-class)

> Bonito/Dakota has ARM laptop builds for Snapdragon X Elite (X13s-class)
> hardware — the same atomic update model as the rest of the project, on
> the fastest-growing ARM Windows hardware. Linux support on it still
> needs real-world testing; this is a concrete place to start.
>
> https://tunaos.org/download — hardware matrix in the README.
> #Linux #Snapdragon #ARM #bootc #LinuxHardware

### Toot 8 — Keyless-signed packages (supply-chain story)

> How TunaOS ships keyless-signed packages: every RPM/DEB on the R2-hosted
> repos is signed with Sigstore/cosign keyless signing, verifiable against
> Rekor — no long-lived signing keys to leak, SBOMs included. Chain of
> trust for immutable desktops, explained in one post.
>
> https://tunaos.org/blog/2026/08/19/keyless-signed-package-delivery
> #Linux #SupplyChain #Sigstore #bootc #OpenSource

### Toot 9 — Migrating from Bluefin (Dakota)

> Moving from Bluefin to Dakota (or the reverse) without reinstalling:
> bootc-migrate handles the switch as a container-native rebase — your
> data, your config, one transaction.
>
> https://tunaos.org/blog/2026/08/20/migrate-bluefin-to-dakota-bootc-migrate
> #Linux #bootc #ImmutableLinux #Bluefin

### Toot 10 — Community + adoption call (evergreen)

> Using TunaOS in production, or evaluating it? We'd love to add you to
> ADOPTERS.md — submit a PR with your variant + use case, or open an issue
> and we'll help you get started. Questions? Matrix #tunaos is open:
> https://matrix.to/#/%23tunaos:reilly.asia
>
> #Linux #ImmutableLinux #bootc #TunaOS

## Account setup checklist

1. Register `@tunaos@fosstodon.org` (or linux.social) with the maintainer's
   human identity; set profile: one-liner + tunaos.org + GitHub link
2. Pin the good-first-issue pool link in the profile
3. Verify the account (server-specific) and follow: @ubuntulovers,
   @fosstodon, bootc-dev, Asahi Linux, elementary, ublue-os
4. Wire blog RSS → toot (manual copy-paste is fine at 4-6/month)

## Post-and-track

1. Post the toot, then drop the URL + follower/engagement delta into the
   monthly ADOPTION-METRICS.md snapshot (#1311)
2. Retro after 6 toots: what got engagement, what to cut
3. Next hook in the calendar: Q3 checkpoint (08-22) → GNOME 51 (~09-12) →
   Hacktoberfest (10-01) → Fedora 45 (~10-20)

---
*Prepared by the outreach agent (ACMM L6 — full mode) for tuna-os/tunaOS.*
