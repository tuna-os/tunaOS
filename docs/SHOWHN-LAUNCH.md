# Show HN Launch Playbook

> Status: **draft** — maintainer review before posting. Nothing here is posted
> until the maintainer presses submit.
> Tracking issue: [#1759](https://github.com/tuna-os/tunaOS/issues/1759)
> (Show HN launch, timed to the Q3 checkpoint 2026-08-22).
> Prepared: 2026-08-16. Facts per [PRESSKIT.md](PRESSKIT.md) (re-verified
> 2026-08-14 against ROADMAP.md).

## Why HN and why now

Stars are flat at ~55 (two months) against a Q4 target of ≥100
(ADOPTION-METRICS.md). Hacker News is the single highest-leverage launch
channel for a young Linux distro: a strong Show HN thread converts into
stars, forks, and first-time contributors (exactly what the Q3 checkpoint
recap, #1345, needs after landing our first human external contributor,
docs#284).

The Q3 checkpoint recap publishes 2026-08-22 — the canonical link for any
HN post, giving the launch a content anchor (recap → download → GH repo).

## Timing — important

**2026-08-22 is a Saturday.** HN traffic and Show HN visibility are
significantly lower on weekends; the checkpoint itself is an internal
decision date, not a publish constraint for HN. Recommended windows:

| Option | When | Why |
|---|---|---|
| **A (recommended)** | Fri 2026-08-21, 08:00–09:00 US/Eastern | Post day before the recap; recap goes up 08-22 and is added as a comment; HN weekday morning peak |
| B | Mon 2026-08-24, 08:00–09:00 US/Eastern | Post-recap Monday; recap already live as the canonical link |
| C | Sat 08-22 morning | Only if we must tie the exact day; accept lower visibility |

Never post on a US holiday or during a major tech launch day (check
calendar before choosing).

## The post

**Title** (must start with `Show HN:`):

> Show HN: TunaOS – atomic bootc desktops on Enterprise Linux lifecycles

**URL**: `https://tunaos.org` (downloads + docs) — the recap blog post is
added in the first comment once it is live.

**First comment** (the HN author comment — paste, then trim to taste):

> TunaOS is a family of atomic, image-based (bootc) Linux desktops that
> bring current desktops to Enterprise Linux lifecycles. Servers run on
> decade-long lifecycles; desktops move on six-month cadences. TunaOS
> closes the gap: every variant is a container-native bootc image with
> atomic updates, verified (keyless-signed via Sigstore/cosign) upgrades,
> and rollback — tracking current desktops (GNOME 51, KDE Plasma 6,
> COSMIC, Niri, XFCE, Pantheon) on EL10, Fedora, Ubuntu LTS, Debian,
> Gentoo, and Arch bases.
>
> We're a fork of Bluefin (Universal Blue) with a manifest-driven,
> multi-distro build pipeline. Right now the honest status: Yellowfin and
> Albacore (GNOME on AlmaLinux 10) are the stable GA line; several other
> variants are beta or experimental (full lifecycle table in the repo).
> We also ship experimental Snapdragon X Elite laptop builds and an Apple
> Silicon installer (boot payloads still pending — engineering preview).
>
> It's a small, single-maintainer-core project — the Q3 checkpoint recap
> went up this week and our first human external contributor landed a PR
> last week. Good-first-issue tasks are tagged and Hacktoberfest is
> coming. Happy to answer anything.

## Anticipated questions (pre-drafted replies)

- **"Why not just use Bluefin/Bazzite?"** — TunaOS is a fork of Bluefin
  with a different job: current desktops on EL lifecycles (GNOME 51 on
  AlmaLinux/CentOS Stream before the point release) plus an independent,
  multi-base variant model. Same bootc foundation, different roadmap.
- **"Is this production ready?"** — Honest per-variant: GA line =
  Yellowfin/Albacore GNOME. Others are beta/experimental and labeled as
  such (VARIANT-LIFECYCLE.md). No overclaiming.
- **"bootc vs ostree/rpm-ostree?"** — bootc is the container-native
  successor; images are OCI, updates are one transaction, rollback is
  built in. Good primer: bootc-dev/bootc (CNCF sandbox).
- **"What's the security story?"** — Keyless signing via Sigstore/cosign,
  SBOMs included, verified upgrades; no long-lived signing keys.
- **"ARM?"** — Snapdragon X Elite builds exist today (experimental);
  Apple Silicon installer ships kernel+glue (boot payloads pending, #777).
- **"How do I try it?"** — Pick a variant on tunaos.org/download, write the
  image, `rpm-ostree rebase` style transition or fresh install; bootc-migrate
  can move from Bluefin/Dakota without reinstalling.

## Engagement rules (post-click)

- **Stay in the thread for hours** — HN visibility is front-page-window
  driven; answer every substantive question, terse and honest.
- **No astroturf** — no upvote rings, no sockpuppets, no "we built this
  too" drive-bys. One human account (`hanthor`).
- **No marketing speak** — HN punishes launch-press language; numbers and
  honesty win (the first-comment template above is already written that way).
- **Link the recap** once it is live; link the GH repo for code questions.
- **After the thread dies** — fold learnings + referral counts into
  ADOPTION-METRICS.md and the #1610 promotion bundle retrospective.

## Checklist before posting

- [ ] Maintainer approves title + first comment (nothing posted otherwise)
- [ ] tunaos.org is up; download page lists the GA variants clearly
- [ ] Recap (docs#295, blog 2026-08-22) is live — or post Option A and add
      the recap link as the first comment on 08-22
- [ ] GNOME 51 beta-testing call post (08-17) is live — a healthy GNOME 51
      hook strengthens the thread
- [ ] Repo README badges/links current (build matrix is auto-refreshed)
- [ ] Check the HN calendar for conflicts (no holiday/major-launch overlap)
