# Reddit / Lemmy Release-Announcement Playbook

> Status: **draft** — for maintainer review before first post.
> Tracking issues: [#1346](https://github.com/tuna-os/tunaOS/issues/1346) (Reddit/Lemmy Linux-community presence), [#1599](https://github.com/tuna-os/tunaOS/issues/1599) (homelab/self-hosted, Draft D), [#1610](https://github.com/tuna-os/tunaOS/issues/1610) (Q3 checkpoint recap, Draft E).
> Prepared: 2026-08-12, homelab draft added 2026-08-14. First post targets: Gurnard launch (#1344) / GNOME 51 release week (#1334).

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

## Target communities

| Community | Purpose | Posting approach |
|---|---|---|
| [r/linux](https://www.reddit.com/r/linux/) | Broad Linux audience for a substantial release or project milestone | One original, discussion-oriented post when the release has broad interest; answer questions in the same thread |
| [r/immutables](https://www.reddit.com/r/immutables/) | People specifically interested in image-based/atomic desktops | Use for variant, bootc, rollback, or image-update details; cross-post only when the content is relevant |
| [programming.dev/c/linux](https://programming.dev/c/linux) | Lemmy Linux audience | Publish the same announcement as a native post, adapting links and tone to the community |
| [lemmy.world/c/linux](https://lemmy.world/c/linux) | Additional Lemmy Linux audience | Cross-post only after checking local rules and whether the post adds value there |

Keep this list small and check relevance/local moderation rules before
expanding it — a post that fits r/linux does not automatically fit every
Lemmy Linux community.

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

## Release gate

Before drafting a post, confirm:

- the release or variant is published and the download page works;
- the release notes identify what changed, known limitations, and a
  support path;
- checksums/signatures and source links are available where applicable;
- the named variant and desktop are spelled consistently with the catalog;
- screenshots or other media are free to redistribute and have useful alt
  text;
- the post has one clear action for readers (try it, read the notes, or
  give feedback), not a list of unrelated asks.

If the download, release notes, or signing state is not ready, wait — a
broken announcement link is worse than a late announcement.

## Process

1. Draft post as a **GitHub Discussion** first (public review, gets the
   community's eyes on it before it goes out)
2. Re-check the target community's current rules immediately before
   posting — promotion limits, flair, and account-age requirements can
   change between drafting and publishing
3. Maintainer posts to r/linux + Lemmy (one human account)
4. Track star/download deltas per post in the monthly
   ADOPTION-METRICS.md snapshot (#1311); label unavailable values
   `not available` rather than estimating them
5. Retro after 3 posts: what worked, what to cut

## Ready-to-post drafts (August 2026 launch trio)

Three launches went out on the blog 2026-08-12 (Gurnard/Pantheon, Apple
Silicon, Snapdragon X Elite) with **no** Reddit/Lemmy presence yet. The
drafts below follow the template above and are ready for the maintainer to
post verbatim or trim.

**r/linux slot budget (1/month):** per the rules above, pick **one** of the
three for r/linux this month. Recommendation: **Draft B (ARM roundup)** —
it has the broadest audience (Apple Silicon + Snapdragon Linux are both
hot topics in 2026). The other two go to their niche subs (r/AsahiLinux,
r/linuxhardware, r/Ubuntu, r/elementaryos) where they are on-topic and not
subject to r/linux's self-promotion limits.

### Draft A — Gurnard (Ubuntu 24.04 + Pantheon)

**Target subs:** r/Ubuntu, r/elementaryos, r/linux (if not using Draft B)

**Title:** `TunaOS Gurnard — the Pantheon desktop on Ubuntu 24.04 LTS, as an atomic bootc image`

**Body:**

> We just shipped **Gurnard** — Ubuntu 24.04 LTS with the Pantheon desktop
> (the elementary OS environment) wrapped in an atomic, container-native
> core. It's the first widely-buildable way to run the elementary desktop
> on a standard Ubuntu LTS base.
>
> Why it matters: Pantheon is one of the most polished desktop shells in
> Linux, but until now it was mostly tied to elementary OS itself. Gurnard
> keeps the calm, minimal, app-centric feel while the base behaves like a
> modern immutable system — bootable containers, atomic updates, rollback
> on failure, verified upgrades. Flathub and Homebrew are pre-enabled.
>
> New/changed:
> - Ubuntu 24.04 LTS base + Pantheon shell, x86_64 **and** arm64 images
> - Atomic updates with rollback; images on GHCR (`ghcr.io/tuna-os/gurnard:base` / `:pantheon`)
> - Built with the same bootc toolchain as the rest of TunaOS
>
> Try it: https://tunaos.org/download — announcement post with more
detail: https://tunaos.org/blog/2026/08/12/announcing-gurnard-ubuntu-pantheon
>
> Status: **experimental** — great time to kick the tires while bug reports
> are cheap and can shape the Pantheon packaging. Feedback welcome in the
> comments or on Matrix (#tunaos).

### Draft B — Apple Silicon (M1/M2 Macs)

**Target subs:** r/AsahiLinux, r/linux (recommended r/linux slot for Aug)

**Title:** `TunaOS on Apple Silicon — bootc images for M1/M2 Macs, alongside Asahi`

**Body:**

> We just published **TunaOS images for Apple Silicon Macs** — atomic,
> container-native Linux for M1/M2, installed via our
> bootc-installer-asahi path (which is explicitly designed to work beyond
> TunaOS — Dakota, Bluefin, Bazzite could all ride it).
>
> Why it matters: Apple Silicon is the most common ARM Linux machine in
> the world, and the Asahi ecosystem has done the heavy lifting to make
> Linux run there. TunaOS adds a bootc-based desktop on top: atomic
> updates, verified upgrades, rollback. It's not a replacement for Asahi
> Linux — it's a sibling with a different update model.
>
> New/changed:
> - Bootc images for M1/M2 Macs with a recoveryOS handoff installer
> - Golden-manifest verification of the installed payload
> - R2-hosted payloads; installer docs written up this week
>
> Try it: https://tunaos.org/download (Apple Silicon section) — post:
> https://tunaos.org/blog/2026/08/12/tunaos-on-apple-silicon
>
> Status: early but actively developed (commits this week). Hardware
> testing reports from real Macs are the most useful contribution right
> now — we track them here: https://github.com/tuna-os/bootc-installer-asahi

### Draft C — Snapdragon ARM laptops (X13s reference path)

**Tracking:** [#1374](https://github.com/tuna-os/tunaOS/issues/1374)

**Target subs:** r/linuxhardware, Snapdragon/X13s communities, r/linux (if not using Draft B)

**Title:** `TunaOS on Snapdragon ARM laptops — the X13s reference path for Linux testing`

**Accuracy note:** Do not describe the ThinkPad X13s as a Snapdragon X Elite
device. Lenovo's X13s uses Snapdragon 8cx Gen 3, while Snapdragon X Elite is a
separate platform family. Lead with the X13s support that is documented today;
invite X Elite owners to report hardware compatibility rather than implying
that the X13s image is already validated on every X Elite laptop. Sources:
[Lenovo X13s specification](https://news.lenovo.com/wp-content/uploads/2022/02/ThinkPad-X13s-Gen-1-Datasheet.pdf),
[Qualcomm X Elite brief](https://docs.qualcomm.com/bundle/publicresource/87-71417-1_REV_E_Snapdragon_X_Elite_Product_Brief.pdf).

**Body:**

> We just published **TunaOS ARM laptop images for the ThinkPad X13s** — the
> Bonito/Dakota family now has a documented Snapdragon laptop path with the
> same atomic, container-native update model as the rest of the project.
>
> Why it matters: Snapdragon laptops are bringing a new wave of ARM hardware
> owners into Linux. The X13s is a concrete, documented starting point, while
> owners of newer Snapdragon X Elite systems can help establish which parts of
> the story generalize to their hardware.
>
> New/changed:
> - Bonito/Dakota ARM images for the ThinkPad X13s
> - Same toolchain: atomic updates, rollback, verified upgrades
> - Documented hardware support matrix in the README
>
> Try it: https://tunaos.org/download — post:
> https://tunaos.org/blog/2026/08/12/tunaos-on-snapdragon-x-elite
>
> Status: early. If you own an X13s or Snapdragon X Elite laptop and want to
> help test, report the exact model, firmware version, install path, working
> devices, and failures in the issue tracker rather than assuming cross-device
> compatibility.

### Draft C execution checklist

Before publication, the maintainer should:

1. Confirm the target community permits project announcements and hardware
   testing requests; ask moderators or channel maintainers where required.
2. Use the [Bonito X13s](https://github.com/tuna-os/docs/tree/main/docs/bonito-x13s)
   and [Dakota X13s](https://github.com/tuna-os/docs/tree/main/docs/dakota-x13s)
   guides as the technical source of truth. Do not promise X Elite support
   unless a device-specific report exists.
3. Ask testers to report model, firmware, image/variant, installer path,
   kernel, working hardware, and logs. Link the resulting issue or discussion
   back to #1374 so this outreach produces evidence rather than impressions.
4. Record the post URL, date, channel, and tester responses in the issue. Do
   not add an adopter entry without consent-confirmed public evidence.

### Draft D — Homelab / self-hosted (bootc desktop + Corral)

**Target subs:** r/selfhosted, r/homelab — audience-specific, not subject
to the r/linux 1/month slot budget above.

**Title:** `TunaOS + Corral — a bootc desktop and a Kubernetes-native VM manager, same image-based model`

**Body:**

> Two things from the TunaOS project that fit this sub: the desktop OS
> ships as a **bootc container image** (atomic updates, one transaction,
> rollback on failure — no package-manager drift to babysit), and
> [Corral](https://github.com/tuna-os/corral) is a companion VM manager
> that runs the same idea against your homelab: QEMU/KVM locally,
> KubeVirt if you've got a cluster, with a Proxmox-style web UI.
>
> The angle that might actually be useful to you: Corral also serves a
> **Proxmox VE API-compatible layer** on top of KubeVirt (verified against
> the `bpg/proxmox` Terraform provider) — so existing Proxmox tooling
> (Terraform, Ansible's `community.general.proxmox_*`, `proxmoxer`,
> monitoring scripts) can list/create/start/stop/delete KubeVirt VMs
> without knowing Corral is there. It is **not** a Proxmox host manager —
> if you want Corral to manage an existing Proxmox box as a backend,
> that's still an open gap (no PVE export adapter yet, tracked upstream).
> It's the reverse: making a Kubernetes cluster speak Proxmox's API to the
> tools you already use.
>
> Try the desktop side first — a QEMU/KVM eval takes about 20 minutes,
> no repartitioning, snapshot-and-revert the whole thing:
> https://tunaos.org/docs/tunaos/evaluating-in-a-vm
>
> Corral: https://github.com/tuna-os/corral (backend support matrix in
> the README — QEMU/KubeVirt are the most complete backends today; Incus
> and libvirt work but some capabilities are backend-limited)
>
> Status: both actively developed, not "finished" — Corral is mid-rewrite
> from an earlier Python tool, and backend move/migration parity between
> Proxmox/Incus/KubeVirt is explicitly incomplete. Said honestly because
> this sub calls that out fast if you don't.

### Draft E — Q3 checkpoint recap (08-22)

**Target subs:** r/linux (the Q3 slot — Aug's Draft B already went out
or was skipped, pick one per month), r/selfhosted/r/homelab only if the
Corral/Draft D angle is reused. Prepared 2026-08-15 for the 08-22
publish; body mirrors the recap post
(`docs/blog/2026-08-22-q3-2026-community-checkpoint.md`, draft:true).

**Title:** `TunaOS Q3 checkpoint: four new desktops on enterprise lifecycles, honest numbers, and a Hacktoberfest backlog`

**Body:**

> TunaOS just published its **Q3 2026 community checkpoint** — the
> quarterly review of what shipped and what's next, written for the
> people who use or build on it.
>
> What Q3 delivered:
> - **Four new variants**: Gurnard (Ubuntu 24.04 LTS + Pantheon),
>   Hummingbird (container-native Fedora), plus the existing GNOME, KDE,
>   COSMIC, Niri, and XFCE flavors on Enterprise Linux lifecycles — all
>   atomic, rollback-safe bootc images
> - **Flavor equality**: the catalog parity gate now holds every desktop
>   to the same promotion standard; GNOME is no longer "primary"
> - **Infrastructure**: manifest-driven build pipeline, published
>   multi-arch images, verified boot reports per release, documented
>   package-sourcing policy
>
> The honest part: ~55 GitHub stars (flat), and by real contributor
> count this is still a single-maintainer project — an early "first
> external contributor" signal turned out to be an automated agent
> account, and we corrected that publicly rather than keep the metric.
> Closing that gap is exactly what the good-first-issue backlog (6 now,
> growing to 8 before Hacktoberfest) is for.
>
> Every open Q3 goal gets an explicit STAFF / DESCOPE→Q4 / DROP
> decision, with owners — carryover is a decision, not a discovery.
>
> Read it: https://tunaos.org/blog (Q3 2026 checkpoint) — decision
> sheet: https://github.com/tunaos/TunaOS/blob/main/Q3_CHECKPOINT-2026-08-22.md
>
> Status: alpha/beta software across most variants — good time to kick
> the tires while bug reports are cheap. Feedback welcome on Matrix
> (#tunaos) or GitHub Discussions.

**Publish-day copy (Matrix #tunaos + GitHub Discussions Announcements, per #1610):**

> 📊 Q3 2026 checkpoint is up: what TunaOS shipped this quarter (Gurnard,
> Hummingbird, flavor equality), where we're honest about the numbers
> (flat stars, still single-maintainer by real contributors), and what
> happens to every open goal — STAFF, DESCOPE, or DROP.
> Six good-first-issues are tagged and growing to eight before
> Hacktoberfest. Blog: <link> — discussion below 👇

### Post-and-track

1. Post the chosen draft (maintainer account), then drop the URL + star
   delta into the monthly ADOPTION-METRICS.md snapshot (#1311).
2. Retro after 3 posts (playbook rule above).
3. Next hook in the calendar: Q3 checkpoint recap (08-22, Draft E
   above), GNOME 51 release week (~09-12), Hacktoberfest (10-01),
   Fedora 45 (~10-20), homelab/self-hosted post (Draft D, no fixed date
   — ride the Q3 checkpoint's Corral/bootc mentions per #1599).
