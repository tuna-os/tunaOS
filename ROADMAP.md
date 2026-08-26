# tunaOS Roadmap

**Last updated**: 2026-08-14 (CI critical-path correction — 13/13 variants red #1570, workflows-permission blocker #1557; Hacktoberfest T-8 numbers) | **Maintainer**: tuna-os (hanthor)

---

## Mission

Bring a modern, cloud-native experience to the Enterprise Linux Desktop. tunaOS provides OCI-based, image-mode Fedora/AlmaLinux desktops with out-of-the-box developer tooling, GPU support, and immutable infrastructure patterns.

---

## Current Status (August 2026)

### Active Variants

| Variant | Base | Desktops | Status |
|---------|------|----------|--------|
| Yellowfin | AlmaLinux Kitten 10 | GNOME, KDE, COSMIC, Niri, XFCE | Stable |
| Albacore | AlmaLinux 10 | GNOME, KDE, COSMIC, Niri, XFCE | Stable |
| Skipjack | CentOS Stream 10 | GNOME, KDE, COSMIC, Niri, XFCE | Beta |
| Bonito / Bonito Rawhide | Fedora 44 / Rawhide | GNOME, KDE, COSMIC, Niri | Beta |
| Sailfin | openSUSE Tumbleweed (rolling) | GNOME, KDE, Niri, XFCE | Beta |
| Guppy | Gentoo Linux (source-based) | GNOME, KDE, Niri, XFCE | Beta |
| Grouper | Ubuntu 26.04 | GNOME, KDE, Niri, XFCE | Beta (RFC 010) |
| Marlin | Arch Linux (rolling), CachyOS overlay | GNOME, KDE, COSMIC, Niri, XFCE | Beta |
| Flounder / Flounder Sid | Debian 13 Trixie / Sid | GNOME, KDE, COSMIC, Niri, XFCE | Beta |
| Hummingbird | Fedora Hummingbird (container-native bootc) | Base, GNOME, KDE, COSMIC, Niri | Experimental (see #1341) |
| Gurnard | Ubuntu 24.04 Noble | Base, Pantheon | Experimental (see #1341) |
| Wahoo | Fedora ELN (EL11 preview, rolling) | Base, GNOME | Experimental — both flavors built and published 08-25 (dispatch-only, no cron); **not booted**, Gate is skipped on dispatch (fedora-eln/eln#214, desktops #2048) |

**Status terms** follow [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md): `Stable`
means GA, `Beta` means published for testing on tunaos.org/download. This
table is the canonical per-variant status; tunaos.org wiki and blog copy must
track it. Notably **Bonito is Beta** (GA tracked in [#272](https://github.com/tuna-os/tunaos/issues/272)) — it is neither "Production" nor "Experimental".

> **Experimental** (per maintainer #1315): Hummingbird and Gurnard/Pantheon are
> configured in `.github/build-config.yml` and building, but predate the
> admission gate in [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md) (#1196) — they
> have no named owner or acceptance criteria yet. They are tracked in
> [#1341](https://github.com/tuna-os/tunaos/issues/1341); the 2026-08-22 Q3
> checkpoint (#1299) decides staff vs. descope. README coverage is tracked in
> [#1298](https://github.com/tuna-os/tunaos/issues/1298).

### Build Health

⚠️ **CORRECTION (2026-08-14)**: the prior "CI pipeline builds are green" claim is **stale** — **all 13 variant workflows were red on 08-14** (#1570, consolidated root-cause diagnosis: yellowfin, albacore, skipjack, bonito, bonito-rawhide, sailfin, guppy, grouper, marlin, flounder, flounder-sid, gurnard, hummingbird). Every failed job maps to a known root cause (no unexplained failures); fixes are fixable but stranded: the hive GitHub App **lacks `workflows` permission** (#1557), so every `.github/workflows/*.yml` fix PR is rejected at push. **CI recovery is now the Q3 critical path** (strategist #1571) — flavor equality (#1316), NVIDIA family (#1383), and release parity (#1254) staff tests all depend on a green matrix. 08-22 checkpoint decision required: STAFF CI-recovery with first-PR-by-09-01, plus maintainer grant of the App `workflows` permission.

✅ **Downloads VERIFIED WORKING** (2026-08-08): tunaos.org/download serves 179 ISOs from R2 (newest 08-07, HTTP 200 GB-scale). ✅ **GitHub Releases RESUMED 2026-08-09**: `gnome-20260809` published 11:38 UTC with assets (incl. SBOM spdx, 52.5 MB) — first release since 07-12; the `a4b147f8` fix (build-run selection, not artifact name — see #1106) and the #1147 cadence backstop are confirmed effective. #936 (tacklebox pin) is **not** a live-boot fix hold: the `image-versions.yaml` fallback was moved to the live-boot fix (tacklebox `4fa6041`) on 07-31 by #937. What is left is a separate, narrower thing — `publish-iso-groups.yml` sets its own `TACKLEBOX_SHA: a105d6d3` (61 commits older, pre-dating the appended-overlay live path), and since `publish-isos.yml` is disabled that override is the SHA every scheduled ISO is actually built with. Those ISOs boot-gate green (run 30773566969, 08-03), so this is a divergence to close deliberately with its own boot evidence, not a hold to lift.

### Community

- 55 stars, 3 forks
- CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md published (June 2026)
- Discussions enabled
- Multi-agent development active (architect, guide, sec-check, quality, CI, outreach)
- 34+ community outreach issues filed; product-readiness gate (#563) resolved
- ⚠️ Adoption metrics untracked — no usage/telemetry data on the 179 downloadable ISOs (#1174); **plan published 08-10** ([ADOPTION-METRICS.md](./ADOPTION-METRICS.md)) — first monthly download/usage snapshot targeted 2026-11-01 (Q4 "Mature")
- 🟡 ROADMAP coverage improving — **16/37 active authorized repos now carry a ROADMAP.md** (2026-08-14): tunaos, tromso, tacklebox, docs, xfce-linux, bluefin-cli, Tavern, corral, tunaos-packages, **bootc-installer** (ROADMAP moved to default branch via PR #14, 08-14 — #1361 resolved), bootc-migrate, dualcut, gtk-office-suite, iso-builder, protota, wootc; template merged into .github project-starter (#13). Excluded from planning scope: ubuntu + letters (**archived** 2026-08-12). Still unplanned (21 active): .github, flatpak-index, bootc-installer-asahi, branding, bst-ci, changelog-action, debian-copr, finupdate, fisherman, homebrew-tap, kde-build-meta, mandelbrot, mariner, remora, scoop-bucket, suite-common, suite-common-rust, tuna-installer-cosmic/kde/niri/xfce (#1295)
- ⚪ **"First external contributor" claim retracted (#1317, corrected 2026-08-13)**: the shimonenator commits (EL10/OBS design fixing #777, image-factory completion gate) are **not** a human contribution — maintainer confirmed the account is misattributed by GitHub because the Google Antigravity agent is listed as commit author; `git log` shows `commit.author.name: antigravity` on every one of that account's commits. **Superseded 2026-08-14**: the **first external human contributions landed and merged the same day** — docs #234 (QEMU/KVM guide, dchaudhari7177) and docs #239 (Gurnard Pantheon fix, Elonon901001), both verified human GitHub accounts (created 2022, real-name profiles). These are docs-repo contributions, not core-code: bus-factor risk (#1095) for core repos is unchanged, but the onboarding loop (seed → PR → merge) is now demonstrably end-to-end, which materially strengthens the Hacktoberfest seeding case (#1537).

- 🟡 **Flavor equality mandate (08-11)**: maintainer directive #1315 — all supported flavors are equal tiers; GNOME-first framing and cadence to be retired (#1316)

---

## Q2 2026 (April–June) — "Stabilize" ✅ COMPLETE

**Theme**: Fix CI, land strategic documentation, ship Redfin alpha.

**Result**: 11/12 goals completed. ISO publishing regressed (#543). Redfin alpha carried to Q3.

| Goal | Status | Issue |
|------|--------|-------|
| CI build reliability ≥80% | ✅ Done | #226, #314, #448 |
| ISO E2E tests passing | ✅ Done | #227 (ISOs building) |
| ISO publishing restored | ✅ Done | #229 (⚠️ regressed: see #543) |
| CONTRIBUTING.md published | ✅ Done | #268 (PR #319) |
| SECURITY.md published | ✅ Done | #269 (PR #319) |
| CODE_OF_CONDUCT.md published | ✅ Done | #270 (PR #319) |
| ROADMAP.md published | ✅ Done | #267 |
| Redfin (RHEL 10) alpha | 🟡 Carried to Q3 | — |
| Security hardcoded creds removed | ✅ Done | #318, #359 |
| SELinux enforcing | ✅ Done | #318, #322 |
| ublue-os/packages COPR eliminated | ✅ Done | #436 |
| projectbluefin/actions adopted | ✅ Done | #440–441 |
| arm64 builds passing | ✅ Done | #448 |

---

## Q3 2026 (July–September) — "Expand" 🟡 IN PROGRESS

**Theme**: Expand variant coverage, harden architecture, grow community.

**Mid-quarter update (2026-08-10)**: Q3 milestone populated; CI green (at the time — see 08-13 correction below); **downloads verified working** (179 ISOs, newest 08-07). ⚠️ **Q3 at risk — checkpoint 2026-08-22** (#1299): 4 open strategic goals (#272 Bonito GA, #1123 Redfin alpha, #1093 RFC governance, #1094 ADR coverage) with zero movement since 08-08 while CI/ops work lands daily. ⚠️ **Desktop parity crisis** (#1294): tunaos-packages#133 audit shows 24/37 published editions are too small to contain their desktop (non-RPM bases: sailfin/flounder/grouper). GitHub Releases gap fixed 08-08 (#1106/#1147 closed, `a4b147f8`).

**Mid-quarter update 2 (2026-08-11)**: maintainer filed #1315 — **flavor equality mandate** (no GNOME-as-primary framing; all supported flavors equal tiers). This reframes desktop parity (#1294) from defect-fix to product strategy; flavor cadence parity (#1254, PR #1314) is its first deliverable. ✅ First deliverable landed 05:22Z: **browser ISO catalog parity gate merged** (#1322) — catalog generation now fails when any browser/on-demand flavor lacks a published catalog fact (#1281 closed). ~~Community signal: first external contributor (shimonenator, 08-10)~~ — **retracted 08-13** (#1317): confirmed an Antigravity-agent account, not a human contributor. #1308's starter backlog stands on its own merit regardless.

**Mid-quarter update 3 (2026-08-11)**: maintainer directive #1319 — **package sourcing policy**: default to system repos / tideforge; no PPAs/COPRs/OBS/AUR; build in-house what the base lacks, with a small trusted third-party allowlist. Second directive in 24h; elevates the Q2 COPR-elimination win (#436) into org-wide supply-chain policy (#1323).

**Correction (2026-08-13)**: the 08-10 "CI green" note above is stale. Bonito's nightly (`build-bonito.yml`) has been **red for 10/10 scheduled runs, 08-03 through 08-13** — verified via `gh run list`. Root cause is a cross-variant nvidia-overlay initramfs regression (`sr_mod`/`cdrom`/`virtio_blk` missing, `TUNAOS_NVIDIA_CONTRACT_FAIL`), independently confirmed also 100% red on Albacore, Marlin, and Yellowfin's nightlies over the same window — not Bonito-specific. Filed as #1499 (previously untracked; distinct from the closed, different-symptom #1118). Separately, `base`/arm64 jobs are failing on transient runner infra (`/libpod_lock` exhaustion), unrelated to the nvidia regression.

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| **Fix ISO downloads** | ci-maintainer | #543, #561 | ✅ Done — downloads verified working (R2, 08-07) |
| Bonito (Fedora 44) GA | ci-maintainer | #272 | 🔴 Blocked — nightly 10/10 red 08-03–08-13, cross-variant nvidia initramfs regression (#1499), not GA-ready |
| Redfin (RHEL 10) alpha | ci-maintainer | #609 (closed, shipped 08-09), #1123 | 🟡 Local-build alpha shipped (systemd auto-update timer units, #609/#1182/#1219) — intentionally **not** in `.github/build-config.yml`'s CI matrix (RHEL EULA forbids redistribution + no RHSM creds on CI runners, see `scripts/get-base-image.sh`); build via `just build redfin <desktop>` or `scripts/corral-build.sh`, see [docs/rhel-setup.md](docs/rhel-setup.md). Remaining: no automated build/publish path is possible by design, so "alpha" here means local-build-verified, not downloadable |
| Ship KDE, COSMIC, Niri, XFCE variants | ci-maintainer | #285 | 🟡 Published but **desktop-completeness unverified** — 24/37 editions undersized per #133/#1294 |
| GitHub Releases page carries ISO assets | ci-maintainer | #1106 | ✅ Verified 08-09 — `gnome-20260809` published with assets; cadence resumed |
| Release-cadence health gate (no silent skip) | ci-maintainer | #1147 | 🟡 Root cause fixed 08-08 (`a4b147f8` fails on dropped release) — verify no silent skip 08-09 |
| Containerfile deduplication | architect | #305 | ✅ Done |
| Hardcoded registry → configurable | architect | #304 | ✅ Done |
| Justfile modular decomposition | architect | #308 | ✅ Done |
| Migration guide (Silverblue/Kinoite/UB) | guide | #273 | ✅ Done (MIGRATION.md) |
| mdBook → tunaos.org centralized | guide | — | ✅ Done |
| Versioning policy documented | strategist | #274 | ✅ Done (VERSIONING.md, date-based + tiers) |
| **External contributor onboarding / Hacktoberfest 2026** | guide / strategist | #1331, #1347, #1354, #1537 | 🟡 In progress — **08-14 live census: 9 usable seeds in docs; tunaos has only non-usable meta-tracker #1308** vs 15–20 needed by the **09-15 seeding deadline** (#1537). **#1354's 3→8 target across tunaos+docs is met**, but the broader pool is below target after consumption. **Zero curated GFI** in protota, wootc, gtk-office-suite, tunaos-packages, and corral; `bootc-installer` has issues disabled entirely (#1531). Former tracker #1362 closed 08-14 as COMPLETED while target unmet — live pool tracking continues in #1537 |
| Weekly boot report as build gate | ci-maintainer | #989 | 🟡 In progress |
| Outreach sequencing | strategist | #563 | ✅ Done (gate lifted) |
| Populate Q3 milestone | strategist | #562 | ✅ Done (2026-08-08, 9 issues) |
| **User-proven ISO installs roadmap** | ci-maintainer | #763 | 🟡 In progress (Phase 1 baseline dispatched #761; GUI gate #577) |
| **Apple Silicon (Asahi Linux) support** | architect / ci-maintainer | #781 | 🟡 In progress (Bonito & Grouper 36/36 verified #776; D0–D4 installer track active) |
| **Desktop parity floor (non-RPM bases)** | packaging | #133, tunaos-packages#323 | ⬜ Not started — P0 for Q4 (see #1294) |
| **Q3 checkpoint (08-22): staff or descope #272/#1123/#1093/#1094** | strategist | #1299 | ⬜ Scheduled |
| **Flavor equality mandate (docs wording + cadence parity)** | strategist | #1315, #1254 | 🟡 In progress — catalog parity gate merged 08-11 (#1322, #1281 closed); cadence parity pending (#1316) |
| **NVIDIA flavor family (6 editions, 0 assets since 07-05)** | ci-maintainer | #1383 | 🔴 Broken — nightly overlay regressed 08-12 (#1382); 13/13 variant matrix red 08-14 (#1570) incl. nvidia cells (#1561/#1562/#1564/#1565); staff test: nightly green + gnome-nvidia assets republished by 09-01 (#1376/#1379) |
| **Package sourcing policy (system-repos/tideforge-first + allowlist)** | strategist | #1319, #1323 | 🟡 In progress — PACKAGE-SOURCING.md merged; DNF/COPR audit done 08-13, ahead of the 08-22 checkpoint (2 violations, 6-COPR niri gap, negativo17/rpmfusion allowlist candidates confirmed — #1453); apt/AUR/OBS bases still unaudited, maintainer allowlist sign-off and Phase 2 migration still pending |

---

## Q4 2026 (October–December) — "Mature"

**Theme**: Enterprise readiness, community governance, ecosystem integration.

**Planning started (2026-08-08)**: Q4 milestone #3 created; tracking issue #1159 open. **All 9 Q4 goals now tracked** (#1167 branch protection, #1168 governance, #1186 release automation, #1187 package signing/SBOM). Stale dependency refs (#306/#307/#212/#301 closed) still flagged in #1159. Extended 08-08 evening: adoption metrics (#1174) and variant lifecycle policy (#1175) added as strategist-owned goals. **Update 08-13**: All stale Q4 dependency refs now resolved — Supply chain hardening re-tracked under #1193 (was #212/#301, both closed), Tacklebox decoupling under #1192 (was #306, closed), Upstream snapshot automation under #1194 (was #307, closed). Both #1192 and #1194 already existed and already carried the Q4 milestone — this was a ROADMAP linking gap, not a missing-tracker gap. #1159's recommendation #3 (refresh stale dependency refs) is complete.

**Progress note (2026-08-11)**: keyless Cosign signing + signed SBOM attestations **landed 08-10** for published ISOs and container images (#1303, #1305) — first Q4 supply-chain deliverable. Remaining scope for #1187: signed SBOMs for **every** release artifact across all flavors (blocked on Releases cadence parity #1254) and tunaos-packages artifacts. Package sourcing policy (#1319/#1323) drafted as [PACKAGE-SOURCING.md](./PACKAGE-SOURCING.md) — source inventory feeds the #1187 attestation graph in Q4.

| Goal | Owner | Dependencies |
|------|-------|--------------|
| Tacklebox decoupling | architect | #1192 (tracker; #306 closed) — audited 2026-08-14: of #306's 4 recommendations, 3 already landed (`TACKLEBOX_SHA`/`TACKLEBOX_IMAGE` version pinning via `scripts/lib/common.sh`; tacklebox runs as a `ghcr.io/tuna-os/tacklebox` container image, not a host-installed binary; the flagged `ghcr.io/hanthor/bluefin:lts` `iso.toml` reference no longer exists in this repo's own build path). Real remaining gap: **the version pin has no single source of truth** — `image-versions.yaml` (`4fa6041`, renovate-tracked) diverges from hardcoded overrides in `publish-iso-groups.yml` (`a105d6d3`) and `luks-e2e.yml` (`fd95174`, the documented floor SHA, not the current pin). Consolidating those onto one pin needs real boot evidence before merging (see Build Health note above on why `publish-iso-groups.yml`'s divergence was left as a deliberate, not accidental, gap) — flagged as the concrete next step, not actioned blind |
| Upstream snapshot automation | ci-maintainer | #1194 (tracker; #307 closed) |
| Branch protection + required CI | strategist | CI health, #1167 — audited 2026-08-13: [BRANCH-PROTECTION.md](./docs/BRANCH-PROTECTION.md), active `main` ruleset has no required-status-checks rule; proposed list is `lint`, `lint-summary`, `unit-tests` |
| Supply chain hardening | sec-check | #1193 (tracker; #212/#301 closed) — coordinates with #1187 (package signing/SBOM is the largest hardening item, tracked there in detail) |
| Release automation | ci-maintainer | CI health, VERSIONING.md, #1186 |
| Community governance model | strategist | #1168 |
| Issue triage policy (queue actionability) | strategist | #1195 — [TRIAGE-POLICY.md](./TRIAGE-POLICY.md) drafted 08-13: milestone-only roadmap signal, verify-before-trust closure, tiered SLA |
| Package signing / SBOM | sec-check | Supply chain, #1187 |
| **Package sourcing policy (system-repos/tideforge-first + allowlist)** | strategist | #1319, #1323 (audit → #1187) |
| Bonito (Fedora 44) GA carryover | ci-maintainer | #272 — blocked on #1499 (nightly red 08-03–08-13) |
| Redfin (RHEL 10) alpha GA | ci-maintainer | #609 |
| Fedora 45 base readiness | ci-maintainer | #1171 — [FEDORA-BASE-POLICY.md](./FEDORA-BASE-POLICY.md) adopted 08-13: N+rawhide model, Fedora 45 planning sequenced after Bonito (#272) GA, not parallel |
| Adoption metrics / usage telemetry | strategist | #1174 |
| **Adoption evidence (ADOPTERS.md production entries)** | strategist | #1348 — zero public production adopters vs "Mature" claim; first entries at 2026-11-01 snapshot |
| Variant lifecycle policy (admission + Beta→Stable exit criteria) | strategist | #1196, #1175 — [VARIANT-LIFECYCLE.md](./VARIANT-LIFECYCLE.md) |

**Milestone fidelity (#1307, 2026-08-12)**: 7 of the 9 goal trackers above were
filed without being attached to the Q4 milestone (#3), so the milestone
undercounted real progress (e.g. keyless signing landing 08-10 for #1187
while the milestone still showed 0 closed). All 7 (#1174/#1175/#1186/#1187/
#1192/#1193/#1194) are now attached. Going forward: **every goal tracker must
set its milestone at creation**, not as a follow-up sweep — a tracker without
a milestone is invisible to milestone-based reporting by construction.

---

## Technical Debt Backlog

Items requiring architectural investment before they become blockers:

| Item | Issue | Priority | Effort |
|------|-------|----------|--------|
| Containerfile deduplication | #305 | P1 | L |
| Hardcoded container registries | #304 | P1 | M |
| Generated workflow cleanup | #311 | P2 | S |
| Scanner debt (#299–#302) | various | P3 | S |
| scripts/ vs build_scripts/ consolidation | #310 | P3 | M |

---

## How to Contribute

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup, build instructions, and PR process.

Priorities listed above — pick an issue labeled `good first issue` or comment on a goal you'd like to own. Contributors are welcome on docs, packaging, and architecture-track issues (#1308 seeds a starter backlog).

---

## Roadmap Governance

This roadmap is maintained by the strategist agent. Updates published after major milestones or quarterly. Propose changes via PR to this file with issue reference.

Roadmap coverage is an organization-level planning signal, not a requirement
that every repository use the same milestone structure. The Community inventory
above is the source of truth for active-repository coverage; update it when a
repository is archived, adopts a roadmap, or moves its roadmap onto the default
branch.

See [SECURITY.md](./SECURITY.md) for vulnerability reporting.

---
*Generated by strategist agent at ACMM L6. Updated 2026-08-11 for flavor equality mandate (#1315) + first external contributor (#1317). Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*
