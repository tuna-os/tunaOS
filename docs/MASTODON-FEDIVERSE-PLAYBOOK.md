# Mastodon / Fediverse Release-Announcement Playbook

> Status: **draft** — for maintainer review before account creation or first post.
> Tracking issue: [#1634](https://github.com/tuna-os/tunaOS/issues/1634) (Mastodon/Fediverse presence).
> Prepared: 2026-08-14. First post targets: Q3 checkpoint recap (08-22) / GNOME 51 release week (#1334).

## Why this exists

Stars are flat (~55; Q4 target ≥100 per ADOPTION-METRICS.md). Reddit/Lemmy
([#1346](https://github.com/tuna-os/tunaOS/issues/1346)), Matrix (#1136),
DistroWatch (#1333), Fedora Magazine (#1137), and conferences (#1135/#1166)
are covered — the **Fediverse is the only non-GitHub channel with no
presence**. It is also where the bootc / immutable-desktop conversation
actually lives: bootc's CNCF maintainers, the Universal Blue team, and the
AlmaLinux/Fedora communities all post there, and cross-posting a tunaos.org
blog post reaches people who never open GitHub. A single maintainer account
with a ~2–4 toots/month cadence turns every release hook into distribution.

## Rules of engagement

- **One human maintainer account** — no bots, no automation, no sockpuppets
- **Toot, then engage** — reply to comments and questions in-thread; never
  post-and-abandon
- **Link tunaos.org, not raw GitHub** — blog posts and /download first; GitHub
  links only in replies
- **Accessibility** — image descriptions (alt text) on every screenshot, no
  emoji-stuffed walls, plain hashtags (2–3 max per toot)
- **Respect instance norms** — read the server rules of the chosen instance
  before posting; keep promotion ≤ ~25% of total toots

## Account setup (maintainer action, one-time)

| Item | Recommendation |
|---|---|
| Instance | `fosstodon.org` (FOSS crowd) or `mastodon.social` (broadest reach); pick one, stay |
| Handle | `@tunaos` if free; else `@tunaos_os` — keep the same handle across instances for verification |
| Bio | "Atomic bootc desktops for Enterprise Linux — AlmaLinux, Fedora, Ubuntu, Debian bases. tunaos.org" + link |
| Profile link | tunaos.org + GitHub org (lets Mastodon verify `rel="me"` on both) |
| Header/pic | Use the TunaOS branding repo assets; a screenshot of the Yellowfin desktop works as header |

## When to post (candidate hooks)

| Hook | Date | Toot angle |
|---|---|---|
| Q3 2026 checkpoint recap (#1345/#1610) | 08-22 | What shipped in Q3; Gurnard + ARM story |
| GNOME 51 release week (#1334) | ~09-12 | GNOME 51 on EL10 before upstream |
| Hacktoberfest kickoff (#1623) | 10-01 | Curated good-first-issue pool, DCO-signed |
| Fedora 45 GA (#1166) | ~10-20 | Bonito on Fedora 45, bootc desktop story |
| New variant / hardware enablement | ad hoc | Asahi (M1/M2), Snapdragon X Elite (X13s), Gurnard/Pantheon |

## Ready-to-post drafts

Each draft is a thread: an opener toot + 1–2 continuation toots (the
Fediverse rewards threads over walls of text). All drafts are <500 chars per
toot and link tunaos.org.

### Q3 checkpoint recap (2026-08-22)

> Toot 1 (opener):
> The TunaOS Q3 checkpoint is out — what the team shipped this quarter, and
> where the project goes next. New: Gurnard (Ubuntu 24.04 + Pantheon), bootc
> images for Apple Silicon and Snapdragon X Elite laptops, and keyless-signed
> package repos. https://tunaos.org/blog/q3-2026-community-checkpoint
> #TunaOS #bootc #EnterpriseLinux

> Toot 2 (thread):
> Quick version: TunaOS is an atomic, bootc-based desktop for Enterprise
> Linux. AlmaLinux, Fedora, Ubuntu, Debian, Arch and Gentoo bases — one
> update story, rollback included. Flatpaks by default, Homebrew baked in.
> Try it in a VM: https://tunaos.org/download #Linux #immutable

### GNOME 51 release week (2026-09-12)

> Toot 1 (opener):
> GNOME 51 is landing on TunaOS's EL10 images ahead of the upstream release
> schedule — enterprise desktops updated on the Fedora/AlmaLinux cadence, not
> the distro-release cadence. Details + screenshots on the blog:
> https://tunaos.org/blog/gnome-51-coming-to-tunaos #TunaOS #GNOME #bootc

> Toot 2 (thread):
> This is the payoff of the keyless-signed repo pipeline: the GNOME stack is
> packaged and shipped from source, signed with cosign, verifiable end to
> end. More on that: https://tunaos.org/blog/keyless-signed-package-delivery
> #supplychain #FOSS

### Hacktoberfest kickoff (2026-10-01)

> Toot 1 (opener):
> Hacktoberfest is on — TunaOS has a curated pool of starter tasks, all
> DCO-signed and labeled good-first-issue. Docs, tests, packaging; no
> experience required. Come build the enterprise Linux desktop with us:
> https://tunaos.org/blog/hacktoberfest-2026 #Hacktoberfest #opensource

### Fedora 45 GA (2026-10-20)

> Toot 1 (opener):
> Fedora 45 is out — and TunaOS's Bonito variant is built on it. An atomic
> bootc desktop on the Fedora base, with Niri and the X13s ARM story as
> options. https://tunaos.org/blog/fedora-45-bonito #TunaOS #Fedora45 #bootc

## Process

1. Draft each toot **in the matching GitHub Discussion** first (public
   review; the Reddit/Lemmy playbook uses the same gate)
2. Maintainer posts the thread from the single account; replies within 24h
3. Track follows, boosts, and tunaos.org click-throughs per toot in the
   monthly ADOPTION-METRICS.md snapshot (#1174)
4. Retro after 4 posts: which hooks earned engagement, which to cut

## Why not automate

Toot automation (bots, scheduled posters) is actively penalized by the
Fediverse and would burn the trust this channel exists to build. The value is
a human maintainer voice in the same rooms as the bootc community — that is
the point.
