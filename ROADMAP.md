# tunaOS Roadmap

**Last updated**: 2026-10-03 (Q3 decisions recorded; Q4 execution sequenced) | **Maintainer**: tuna-os (hanthor)

---

## Mission

Bring a modern, cloud-native experience to the Enterprise Linux Desktop. tunaOS provides OCI-based, image-mode Fedora/AlmaLinux desktops with out-of-the-box developer tooling, GPU support, and immutable infrastructure patterns.

---

## Current Status (October 2026)

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
| Hummingbird | Fedora Hummingbird (container-native bootc) | Base, GNOME, COSMIC | Experimental (see #1341) |
| Gurnard | Ubuntu 24.04 Noble | Base, Pantheon | Experimental (see #1341) |
| Wahoo | Fedora ELN (EL11 preview, rolling) | Base, GNOME, KDE, COSMIC | Experimental, dispatch-only — base/GNOME/KDE **Gate-green and published** 08-27; COSMIC builds but Promote is held behind a Gate blocked by an AWS GPU vCPU quota of 0. No working H.264/H.265 on this base (fedora-eln/eln#214, desktops #2048) |

**Status terms** follow [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md): `Stable`
means GA, `Beta` means published for testing on tunaos.org/download. This
table is the canonical per-variant status; tunaos.org wiki and blog copy must
track it. Notably **Bonito is Beta** (GA tracked in [#272](https://github.com/tuna-os/tunaos/issues/272)) — it is neither "Production" nor "Experimental".

`Stable` is an all-cells claim: every advertised desktop, edition, and
supported architecture for that variant must have the evidence ledger required
by [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md). A passing GNOME/default cell
does not promote the other cells. Promotion or a deliberate narrower support
claim must link the per-cell boot-gate, LUKS-E2E, desktop-contract, and
user-install evidence in its PR.

> **Experimental** (per maintainer #1315): Hummingbird and Gurnard/Pantheon are
> configured in `.github/build-config.yml` and building, but predate the
> admission gate in [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md) (#1196) — they
> have no named owner or acceptance criteria yet. They are tracked in
> [#1341](https://github.com/tuna-os/tunaos/issues/1341); the 2026-08-22 Q3
> checkpoint (#1299) decides staff vs. descope. README coverage is tracked in
> [#1298](https://github.com/tuna-os/tunaos/issues/1298). Hardware/kernel profiles
> (e.g. `bonito:gnome-t2`, Apple Silicon Asahi, HWE) are in-scope under the
> admission gate (#1270).

### Proposed flavors

| Flavor | Owner | Stage | Acceptance / tracker |
|--------|-------|-------|----------------------|
| Marlin Roost (amd64, rolling) | @hanthor | Proposal, best effort; capacity confirmed and signed served package install verified 2026-10-04; experimental image build enabled | Signed Tideforge package, greetd session picker, desktop contract and VM boot, then GHCR publication and bootc switch; [#2990](https://github.com/tuna-os/tunaOS/issues/2990), [upstream #69](https://github.com/hanthor/roost-desktop/issues/69). One image/boot cell; no new ISO or LUKS cells. |

### Build Health

✅ **Q3 CI crisis closed**: #1570 and the workflow-publishing blocker #1557 are closed. Live health is not copied into this roadmap: the generated [build matrix in README.md](README.md#build-status) and [matrix provenance](docs/matrix-provenance.json) are refreshed from workflow runs and remain the source of truth. This keeps a failed 2026-10-03 run visible without freezing another hand-written cell count here.

✅ **Downloads VERIFIED WORKING** (2026-08-08): tunaos.org/download serves 179 ISOs from R2 (newest 08-07, HTTP 200 GB-scale). ✅ **GitHub Releases RESUMED 2026-08-09**: `gnome-20260809` published 11:38 UTC with assets (incl. SBOM spdx, 52.5 MB) — first release since 07-12; the `a4b147f8` fix (build-run selection, not artifact name — see #1106) and the #1147 cadence backstop are confirmed effective. #936 (tacklebox pin) is **not** a live-boot fix hold: the `image-versions.yaml` fallback was moved to the live-boot fix (tacklebox `4fa6041`) on 07-31 by #937. What is left is a separate, narrower thing — `publish-iso-groups.yml` sets its own `TACKLEBOX_SHA: a105d6d3` (61 commits older, pre-dating the appended-overlay live path), and since `publish-isos.yml` is disabled that override is the SHA every scheduled ISO is actually built with. Those ISOs boot-gate green (run 30773566969, 08-03), so this is a divergence to close deliberately with its own boot evidence, not a hold to lift.

### Community

- Pre-Q4 Baseline (2026-08): 56 stars, 3 forks (API), 0 GitHub Release downloads, 0 external production adopters (ADOPTERS.md)
- CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md published (June 2026)
- Discussions enabled
- Multi-agent development active (architect, guide, sec-check, quality, CI, outreach)
- 34+ community outreach issues filed; product-readiness gate (#563) resolved
- 🟡 Adoption measurement plan published ([ADOPTION-METRICS.md](./ADOPTION-METRICS.md)); execution moved from the closed planning tracker #1174 to [#2819](https://github.com/tuna-os/tunaos/issues/2819). The first public snapshot remains due 2026-11-01; until it lands, usage and adoption are unmeasured.
- 🟡 ROADMAP coverage improving — **16/37 active authorized repos now carry a ROADMAP.md** (2026-08-14): tunaos, tromso, tacklebox, docs, xfce-linux, bluefin-cli, Tavern, corral, tunaos-packages, **bootc-installer** (ROADMAP moved to default branch via PR #14, 08-14 — #1361 resolved), bootc-migrate, dualcut, gtk-office-suite, iso-builder, protota, wootc; template merged into .github project-starter (#13). Excluded from planning scope: ubuntu + letters (**archived** 2026-08-12). Still unplanned (21 active): .github, flatpak-index, bootc-installer-asahi, branding, bst-ci, changelog-action, debian-copr, finupdate, fisherman, homebrew-tap, kde-build-meta, mandelbrot, mariner, remora, scoop-bucket, suite-common, suite-common-rust, tuna-installer-cosmic/kde/niri/xfce (#1295)
<!-- BEGIN GENERATED — scripts/gen-roadmap-coverage.py -->

- 🟡 **Per-repo ROADMAP coverage — 40 of 45 active repos (89%)**, measured 2026-09-17 by [`scripts/gen-roadmap-coverage.py`](./scripts/gen-roadmap-coverage.py).
  Scope is every non-archived, non-private repo in the `tuna-os` org; a repo counts as
  planned when `ROADMAP.md` is at the root of its **default branch**. Archived repos are out
  of scope because a read-only repo cannot be planned.

  **Planned (40)**: .github, bluefin-cli, blueshell, bootc-installer, bootc-installer-asahi, bootc-migrate, branding, bst-ci, changelog-action, corral, debian-copr, docs, dualcut, finupdate, fisherman, flatpak-index, gnome-hive-monitor, gtk-office-suite, hive, homebrew-tap, iso-builder, mandelbrot, mariner, protota, remora, scoop-bucket, spindle, suite-common, suite-common-rust, tacklebox, Tavern, tromso, tuna-installer-cosmic, tuna-installer-kde, tuna-installer-niri, tuna-installer-xfce, tunaOS, tunaos-packages, wootc, xfce-linux.

  Counted on a non-`main` default branch: `blueshell` on `ptyxis-port`, `bootc-installer` on `dev`, `changelog-action` on `master`, `fisherman` on `dev`, `hive` on `v4`, `mariner` on `master` — these are the repos' own default branches, not strandings.

  **Unplanned (5)**: compass, hive-operator, kde-build-meta, quickcast, rdocx. Tracked by #1295.

<!-- END GENERATED -->
- ⚪ **"First external contributor" claim retracted (#1317, corrected 2026-08-13)**: the shimonenator commits (EL10/OBS design fixing #777, image-factory completion gate) are **not** a human contribution — maintainer confirmed the account is misattributed by GitHub because the Google Antigravity agent is listed as commit author; `git log` shows `commit.author.name: antigravity` on every one of that account's commits. **Superseded 2026-08-14**: the **first external human contributions landed and merged the same day** — docs #234 (QEMU/KVM guide, dchaudhari7177) and docs #239 (Gurnard Pantheon fix, Elonon901001), both verified human GitHub accounts (created 2022, real-name profiles). These are docs-repo contributions, not core-code: bus-factor risk (#1095) for core repos is unchanged, but the onboarding loop (seed → PR → merge) is now demonstrably end-to-end, which materially strengthens the Hacktoberfest seeding case (#1537).

- 🟡 **Flavor equality**: the policy is accepted in [ADR 0005](docs/adr/0005-flavor-equality.md), and scheduled multi-desktop publishing landed in #1588. Q4 verification that every tier-1 flavor actually publishes on cadence is tracked by [#2550](https://github.com/tuna-os/tunaos/issues/2550).

---


### Per-repo roadmaps

Every active repo in the `tuna-os` org is expected to carry its own `ROADMAP.md`
at the repo root on its default branch. This file plans tunaOS the image; it is
not a place for package, installer, or ecosystem repos to state their milestones.
New repos scaffolded from the `.github` project-starter template start with one
([tuna-os/.github#13](https://github.com/tuna-os/.github/pull/13)).

Coverage is **measured, not asserted**. The block in [Community](#community) is
regenerated by [`scripts/gen-roadmap-coverage.py`](./scripts/gen-roadmap-coverage.py)
— run it rather than editing the numbers by hand, and see its docstring for the
two rules that decide the count (which repos are in scope, and where the file has
to live). Do not gate pull requests on `--check`: coverage moves when *another*
repo gains a roadmap, so a byte-exact gate fails unrelated PRs. `--check-structure`
catches the thing a PR can actually break — a hand-edit inside the generated block.

See [SECURITY.md](./SECURITY.md) for vulnerability reporting.

---
*Maintained by the strategist role. Updated 2026-10-03 for the Q3 exit decision and Q4 execution sequence.*

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

## Q3 2026 (July–September) — "Expand" ✅ CALENDAR CLOSED; 2 CARRYOVERS

**Theme**: Expand variant coverage, harden architecture, grow community.

**Exit decision (2026-09-30)**: the checkpoint issue #1299 was closed on
2026-09-24 without maintainer sign-off on its proposed STAFF/DESCOPE labels.
The roadmap therefore records outcomes, not retroactive approvals: RFC
lifecycle governance (#1093) and ADR coverage (#1094) completed; Bonito GA
(#272) carries into Q4 and remains Beta; Redfin delivered a reproducible local
alpha, with CI publishing explicitly out of scope because RHEL redistribution
and RHSM credentials prevent a hosted path (#1123). These are the authoritative
Q3 dispositions unless a maintainer changes product scope.

**Mid-quarter update (2026-08-10)**: Q3 milestone populated; CI green (at the time — see 08-13 correction below); **downloads verified working** (179 ISOs, newest 08-07). ⚠️ **Q3 at risk — checkpoint 2026-08-22** (#1299): 4 open strategic goals (#272 Bonito GA, #1123 Redfin alpha, #1093 RFC governance, #1094 ADR coverage) with zero movement since 08-08 while CI/ops work lands daily. ⚠️ **Desktop parity crisis** (#1294): tunaos-packages#133 audit shows 24/37 published editions are too small to contain their desktop (non-RPM bases: sailfin/flounder/grouper). GitHub Releases gap fixed 08-08 (#1106/#1147 closed, `a4b147f8`).

**Mid-quarter update 2 (2026-08-11)**: maintainer filed #1315 — **flavor equality mandate** (no GNOME-as-primary framing; all supported flavors equal tiers). This reframes desktop parity (#1294) from defect-fix to product strategy; flavor cadence parity (#1254, PR #1314) is its first deliverable. ✅ First deliverable landed 05:22Z: **browser ISO catalog parity gate merged** (#1322) — catalog generation now fails when any browser/on-demand flavor lacks a published catalog fact (#1281 closed). ~~Community signal: first external contributor (shimonenator, 08-10)~~ — **retracted 08-13** (#1317): confirmed an Antigravity-agent account, not a human contributor. #1308's starter backlog stands on its own merit regardless.

**Mid-quarter update 3 (2026-08-11)**: maintainer directive #1319 — **package sourcing policy**: default to system repos / tideforge; no PPAs/COPRs/OBS/AUR; build in-house what the base lacks, with a small trusted third-party allowlist. Second directive in 24h; elevates the Q2 COPR-elimination win (#436) into org-wide supply-chain policy (#1323).

**Correction (2026-08-13)**: the 08-10 "CI green" note above is stale. Bonito's nightly (`build-bonito.yml`) has been **red for 10/10 scheduled runs, 08-03 through 08-13** — verified via `gh run list`. Root cause is a cross-variant nvidia-overlay initramfs regression (`sr_mod`/`cdrom`/`virtio_blk` missing, `TUNAOS_NVIDIA_CONTRACT_FAIL`), independently confirmed also 100% red on Albacore, Marlin, and Yellowfin's nightlies over the same window — not Bonito-specific. Filed as #1499 (previously untracked; distinct from the closed, different-symptom #1118). Separately, `base`/arm64 jobs are failing on transient runner infra (`/libpod_lock` exhaustion), unrelated to the nvidia regression.

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| **Fix ISO downloads** | ci-maintainer | #543, #561 | ✅ Done — downloads verified working (R2, 08-07) |
| Bonito (Fedora 44) GA | ci-maintainer | #272 | 🟡 Progress — T2 bootc profile **#1256 merged 08-18**; nvidia initramfs regression **#1499 closed** (fixes #1503/#1523 merged 08-14); still Beta, GA exit per VARIANT-LIFECYCLE.md; staff test at 09-01 checkpoint review |
| Redfin (RHEL 10) alpha | ci-maintainer | #609 (closed, shipped 08-09), #1123 | 🟡 Local-build alpha shipped (systemd auto-update timer units, #609/#1182/#1219) — intentionally **not** in `.github/build-config.yml`'s CI matrix (RHEL EULA forbids redistribution + no RHSM creds on CI runners, see `scripts/get-base-image.sh`); build via `just build redfin <desktop>` or `scripts/corral-build.sh`, see [docs/rhel-setup.md](docs/rhel-setup.md). Remaining: no automated build/publish path is possible by design, so "alpha" here means local-build-verified, not downloadable |
| Ship KDE, COSMIC, Niri, XFCE variants | ci-maintainer | #285 | 🟡 Published but **desktop-completeness unverified** — 24/37 editions undersized per tunaos-packages#133 / #1294 |
| GitHub Releases page carries ISO assets | ci-maintainer | #1106 | ✅ Verified 08-09 — `gnome-20260809` published with assets; cadence resumed |
| Release-cadence health gate (no silent skip) | ci-maintainer | #1147 | 🟡 Root cause fixed 08-08 (`a4b147f8` fails on dropped release) — verify no silent skip 08-09 |
| Containerfile deduplication | architect | #305 | ✅ Done |
| Hardcoded registry → configurable | architect | #304 | ✅ Done |
| Justfile modular decomposition | architect | #308 | ✅ Done |
| Migration guide (Silverblue/Kinoite/UB) | guide | #273 | ✅ Done (MIGRATION.md) |
| mdBook → tunaos.org centralized | guide | — | ✅ Done |
| Versioning policy documented | strategist | #274 | ✅ Done (VERSIONING.md, date-based + tiers) |
| **External contributor onboarding / Hacktoberfest 2026** | guide / strategist | #2943, #2946 (#1537 closed) | 🟡 Q3 seeding target missed; the event is now live. Q4 owns pool replenishment, conversion tracking, and the zero-task repository gap. The measured census and rerun command remain in [docs/HACKTOBERFEST-2026.md](docs/HACKTOBERFEST-2026.md). |
| Weekly boot report as build gate | ci-maintainer | #989 | 🟡 In progress |
| Outreach sequencing | strategist | #563 | ✅ Done (gate lifted) |
| Populate Q3 milestone | strategist | #562 | ✅ Done (2026-08-08, 9 issues) |
| **User-proven ISO installs roadmap** | ci-maintainer | #763 | 🟡 In progress (Phase 1 baseline dispatched #761; GUI gate #577) |
| **Apple Silicon (Asahi Linux) support** | architect / ci-maintainer | #781 | 🟡 In progress (Bonito & Grouper 36/36 verified #776; D0–D4 installer track active) |
| **Desktop parity floor (non-RPM bases)** | packaging | tunaos-packages#133, tunaos-packages#323, #1294 (successor tunaos-packages#507) | ⬜ Not started — P0 for Q4 (see #1294) |
| **Q3 checkpoint (08-22): #272/#1123/#1093/#1094** | strategist | #1299 | ✅ Closed without sign-off; outcomes recorded in the Q3 exit decision above — Bonito carries to Q4, Redfin is local-only, RFC/ADR goals completed. |
| **Flavor equality mandate (docs wording + cadence parity)** | strategist | ADR 0005, #1588, #2550 | ✅ Q3 policy and scheduler work delivered — catalog parity #1322 and scheduled GNOME/KDE/XFCE/COSMIC/Niri publishing #1588 merged. Q4 verifies two consecutive healthy cycles under #2550. |
| **NVIDIA flavor family** | ci-maintainer | #1383, #1499, #2550 | 🟡 Deterministic initramfs regression fixed in Q3; downloadable-asset cadence is now part of the Q4 release-parity verification rather than a separate expired 09-01 staff test. |
| **Windows conversion channel (wootc)** | strategist / wootc maintainer | #1988, #2821, wootc ROADMAP | ✅ Q3 channel shipped `v0.1.0-alpha.1`; Q4 separates tunaOS discoverability (#2821) from release and hardware gates owned by wootc. |
| **Package sourcing policy (system-repos/tideforge-first + allowlist)** | strategist | #1319, #1323 | 🟡 In progress — PACKAGE-SOURCING.md merged; DNF/COPR audit done 08-13, ahead of the 08-22 checkpoint (2 violations, 6-COPR niri gap, negativo17/rpmfusion allowlist candidates confirmed — #1453); apt/AUR/OBS bases still unaudited, maintainer allowlist sign-off and Phase 2 migration still pending |

---

## Q4 2026 (October–December) — "Mature" 🟡 ACTIVE

**Theme**: Enterprise readiness, community governance, ecosystem integration.

**Q4 kickoff (2026-10-03)**: milestone #3 shows all 11 original planning
trackers closed, but tracker closure is not completion evidence. Several were
administratively closed after their policy or plan landed. Q4 is scored against
the artifact-level exit criteria in [Q4-MATURE-DEFINITION.md](Q4-MATURE-DEFINITION.md):
published snapshots, healthy release cycles, signed artifacts, enforced rules,
and documented lifecycle decisions.

### Execution sequence

| Window | Outcome | Owner | Evidence / live tracker |
|--------|---------|-------|-------------------------|
| **Oct 1–15** | Verify equal release cadence for GNOME, KDE, XFCE, COSMIC, Niri, and NVIDIA editions across two consecutive cycles | ci-maintainer | ADR 0005; scheduler PR #1588 merged; verification [#2550](https://github.com/tuna-os/tunaos/issues/2550) |
| **October** | Keep a diverse, claimable Hacktoberfest pool live and measure conversion instead of gross seeds | guide / strategist | [#2943](https://github.com/tuna-os/tunaos/issues/2943), zero-task repo gap [#2946](https://github.com/tuna-os/tunaos/issues/2946), [runbook](docs/HACKTOBERFEST-2026.md) |
| **By Nov 1** | Publish the first adoption/download snapshot | strategist | [#2819](https://github.com/tuna-os/tunaos/issues/2819), [ADOPTION-METRICS.md](ADOPTION-METRICS.md) |
| **By Nov 1** | Add at least one consented, verifiable production adopter or explicitly report zero | strategist / outreach | [#2909](https://github.com/tuna-os/tunaos/issues/2909), [ADOPTERS.md](ADOPTERS.md) |
| **By Nov 15** | Verify required CI, signed SBOM coverage, dependency freshness, and weekly upstream snapshots against the Q4 definition of done | ci-maintainer / sec-check | [BRANCH-PROTECTION.md](docs/BRANCH-PROTECTION.md), #1187, #1193, #1194 |
| **By Dec 30** | Apply lifecycle gates to Q3 carryovers: Bonito either meets Stable evidence or remains Beta; Redfin remains reproducible local-only unless redistribution constraints change | ci-maintainer / strategist | #272, #1123, [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md) |

### Product-channel scope

| Channel | Q4 scope | Owner |
|---------|----------|-------|
| **Windows conversion (wootc)** | tunaOS owns discoverability in `README.md` and `MIGRATION.md` under [#2821](https://github.com/tuna-os/tunaos/issues/2821). Release, hardware, BitLocker, and winget gates remain in [wootc's ROADMAP](https://github.com/tuna-os/wootc/blob/main/ROADMAP.md); closing #1988 did not transfer those deliverables into this repository. | strategist / wootc maintainer |
| **Package sourcing** | Enforce [PACKAGE-SOURCING.md](PACKAGE-SOURCING.md) and feed approved-source inventory into signing/SBOM evidence. | strategist / sec-check |
| **Governance and triage** | Keep [GOVERNANCE.md](docs/GOVERNANCE.md) and [TRIAGE-POLICY.md](TRIAGE-POLICY.md) as the operating contract; policy publication is complete, enforcement is reviewed at Q4 close. | strategist |
| **Tacklebox and upstream snapshots** | Preserve the external dependency boundary and weekly snapshot schedule; changes require the boot evidence named in the Q4 definition of done. | architect / ci-maintainer |

**Milestone fidelity**: status is derived from the exit artifacts above, not
from the closed count on milestone #3. Any new execution issue must be attached
to that milestone when created; otherwise the milestone and this roadmap will
diverge again.

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
*Maintained by the strategist role. Updated 2026-10-03 for the Q3 exit decision and Q4 execution sequence.*
