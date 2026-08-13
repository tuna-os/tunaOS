# Reddit / Lemmy Release-Announcement Playbook

> Status: **draft** — for maintainer review before first post.
> Tracking issue: [#1346](https://github.com/tuna-os/tunaOS/issues/1346) (Reddit/Lemmy Linux-community presence).
> Prepared: 2026-08-12. First post targets: Gurnard launch (#1344) / GNOME 51 release week (#1334).

## Why this exists

Stars are flat (~55; 3 new in the last week) and the Q4 target is ≥100
(ADOPTION-METRICS.md). Matrix (#1136), DistroWatch (#1333), Fedora Magazine
(#1137), and conferences (#1135/#1166) are covered — but there is **no**
Reddit/Lemmy presence, and that is where the ublue/Bluefin ecosystem gets
outsized visibility for immutable-desktop releases. This playbook makes
release announcements a repeatable, low-effort process.

## Rules of engagement

- **One text post per release or variant launch on r/linux**, plus one
  Lemmy cross-post — **max ~1/month**, no spam cadence
- **Maintainer-voiced**, first-person, linking tunaos.org (not just GitHub)
- **Respect each community's rules** — r/linux self-promotion policy,
  Lemmy instance rules; read them before posting
- **Never astroturf** — no bot accounts, no vote manipulation, no
  sockpuppets. One human account, clearly the maintainer
- **Engage honestly in comments** — answer questions, accept criticism,
  update the post with fixes

## When to post (candidate hooks)

| Hook | Date | Post angle |
|---|---|---|
| Gurnard launch (#1344) | Aug 2026 | Ubuntu 24.04 + Pantheon as an atomic bootc image |
| GNOME 51 release week (#1334) | ~Sep 12 | GNOME 51 on EL10 before the upstream release |
| Hacktoberfest (#1331) | Oct 1 | Good-first-issue backlog, contributor onboarding |
| Fedora 45 (#1166) | ~Oct 20 | Bonito on Fedora 45, bootc desktop story |
| Q3 checkpoint recap | 08-22 | Community milestones, new variants |

## Post template

**Title**: `TunaOS <release/variant> — <one-line value>`

**Body**:
1. What it is (1–2 sentences, plain language)
2. Why it matters for Linux users (immutable/bootc angle)
3. What's new/changed (bullets)
4. How to try it (tunaos.org/download + docs link)
5. Known limitations / status (honest)
6. Link: tunaos.org/blog post + GitHub

## Process

1. Draft post as a **GitHub Discussion** first (public review, gets the
   community's eyes on it before it goes out)
2. Maintainer posts to r/linux + Lemmy (one human account)
3. Track star/download deltas per post in the monthly
   ADOPTION-METRICS.md snapshot (#1311)
4. Retro after 3 posts: what worked, what to cut

## First post (ready to adapt)

Gurnard launch announcement — see
[blog/2026-08-12-announcing-gurnard-ubuntu-pantheon.md](https://github.com/tuna-os/docs/blob/main/blog/2026-08-12-announcing-gurnard-ubuntu-pantheon.md)
and issue #1344 for the base content.
