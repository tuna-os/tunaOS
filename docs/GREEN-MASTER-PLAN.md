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

*Resolved (2026-08-18, maintainer decision):* every **base** Gate timed out
marker-less matrix-wide (VM boots, paints a text screen, serial silent —
verified on sailfin and bonito-rawhide with #1855's surviving evidence),
and the maintainer settled the underlying product question instead: base
images are parent layers, not user-facing artifacts — nobody runs them
as-is. Plain `base` is now a reviewed boots-scope exclusion (like
base-hwe/base-nvidia) and the dedicated base Gate job is removed; a base's
boot machinery is transitively proven by every desktop Gate stacked on it
(marlin's 15 Gate passes prove marlin's base boots). The boots axis is now
exactly the desktop Gate, which demonstrably works. #1861's serial-tail
dump stays — it serves the desktop-Gate ❌ cells (albacore/yellowfin/
skipjack/grouper/flounder/guppy), which are the real remaining boots work.

*Post-mortem datum (08-18, from #1861's serial dump on the last base Gate
ever run, sailfin dispatch 32105775211):* console routing was never the
problem — the serial log shows a complete boot to login (graphical target
reached, agetty on ttyS0). The `TUNAOS_BASE_CONTRACT` marker simply never
emitted: the contract unit didn't fire, on a system that otherwise booted
clean. Recorded here for the day `base` is ever re-gated.

### W4. ISO + installer axis *(criterion 4 — currently 0 passes anywhere)*

- [x] **#1772** — tacklebox `[customize]` hangs 87m silent on amd64. Fixed by
      #1882 (outer 80-min deadline) + #1885 (streamed customize, 30-min cap):
      customize now streams and completes in ~2 min. Closed with evidence from
      run 32238167029.
- [x] **#1556** — arm64 `libpod_lock` during tacklebox pre-pull. Root cause
      stale `/dev/shm/libpod_lock` (lock-count drift → ERANGE); fixed by the
      rm + `podman system renumber` reset in ghcr-login (#1576), lifecycle
      (#1841), and the ISO surface (#1848). Closed with arm64 login + full
      build evidence (run 32254285223).
- [ ] Installer smoke passes 0/31 tested. **Now blocked by #1893, not #1772**:
      after customize completes, the ISO build hangs ~50 min silently in the
      `podman commit` of the customized container (tacklebox#231 streams it).
      Re-baseline and split real failures from the DRM-render-node harness
      limit once the pin bump lands.
- [ ] LUKS E2E (criterion 5) is the healthiest axis (31/52). Blocked at the
      same "Build dev ISO" step (the Aug 9 failures), so it needs the same
      #1893 fix before a fresh sweep can re-verify 31/52.

### W5. Read the omissions manifest *(criterion 8 — data exists, unread)*

Every image already writes `/usr/share/tunaos/missing-on-*.txt`.

- [x] Scheduled job: the desktop contract sweep now runs
      `verify-package-wishlist.sh` against every published image it pulls
      (one pull, two axes), records `omissions_status` per cell, and the
      composite scores it; unallowlisted omissions ⇒ not clean.
- [x] This is what catches the #858 class (published image, no desktop) and
      the #1755 class (hummingbird desktops installing nothing) *at publish
      time* instead of at verification time — in force since the box above
      landed: the sweep reads the manifest from every published image daily
      and unallowlisted omissions score the cell not-clean in the composite.

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
- [x] The `createrepo_c --update` drift class (#358) is fixed in
      `build-xfce-package.yml` only — audit `build-xfce-distributed.yml`,
      `build.yml`, `build-gnome49/50/51-package.yml` (noted on #358).
      Audited 2026-08-18 (tunaos-packages#421): every named suspect is clean
      — they all exclude `repodata/**` at seed and full-generate before any
      `--update`. The class IS live in two surfaces the issue did not name:
      `build-fprintd-aarch64.yml` (seeds published repodata, signs only new
      RPMs, then `--update`) and the justfile's `sync-to-r2` recipe (the
      #358 shape verbatim). Update 08-18: RFC 011 is **accepted** (maintainer
      sign-off; ADR 0001 in tunaos-packages) and **packages#419 MERGED
      08:36Z** — the #421 fixes, the Phase 0 catalog (928 entries +
      completeness tests), the deb `apt-get build-dep` rework, and the
      workflow shell-quoting regression test are all on main. Tracking
      issue #418 stays open for Phase 1+. RFC 011 Phase 2 makes this class
      structurally unrepeatable.

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
      Update 08-18: the first aarch64 publish landed
      (`hummingbird/20251124-aarch64`, 1358 packages) but is a seed with no
      desktop coverage (cosmic 8/22, gnome 5/52, measured live). The four
      cells are pinned `linux/amd64` per #1755 option A instead of red —
      tests/test_hummingbird_arm64_honesty.py makes re-adding arm64 a
      reviewed, per-desktop, measured decision as the factory converges.

### W9. Hardware capacity *(unblocks W3/W4 for 4 of 5 desktops, and NVIDIA)*

- [ ] GPU/DRM-capable runners (AWS grant, runs-on) → cosmic/niri/kde/xfwl4
      boot gates and installer smoke become testable.
- [ ] NVIDIA needs real GPUs; #848 (stage-3 dev ISO) is a prerequisite.
      Until then NVIDIA cells are *not yet covered*, never *green*.

### W10. Package supply (RFC 011) — the factory closes the gap and retires COPR

The image factory's green bar depends on the package supply. RFC 011
(tunaos-packages) makes the supply structural: one catalog owns identity,
the gap engine computes per-target need against live repo indexes, and one
unified format-agnostic factory (`package-factory.yml` + `package-factory-cell.yml`,
landed in tunaos-packages#430, amended by #438) builds only what the target's
system repos cannot supply. Measured 2026-08-18 (`docs/factory-status.json`):

| target | built | needed | coverage |
|---|---|---|---|
| `el10/x86_64` | 56 | **73** | 43% |
| `hummingbird/x86_64` | 570 | 103 | 85% |
| `hummingbird/aarch64` | 262 | **411** | 39% |
| `arch`/`debian`/`opensuse-tumbleweed`/`ubuntu` | — | — | **unmeasured** |

The third-party dependency to retire is COPR `jreilly1821/c10s-gnome-50` /
`c10s-gnome-49` (#391 SPOF) — the `build-order*.yml` files still carry
`copr_name` entries ("already registered in COPR; just trigger build-package").

- [x] RFC 011 accepted; Phase 0 catalog (928 entries + completeness tests)
      landed (tunaos-packages#419); the unified factory (#430) replaced the
      per-family workflows; RFC amended to the format-agnostic shape (#438).
- [ ] Close the el10 gap (73 needed: COSMIC, XFCE-Wayland, Niri/labwc/greetd,
      fprintd, and the long tail) — tracking tunaos-packages#439.
- [ ] Close the hummingbird/aarch64 gap (411 needed) or honestly classify the
      x86_64-only upstream sources.
- [ ] Measure the four unmeasured targets (`arch`, `debian`,
      `opensuse-tumbleweed`, `ubuntu`) so their need is computed, not assumed.
- [ ] Retire COPR: remove the `copr_name` entries as each family's in-factory
      build proves out and the image build points at the factory R2 path.
- [ ] Wire factory dependency ordering — gap deps must publish before their
      dependents' clean-install verify (tunaos-packages#440; the first el10
      wave showed niri failing on unbuilt `libseat`, its declared runtime dep).

---

## Part 2 — Per-variant state and work

Counts are build-axis cells from the README matrix (142 total). "Blockers"
are issues that stand between the variant and *build* green; the criteria
above then apply on top. NVIDIA flavors across yellowfin/albacore/skipjack/
bonito/bonito-rawhide/marlin/flounder/flounder-sid share **#1725**
(semodule install fails) plus W9, and are not repeated per row.
*Re-classified 08-18 for EL10 (albacore run 32090745718, posted on #1725):
the current failure is not semodule — all five albacore nvidia legs die in
the overlay kernel swap with rpmdb sqlite corruption ("database disk image
is malformed" on every INSERT while installing kernel-6.12.0-257.el10),
i.e. the same rpmdb-under-buildah-overlay class as #1823, on a second
variant surface. Count EL10 nvidia cells under #1823 until it resolves.
**RESOLVED on the EL10 surface, three rounds of evidence (08-18→08-20):**
round 1 (#1877, bare `rpm --rebuilddb`) produced the discriminating
signature — clean rebuild, replace REFUSED, zero malformed; round 2
(#1909, literal-path directory round-trip) killed the malformed storm but
the rebuild's rename still failed; round 3 (#1912, `readlink -f` the
dbpath + round-trip the RESOLVED directory + rebuild demoted to advisory)
went GREEN: albacore base-nvidia run 32339591457 logged the resolution
(`/usr/share/rpm` is a real dir there — symlink hypothesis refuted for
EL10), the kernel transaction completed with no malformed and
`TUNAOS_NVIDIA_CONTRACT_OK`. Root cause: rpm writing into a db directory
still in a lower overlay layer; the upper-layer round-trip is the whole
fix, the rebuild was only ever the probe. Round 4 (#1916) closed the
second half of the class: the DESKTOP legs inherit a db their stage-2
already corrupted at rest and need the rebuild's PRODUCT, which rpm
builds and then discards at its failing rename — so the guard now
salvages it file-level, exactly per rpm's own printed recovery
instruction. **Validation run 32367546177 (08-20): ALL FIVE albacore
desktop-nvidia legs built green** — `rebuilt-salvaged` marker, zero
malformed, zero failed deps, `TUNAOS_NVIDIA_CONTRACT_OK` — plus
base-nvidia promoted. The full EL10 nvidia cluster (~15 build cells
across albacore/yellowfin/skipjack, same overlay script) is unblocked;
the next board refresh shows it. Ported to bonito-rawhide's stage-2
(`rawhide_rpmdb_probe`, #1915+#1916) — verify on its next nightly's
desktop legs, then #1823 closes.*

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
| desktops | classified 08-18: xfce **healed on both arches**; gnome/niri amd64 fail on F44 amd64 repo skew (libxslt/libtasn1/libnotify version walls + `LIBSYSTEMD_257` symbol missing) — upstream repo inconsistency, nothing here can fix it | heals when the F44 amd64 mirrors converge; re-check next nightly |
| *-nvidia (5) | #1725 | as above |

### bonito-rawhide (Fedora Rawhide) — 6/14 build
| area | state | action |
|---|---|---|
| base (both arches) | **promotes again since 08-18** — the #1810 liboapv wall cleared upstream | keep |
| rpmdb (#1823) | probe verdict in (nightly 32090947417): `rpm --rebuilddb` fails **at rest** on the inherited base — malformed before any stage-2 write, or the rebuild's replace step fails under the buildah overlay; discriminating datum recorded on #1823 | run the probe once on a stable dnf base to pick between the two readings |
| desktops | new upstream skew class 08-18: `libnma-gtk4` still requires `libnm.so.0` after Rawhide's NetworkManager dropped it — nothing here can fix it | heals when Rawhide rebuilds libnma; rolling standard |
| taxonomy | rolling variant, structurally exposed to skew (#1762) | count under rolling standard |

### hummingbird (hardened rolling fork of Fedora Rawhide, experimental) — 1/5 build
The fully-diagnosed one: **#1755**.
| area | state | action |
|---|---|---|
| base | **promotes on both arches** | keep |
| gnome amd64 | builds; repo lacks gnome-shell/gdm/mutter (29 of 52 pkgs missing) so the image has no real desktop | needs tunaos-packages rebuilds (#1755 §2, tunaos-packages#250) |
| cosmic amd64 | three walls down in one day (08-18): manifest section landed (#1859) → first run died on missing dconf (binary absent, branding keyfiles uncompilable — fixed by #1875, dconf listed in both cosmic lists) → second run **built, manifested and signed** with the desktop contract passing, then its Gate died at disk install: `bootc install` execs mkfs.xfs from inside the image and the btrfs-oriented upstream base ships no xfsprogs (run 32139187211) — xfsprogs added to the hummingbird base set (in repo, verified) | verify Gate on the next dispatch after the xfsprogs fix merges |
| kde/niri | no manifest section; ~50% pkg coverage | after cosmic proves the path |
| all arm64 desktops | resolved 08-18 via option A: the aarch64 repo now publishes (1358-pkg seed vs x86_64's 8100 — cosmic 8/22, gnome 5/52, no shell/gdm/compositor measured live) but cannot carry a desktop yet, so desktop flavors are pinned `linux/amd64` in build-config with the re-add condition tested | re-add arm64 per flavor when the aarch64 index carries that desktop's manifest set |
| dconf branding failure | **deliberately left failing** — guarding it would green cells that contain no desktop | fix only after manifest sections exist |
| convergence | tunaos-packages seed grew for the first time since 08-09 (7170→7673); reserve budget stops *between* tiers (tunaos-packages#401), cosmic/niri/kde runs lost to the 6h ceiling | in-loop deadline check (#401), tier failures layer-00/01/02/07/10/11 to classify (#402/#403/#404 candidates) |

### wahoo (Fedora ELN, experimental) — 4/4 build; gnome + kde Gate-green and promoted (08-27)
New 2026-08-25 (#2042); cosmic + kde added 08-27 (#2103). The EL11
early-warning lane: ELN is Rawhide sources built with Enterprise Linux
macros, and its os-release already reads `ID=eln`, `VERSION_ID=11`,
`ID_LIKE="rhel centos fedora"` — the same 11 c11s and
almalinux-bootc:11-kitten will carry. Nothing else in the matrix sees EL11.

Dispatch-only (`experimental: true`): 0 nightly cells, 0 ISO cells; its
incremental scheduled cells are the three desktops in the monthly LUKS sweep.

**It boots.** Run 33041330231 (on a4d86c5) is the first wahoo dispatch to
reach a Gate at all — earlier runs had it `skipped` — and **gnome and kde
both passed it**. That retires the "this lane has never booted" caveat these
docs carried from 08-25, for those two flavors.

| area | state | action |
|---|---|---|
| base amd64/arm64 | built, manifested, cosign-signed, **Promoted** | keep |
| gnome amd64/arm64 | built, **Gate PASSED**, **Promoted** | keep |
| kde amd64/arm64 | built, **Gate PASSED**, **Promoted**. Plasma 6.7.4 (plasma-desktop, kwin 6.7.4-2, kscreen), sddm 0.21.0 present; `TUNAOS_BRANDING_KDE_OK` | keep |
| cosmic amd64/arm64 | **built, manifested and signed on both arches** — but **Promote skipped**, held behind a Gate that never ran: the GPU runner failed to launch with AWS `VcpuLimitExceeded` ("current vCPU limit of 0" for the `g4dn*` bucket). Nothing about the image was tested; `cosmic-linux-amd64`/`-arm64` and `cosmic-testing` are on GHCR, the promoted `cosmic` tag is not | **needs a human**: raise the AWS on-demand `g4dn` vCPU limit for the runner account, then re-dispatch. Not a wahoo defect |
| kde display manager | **measured answer to the question kde.yaml flagged**: the eln `kde-desktop` group makes `plasma-login-manager` (6.7.4) mandatory, and it claims `display-manager.service` first — the build logs `already points at plasmalogin.service; leaving it` — so the greeter is **plasmalogin, not the `sddm` the manifest declares**. The Gate passed on it, so this is an accuracy gap in the manifest, not a breakage | decide whether ELN should override `display_manager` per-section; note `display_manager` is top-level in kde.yaml and shared with el10/fedora, so it must not be changed globally |
| package measurement | `TUNAOS_WISHLIST_OK misses=0` on every flavor — every strictly-listed name resolved, nothing silently skipped. The pre-merge repodata measurements (cosmic 23/24, kde 16/23) held exactly | re-measure when ELN moves |
| desktop contract | **waived, not passed, on all three desktops — `missing=1` each, and the 1 is always the codec gap.** `verify-desktop-experience.sh` calls `waive()` on the h264 branch after the ELN marker, so the images are correctly stamped "NOT a verified desktop" while still building | closes only when a codec source exists |
| codecs | **sharper evidence than the 08-25 note.** The build's own `codec_diag` shows ELN's ffmpeg-free is configured `--disable-decoders` and `--disable-decoder='h264,hevc,vc1,vvc'` — the decoders are **compiled out of libavcodec**, not merely unbacked by the `noopenh264` stub. So even a working openh264 would not restore hevc/vc1/vvc. `TUNAOS_CODEC_GAP` fires on every green build as designed | tunaos-packages#562 — a sourcing decision, not a build task |
| SBOM attestation | still missing. All three `Attest SBOM` jobs failed on `rekor.sigstore.dev` (14x 502 plus 429s) with the workflow's `SIGSTORE_OUTAGE` classifier — the **third consecutive run**. Upstream, non-blocking; images are cosign-signed | attests itself when Sigstore's write path recovers; do not chase |
| niri/xfce | **not declared** — ELN ships one package of the Niri stack (`swaybg`) and zero `xfce*` | #2051/#2052; tunaos-packages#559-#562 |

### sailfin (openSUSE Tumbleweed) — 0/7 → **all five desktops promoted with Gates green (08-18)**
| area | state | action |
|---|---|---|
| base | **promoted 08-17** after #1806 re-pin; promotes nightly since | keep |
| gnome/kde/cosmic/niri/xfce amd64 | **VERIFIED 08-18** on dispatch 32105775211: all five legs built, **all five desktop Gates passed, all five Promoted** (gnome arm64 too). The four-layer codec saga (#1832) is closed: dup re-assert (#1850) → library complements (#1854) → availability-gated force + TUNAOS_CODEC_GAP (#1858) → `ffmpeg-8` CLI pin (#1861). Sailfin went 0→5 promoted desktop cells in one day and is the second variant after marlin with a fully Gate-green desktop board | unpin `ffmpeg-8` per the Containerfile note when Packman ships the 9.x stream; watch the nightly holds |

### guppy (Gentoo) — 4/4 build (08-18), kde+xfce fully green
The best-instrumented variant after this week.
| area | state | action |
|---|---|---|
| base, xfce | promoted, with attested SBOM for the first time (#1567 closed loop: cgroup cap #1784/#1795 + manifest-derived SBOM fallback #1796); xfce **Gate passed 08-18** | keep |
| gnome | builds (42m), signs — **fails the desktop-experience contract deterministically**, `early_exit rc=1`, reproduced again on the 08-18 nightly (#1801); Promote held behind the Gate | reproduce locally via `scripts/boot-gate.sh guppy gnome`; genuine desktop debugging |
| kde | **VERIFIED 08-18** (nightly 32090675142): #1816's binhost version-lock worked — kde built in **79 minutes** (vs the 6h ceiling), **Gate passed, Promoted**. Guppy now builds 4/4 with two desktop cells fully green | keep; #1816 pattern is the template if the tree races ahead again |

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
