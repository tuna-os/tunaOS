# elementary OS Community — Gurnard Cross-Post Draft

> Status: **draft** — for maintainer review + explicit approval before any external contact.
> Tracking issue: [#1368](https://github.com/tuna-os/tunaOS/issues/1368) (elementary OS cross-post pitch).
> Prepared: 2026-08-13. Target: elementary OS blog/planet, community forums (warm — elementary OS is listed in ADOPTERS.md).

## Cross-post summary (3–4 paragraphs, submission-ready)

**Title (working): Pantheon, anywhere: Gurnard brings the elementary desktop to Ubuntu 24.04 LTS**

If you love the Pantheon desktop — the calm, minimal environment at the heart
of elementary OS — you mostly had to run elementary OS itself to get it. A new
project called [TunaOS](https://tunaos.org) just made that choice bigger:
**Gurnard** pairs Ubuntu 24.04 LTS with Pantheon, wrapped in an atomic,
container-native core. It's the first widely-buildable way to get the
elementary desktop on a standard Ubuntu LTS base.

Gurnard keeps what makes Pantheon special — the elegant shell, the
application-centric workflow, the clean out-of-the-box feel — while the base
underneath behaves like a modern immutable Linux: bootable containers, atomic
updates, rollback on failure, verified upgrades. Flathub and Homebrew come
pre-enabled, so apps and tools are a click away. The images ship for both
x86_64 and arm64.

Why does this matter for the elementary community? Because Pantheon is
packaging surface that deserves to live beyond one distribution. Gurnard is
experimental today (`ghcr.io/tuna-os/gurnard:base` and `:pantheon`) — the
right time to try it is now, while bug reports are cheap to fix and can shape
the packaging before the surface settles. Think of it as a second home for
Pantheon: same desktop, new foundation, and a project that explicitly lists
elementary OS in its ecosystem table.

If you're curious: [announcement post](https://tunaos.org/blog/2026/08/12/announcing-gurnard-ubuntu-pantheon),
[download](https://tunaos.org/download), or join the conversation on
[Matrix #tunaos](https://matrix.to/#/%23tunaos:reilly.asia). Feedback,
bug reports, and packaging help are all welcome — and we'd love to hear from
elementary users about what a Pantheon-on-Ubuntu should feel like.

## Pitch email variant (short)

> Hi elementary team,
>
> TunaOS just shipped Gurnard — Ubuntu 24.04 LTS with the Pantheon desktop as
> an atomic bootc image. We'd love to feature a short cross-post on the
> elementary blog/planet or community forum, framed around "Pantheon on a
> non-elementary base" and what that means for the desktop's reach.
>
> Happy to adapt tone/length to your editorial style. Full announcement:
> https://tunaos.org/blog/2026/08/12/announcing-gurnard-ubuntu-pantheon
>
> — TunaOS maintainer

## Process notes

- **No external contact without maintainer approval** (outreach policy Rule 10)
- On approval, route the pitch through the maintainer (hanthor)
- Track pickup in ADOPTION-METRICS.md funnel tier 1 (#1311)
- elementary OS is a warm partner (ADOPTERS.md row added in #1356) — this is
  ecosystem engagement, not cold outreach
