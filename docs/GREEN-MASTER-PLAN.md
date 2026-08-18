# Master plan: getting to green

**Green** is defined in [GREEN-CRITERIA.md](GREEN-CRITERIA.md) /
[`.github/green-criteria.yml`](../.github/green-criteria.yml): a cell is green
only when it builds, ships its declared desktop, boots to a session, installs
from ISO, completes installation, survives update/rebase/rollback, matches
upstream, admits its omissions, stays rebuildable, and declares no
architecture it cannot satisfy. Skipped, never-tested and stale are **not
green**.

This document is the work plan to get there. It was written on 2026-08-17
against measured state, not aspiration; where something is undiagnosed it says
so. Baselines per criterion are recorded in `green-criteria.yml`; this file is
about *sequence* — what unblocks what.

The matrix is 142 image cells across 13 variants. On 08-17: **84 build**,
**35/52 pass the desktop contract**, **31/52 pass install (LUKS)**,
**0/36 ISO cells pass installer smoke**, **0/52 lifecycle** (one 9-second run
ever), parity and omissions **unmeasured**.

---

## Part 1 — Cross-cutting workstreams

Ordered by leverage: each unblocks many cells or makes the scoreboard honest.
Per-variant work (Part 2) mostly hangs off these.

### W1. Truth in reporting *(first, everything else is scored by it)*

The README matrix counts *promoted* cells; MATRIX-STATUS tracks the other axes
separately and nothing composes them. Under the new bar the scoreboard must
score cells against the criteria.

- [x] Extend `scripts/gen-matrix-status.py` to emit a **composite green
      table**: a cell is green only when every `blocking` criterion in
      `green-criteria.yml` has a current affirmative result; never-tested
      renders as ⬜, not green.
- [x] `update-build-status.sh` README table gains a second number:
      `built X/142 · green Y/142` so raising the bar is visible, not silent.
      Guarded: the script refuses to publish the composite number the day a
      criterion it cannot score graduates to blocking.
- [x] Per-cell provenance (which run asserted which criterion, when) — already
      half-exists in MATRIX-STATUS; make it cover every axis.
      Done: `composite_section()` records `{cell → {axis → verdict, date,
      run URL}}` as a side product of the same wiring that scores the board,
      and the generator ships it as `docs/matrix-provenance.json` next to the
      scoreboard on every refresh.

*Risk:* the composite number will start low (likely < 20/142). That is the
true number; do not soften it.

### W2. Bootc Lifecycle online *(criterion 6 — largest information gain)*

