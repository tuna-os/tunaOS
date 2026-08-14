# Fedora Magazine — Guest Post Pitch Draft

> Status: **draft** — for maintainer review and submission to fedora-magazine@fedoraproject.org.
> Tracking issue: [#1137](https://github.com/tuna-os/tunaOS/issues/1137) (Fedora Magazine guest post pitch ahead of Fedora 45).
> Prepared: 2026-08-12. Suggested pitch window: August 2026 for a late-Sept/Oct 2026 slot (Magazine writers pitch 4–6 weeks ahead).

## Pitch email (≈300 words, submission-ready)

**Subject: Guest post pitch — "Bonito: Fedora's newest immutable desktop flavor"**

Hi Fedora Magazine team,

I'd like to propose a guest post for the Fedora 45 release window: **"Bonito:
Fedora's newest immutable desktop flavor — what bootc brings to the Fedora
desktop."**

**The story.** Bonito is a Fedora-based, bootable-container desktop — one of
several images built by [TunaOS](https://tunaos.org), an open-source project
focused on immutable, cloud-native desktops. Where classic Fedora Workstation
installs a package-managed root filesystem, Bonito ships the whole desktop as
a bootc container image: atomic updates, one transaction, rollback on
failure, verified upgrades. The desktop updates like a container fleet, and
stays on a current GNOME while the base tracks Fedora's lifecycle.

**Why it fits Fedora Magazine.** Fedora is where the container-native desktop
idea is most alive — the bootc work, and the growing group of Fedora-based
immutable spins (including our Niri and XFCE flavors, which build on Fedora
infrastructure). TunaOS also packages current GNOME backports (49/50/51) for
CentOS Stream 10 and Fedora bases through its own native RPM build chain,
published to a project-run repository — Fedora COPR is legacy/compatibility
infrastructure for us now, being phased out — so the post can cover both the
Bonito image itself and the wider packaging effort — genuinely Fedora
ecosystem news, not an advert.

**What we'd include.** A short tour of Bonito: what it is, how bootc changes
the update model, what works today (Fedora 44 base, GNOME, Niri, XFCE
flavors, verified boot reports), and how to try it. All content is already
published on [tunaos.org/blog](https://tunaos.org/blog) and
[github.com/tuna-os/tunaOS](https://github.com/tuna-os/tunaOS), so we can
provide a full draft in Magazine house style on request.

**About the author.** TunaOS is an open-source project with a daily rolling
build cadence (plus weekly and quarterly-LTS stability tiers for users who
want less churn) and an active community on Matrix. Happy to adapt length,
tone, and
depth to the Magazine's editorial preferences.

Thanks for considering,
[Maintainer name]

## Editorial notes

- Pitch deadline: **submit in August 2026** for a Fedora 45 (Oct 2026) slot
- Follow up once, ~2 weeks after submission
- If accepted: repurpose the 2026-07-19 "Modern Enterprise Linux Desktops
  with TunaOS" blog post into Magazine house style, update for Fedora 45
- Link back to tunaos.org/blog from the article

## Submission checklist

- [ ] Maintainer review of pitch text
- [ ] Send to fedora-magazine@fedoraproject.org
- [ ] Track acceptance; convert to house-style draft if accepted
- [ ] Record pickup in ADOPTION-METRICS.md funnel tier 1 (#1311)