The workflow exists, is on a weekly cron (Thu 05:00Z), and has run **once**,
failing in 9 seconds — `generate-matrix` succeeded (the jq emits 156 cells
against today's config) yet no downstream job materialised. Verification run
`31999953433` dispatched 08-17 06:01Z.

- [x] Diagnose the run-2 result; fix whatever eats the matrix between
      `generate-matrix` and the `lifecycle` job — run 2 surfaced the arm64
      mixed-stack/stale-lock podman failure (#1556 class, all six arm64
      cells); fixed by the guarded install + lock sweep (#1841).
- [x] First full sweep: run 32040213366 (08-17, post-#1841) executed all
      168 cells — 133 passed, including 43 of 53 arm64. Every failure maps
      to a KNOWN class, no new ones: xfce cells → #1819 (7 cells,
      roster posted), gnome-nvidia-hwe → #1820 (3 cells, roster posted),
      bonito-rawhide → #1823, hummingbird desktops → images not yet
      published by the factory. The update transaction demonstrably works
      matrix-wide where images exist.
- [x] Wire results into MATRIX-STATUS (already scaffolded) and W1 — the
      scaffold had a latent key mismatch (raw job names like
      "yellowfin:gnome (amd64)" / "BETA guppy:gnome (amd64)" vs the
      composite's "variant:flavor" lookup), so all 168 real verdicts
      rendered ⬜; lifecycle_results() now normalises names and merges arch
      legs worst-of. Criterion flipped unimplemented → advisory on the
      first-sweep evidence; graduate after a second consecutive clean-shape
      weekly sweep.
- [x] Then: weekly cadence is already scheduled; make the cron survive —
      Bootc Lifecycle added to rerun-infra-failures.yml's roster, so an
      infra-classified red sweep gets one classified re-run instead of
      sitting unnoticed for four days like 08-13 did.

### W3. Boot gate mandatory where CI can test it *(criterion 3)*

The Gate exists and silently broke matrix-wide on 08-17 (#1811, fixed). It is
per-cell skippable, and `base` cells promote with the Gate skipped.

- [x] Make Gate **required for green** (not for promote) on every cell CI can
      actually boot: `boots` is now blocking with a reviewed scope
      (green-criteria.yml `scope:` excludes -asahi and base-hwe/base-nvidia);
      plain `base` cells get their own non-promote-blocking Gate asserting
      TUNAOS_BASE_CONTRACT_OK (multi-user + operable bootc).
- [x] DRM-limited cells: measured Gate outcomes decide per cell — marlin kde
      and xfce PASSED 2026-08-17, so "needs DRM" is per-variant evidence, not
      a blanket cap; cells whose gate fails or never ran render ❌/⬜, never
      green, exactly as required.
- [x] Gate-ran-at-all: under the composite, a skipped or absent Gate renders
      ⬜ and the cell is not green — the absence of a gate can no longer look
      like success on any scoreboard.

### W4. ISO + installer axis *(criterion 4 — currently 0 passes anywhere)*

- [ ] **#1772** — tacklebox `[customize]` hangs 87m silent on amd64. External
      pinned repo; needs either a maintainer fix upstream or a timeout+retry
      harness around it. This blocks *every* amd64 ISO cell.
- [ ] **#1556** — arm64 `libpod_lock` during tacklebox pre-pull blocks every
      arm64 ISO cell before boot; also gates the unresolved `-vga` risk on
      aarch64 (#1595 review note).
- [ ] Installer smoke passes 0/31 tested; after #1772/#1556, re-baseline and
      split real failures from the DRM-render-node harness limit.
- [ ] LUKS E2E (criterion 5) is the healthiest axis (31/52) — keep it green
      while the ISO work lands; it is the complement, not a substitute.

### W5. Read the omissions manifest *(criterion 8 — data exists, unread)*

Every image already writes `/usr/share/tunaos/missing-on-*.txt`.

- [x] Scheduled job: the desktop contract sweep now runs
      `verify-package-wishlist.sh` against every published image it pulls
      (one pull, two axes), records `omissions_status` per cell, and the
      composite scores it; unallowlisted omissions ⇒ not clean.
- [ ] This is what catches the #858 class (published image, no desktop) and
      the #1755 class (hummingbird desktops installing nothing) *at publish
      time* instead of at verification time.

### W6. Schedule parity *(criterion 7)*

- [x] `scripts/package-parity.sh` is on a daily cadence
      (`package-parity.yml`) and feeds W1: per-cell verdicts land in the
      package-parity-baseline artifact, the Package parity section, and the
      composite. First cadence = desktop-vs-own-base delta (the #858 shape);
      the audit roster now derives from build-config so no declared variant
      can be silently omitted.
- [x] Diff against each variant's UPSTREAM reference (Bluefin/Aurora package
      sets) — the `upstream` job in package-parity.yml measures every cell in
      green-criteria.yml's `upstream_references` map (bonito→bluefin:stable /
      aurora:stable, EL family→bluefin:lts) daily. Measurement only: the
      criterion stays advisory until the noise floor these numbers establish
      turns into per-variant thresholds, then graduate per-variant.

### W7. Rebuildability beyond base pins *(criterion 9)*

`check-base-image-pins.sh` covers the 13 base-image digests (nightly 22:20Z,
#1806/#1809). Not yet covered: COPR repos (#391 single point of failure),
repo.tunaos.org snapshots (hummingbird's 9-month-old datestamp pin), toolchain
payloads, action pins.

- [x] Extend the pin check to package-repo URLs per variant —
      scripts/check-package-repo-pins.py walks every desktop manifest for dnf
      baseurls, COPR projects, PPAs, and APT repos/keyrings, and probes each
      nightly in check-base-image-pins.yml (own job, so base-pin and
      package-pin failures report independently). 14 pins found, 14 resolving
      at first run. Toolchain payloads and action pins remain open, as does
      the COPR *content* question (#391 is about trusting the repo, not just
      its existence) — the structural fix for that is RFC 011's tier-2
      migration, not this check.
- [ ] The `createrepo_c --update` drift class (#358) is fixed in
      `build-xfce-package.yml` only — audit `build-xfce-distributed.yml`,
      `build.yml`, `build-gnome49/50/51-package.yml` (noted on #358).

### W8. Architecture honesty *(criterion 10)*

- [x] Config-time validation, first cadence: every declared platform must
      exist in the variant's base-image manifest list, checked nightly at
      22:20 UTC by `check-base-image-pins.sh` before the builds — an
      unsatisfiable declaration is now a loud config error, not a mystery
      red cell. Package-repo arch coverage (the hummingbird case proper) is
      the remaining half, shared with W7's repo-pin extension.
- [x] Decided and built: the aarch64 hummingbird leg landed
      (tunaos-packages#414) and upstream public-hummingbird serves arm64
      with full source parity — the four guaranteed-red cells become
      buildable once the first aarch64 factory run publishes.

### W9. Hardware capacity *(unblocks W3/W4 for 4 of 5 desktops, and NVIDIA)*

- [ ] GPU/DRM-capable runners (AWS grant, runs-on) → cosmic/niri/kde/xfwl4
      boot gates and installer smoke become testable.
- [ ] NVIDIA needs real GPUs; #848 (stage-3 dev ISO) is a prerequisite.
      Until then NVIDIA cells are *not yet covered*, never *green*.

---

## Part 2 — Per-variant state and work

Counts are build-axis cells from the README matrix (142 total). "Blockers"
are issues that stand between the variant and *build* green; the criteria
above then apply on top. NVIDIA flavors across yellowfin/albacore/skipjack/
bonito/bonito-rawhide/marlin/flounder/flounder-sid share **#1725**
(semodule install fails) plus W9, and are not repeated per row.

### yellowfin (AlmaLinux Kitten 10) — 12/20 build
| area | state | action |
|---|---|---|
| base/base-hwe, desktops | building, base promoted | keep |
| xfce, xfce-hwe | **unblocked 08-17** — gtkgreet checksum repaired (#358/#385), xfce built on amd64+v2 | confirm on next nightly, then hwe |
| *-nvidia (6 cells) | #1725 semodule | fix build; hardware via W9 |
| gnome-asahi | arm64/Asahi tier (#1738 sweep red) | Asahi hardware smoke track |

### albacore (AlmaLinux 10) — 12/20 build
Same shape as yellowfin. Additionally:
| area | state | action |
|---|---|---|
| gnome-nvidia-hwe | **boot gate fails for real** — marker never emitted, 900s timeout (#1751); only non-Sigstore red in the 08-15 EL10 sweep | debug with the full-log method recorded on #1751 |
| xfce, xfce-hwe | expect unblock from #358 repair | verify next nightly |

### skipjack (CentOS Stream 10) — 9/18 build
| area | state | action |
|---|---|---|
| gnome, gnome-hwe | classified 2026-08-17: builds succeed on both arches; Gates died on the #1811/#1818 just-cwd class (fixed on main), Attest SBOMs on Rekor 502s | clears on the first post-#1818 nightly; verify then |
| xfce | expect unblock from #358 repair | verify next nightly |
| *-nvidia (5) | #1725 | as above |

### bonito (Fedora 44) — 6/15 build
| area | state | action |
|---|---|---|
| base | **promoted 08-17** after #1806 re-pin | keep |
| desktops | were blocked behind base; tonight xfce/arm64 built, xfce/amd64 failed — **undiagnosed** | classify remaining desktop failures now base is back |
| *-nvidia (5) | #1725 | as above |

### bonito-rawhide (Fedora Rawhide) — 6/14 build
| area | state | action |
|---|---|---|
| base (both arches) | pin fixed (#1806), now blocked **upstream**: rpmfusion ffmpeg-libs needs `liboapv.so.2`, nothing provides it (#1810) | watch upstream; product call between wait / scoped `--skip-unavailable` / drop rpmfusion — see #1810 options |
| everything else | downstream of base | — |
| taxonomy | rolling variant, structurally exposed to skew (#1762) | count under rolling standard |

### hummingbird (Fedora rebuild, experimental) — 1/5 build
The fully-diagnosed one: **#1755**.
| area | state | action |
|---|---|---|
| base | **promotes on both arches** | keep |
| gnome amd64 | builds; repo lacks gnome-shell/gdm/mutter (29 of 52 pkgs missing) so the image has no real desktop | needs tunaos-packages rebuilds (#1755 §2, tunaos-packages#250) |
| cosmic amd64 | **section landed 08-18** (#1755 option B): 22/23 pkgs re-measured against the live repo, `hummingbird:` section added to cosmic.yaml (cosmic-settings-daemon deliberately omitted — not in repo) | verify on next nightly |
| kde/niri | no manifest section; ~50% pkg coverage | after cosmic proves the path |
| all arm64 desktops | repo 404s — unsatisfiable by construction | W8: drop or build (#1755 option A/D) |
| dconf branding failure | **deliberately left failing** — guarding it would green cells that contain no desktop | fix only after manifest sections exist |
| convergence | tunaos-packages seed grew for the first time since 08-09 (7170→7673); reserve budget stops *between* tiers (tunaos-packages#401), cosmic/niri/kde runs lost to the 6h ceiling | in-loop deadline check (#401), tier failures layer-00/01/02/07/10/11 to classify (#402/#403/#404 candidates) |

### sailfin (openSUSE Tumbleweed) — 0/7 build → base back
| area | state | action |
|---|---|---|
| base | **promoted 08-17** after #1806 re-pin (was 100% blocked) | keep |
| gnome/kde/cosmic/niri/xfce amd64 | classified 2026-08-17: **#1832** — one blocker for all five: openSUSE ships the crippled ffmpeg (h264/hevc decoders compiled out), the codec baseline fails deterministically | enable Packman ffmpeg (the RPM Fusion equivalent), per #1832 |

### guppy (Gentoo) — 2/4 build
The best-instrumented variant after this week.
| area | state | action |
|---|---|---|
| base, xfce | promoted, with attested SBOM for the first time (#1567 closed loop: cgroup cap #1784/#1795 + manifest-derived SBOM fallback #1796) | keep |
| gnome | builds, signs — **fails the desktop-experience contract deterministically**, `early_exit rc=1` at ~36s, twice reproduced (#1801) | reproduce locally via `scripts/boot-gate.sh guppy gnome`; genuine desktop debugging |
| kde | emerge now *finishes* (3h43m under #1803's 240m) but image assembly overruns the ceiling; **0 of 70 emerges used the binhost** (#1802) | enable `getbinpkg` for `kde-plasma/*` — packaging decision, collapses hours to minutes; do **not** raise the ceiling again |

### gurnard (Ubuntu 24.04, experimental) — 2/2 build
Green on build. Next bar: gates, ISO, lifecycle like everyone else. No known
variant-specific blocker.

### grouper (Ubuntu 26.04) — 6/7 build
| area | state | action |
|---|---|---|
| kde/xfce gates | broke 08-17 with the module-path regression, fixed (#1811) | verify on next nightly |
| gnome-zfs | classified 2026-08-17: builds, signs; Gate died on the #1811/#1818 just-cwd class (fixed on main), Promote skipped behind it | clears on the first post-#1818 nightly; verify then |

### marlin (Arch) — 16/16 build, gates regressed
| area | state | action |
|---|---|---|
| all desktop gates | failed 08-17 on #1811's path bug; **every desktop Promote skipped**, so marlin drops to ~base on the next matrix refresh | verification run dispatched on the fixed main — confirm 16/16 restored |
| base Gate | **skipped yet counted green** — the live example of criterion 3 | W3 makes this visible |
| cachyos flavors (5) | build; same gate/ISO/lifecycle bar applies | — |

### flounder (Debian 13) — 7/7 build
Green on build (nvidia included since #1564). Next bar is gates/ISO/lifecycle.

### flounder-sid (Debian Sid) — 5/7 build
| area | state | action |
|---|---|---|
| gnome, xfce | classified 2026-08-17: **#1833** — sid's GNOME 50→51 transition (libgjs0 Breaks gnome-shell < 51~beta~); gnome via extension-manager→gjs, xfce via gdm3→gnome-shell | upstream heals on gnome-shell 51; optional decoupling per #1833 |
| taxonomy | rolling variant (#1762) | rolling standard |

---

## Part 3 — Sequence

**Phase 0 — score honestly (days).** W1 composite scoring; W2 lifecycle
diagnosis (run in flight); confirm #1811 restored the marlin/grouper gates;
close out the four "undiagnosed" boxes above (skipjack gnome, sailfin
desktops, grouper gnome-zfs, flounder-sid gnome/xfce) — every one is a
log-pull away from being a classified blocker.

**Phase 1 — build to 100% of the satisfiable matrix (weeks).** #1725 nvidia
semodule (~16 cells, largest single block); hummingbird cosmic manifest
section (1 cell, proves the rebuild path); W8 decision on hummingbird arm64;
guppy kde binhost (#1802); bonito-rawhide upstream watch (#1810).

**Phase 2 — boots + desktop (overlaps 1).** Gate mandatory-for-green on
testable cells (W3); guppy gnome #1801 and albacore gnome-nvidia-hwe #1751
are the two known real boot failures; W9 GPU runners to open the other four
desktops.

**Phase 3 — ISO + install.** #1772, #1556, then installer-smoke re-baseline.
Zero cells pass today; this is the axis with the most ground to cover.

**Phase 4 — lifecycle, parity, omissions as gates.** W2 weekly green, W5/W6
feeding W1, then flip each from `advisory` to `blocking` in
`green-criteria.yml` — deliberately, one at a time, with the number drop each
causes stated in the PR that flips it.

**Definition of done:** `green-criteria.yml` shows every criterion `blocking`,
and the composite table shows a cell green only when all of them hold. The
number on that day is the real one, whatever it is.
