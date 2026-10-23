# tunaOS Roadmap

**Last updated**: 2026-08-23 (Windows conversion channel added to Q3 + Q4 after wootc `v0.1.0-alpha.1` shipped 08-22 — #1988) | **Maintainer**: tuna-os (hanthor)

---

## Mission

Bring a modern, cloud-native experience to the Enterprise Linux Desktop. tunaOS provides OCI-based, image-mode Fedora/AlmaLinux desktops with out-of-the-box developer tooling, GPU support, and immutable infrastructure patterns.

---

## Delivery priority: one-config reference journey

The near-term outcome is a repeatable branded Yellowfin/RPM and Grouper/APT
installation from one fork-owned config. See the [delivery plan](docs/FORK-DELIVERY.md)
and [tracking epic #3474](https://github.com/tuna-os/tunaOS/issues/3474) for the
six priorities, dependencies and acceptance gates. Finish the two reference
journeys before expanding scope. Generated exact-image evidence owns test
status; a planned outcome or a green draft PR is not a shipped result.

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
> admission gate (#1270), and rebuild-based variants must satisfy the
> rebuild-config completeness precondition (#1763).

<!-- BEGIN GENERATED — scripts/gen-platform-coverage.py -->

### Platform Coverage Matrix

`scripts/gen-platform-coverage.py` makes this matrix from [`tunaos.toml`](./tunaos.toml). It records the desktop/platform combinations the image factory commits to build; it does not infer support from registry tags.

- **S — Supported:** an active cell for a standard OCI image (`build_image: true`). Runtime evidence and current failures remain visible in [MATRIX-STATUS.md](docs/MATRIX-STATUS.md).
- **E — Experimental:** an active Apple Silicon/Asahi cell. The boot chain has static verification, but the installer and real-hardware gates have not graduated it.
- **U — Unsupported:** no active image cell and no release or maintenance commitment.

| Variant | x86_64 | aarch64 | Apple Silicon (M1/M2, Asahi) |
|---|---|---|---|
| **yellowfin** | **S:** GNOME, KDE, COSMIC, Niri, XFCE, Tuna; <br>**U:** Pantheon | **S:** KDE, Niri; <br>**U:** GNOME, COSMIC, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **albacore** | **S:** GNOME, KDE, COSMIC, Niri, XFCE, Tuna; <br>**U:** Pantheon | **S:** KDE, Niri; <br>**U:** GNOME, COSMIC, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **skipjack** | **S:** GNOME, KDE, COSMIC, Niri, XFCE, Tuna; <br>**U:** Pantheon | **S:** KDE, Niri; <br>**U:** GNOME, COSMIC, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **wahoo** | **S:** GNOME, KDE, COSMIC, Tuna; <br>**U:** Niri, XFCE, Pantheon | **S:** GNOME, KDE, COSMIC; <br>**U:** Niri, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **bonito** | **S:** GNOME, KDE, COSMIC, Niri, XFCE, Tuna; <br>**U:** Pantheon | **S:** GNOME, KDE, COSMIC, Niri, XFCE; <br>**U:** Pantheon, Tuna | **E:** GNOME; <br>**U:** KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **hummingbird** | **S:** GNOME, COSMIC; <br>**U:** KDE, Niri, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **sailfin** | **S:** GNOME, KDE, COSMIC, Niri, XFCE, Tuna; <br>**U:** Pantheon | **S:** GNOME; <br>**U:** KDE, COSMIC, Niri, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **guppy** | **S:** GNOME, KDE, XFCE; <br>**U:** COSMIC, Niri, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **bonito-rawhide** | **S:** GNOME, KDE, COSMIC, Niri, XFCE, Tuna; <br>**U:** Pantheon | **S:** GNOME, KDE, COSMIC, Niri, XFCE; <br>**U:** Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **gurnard** | **S:** Pantheon; <br>**U:** GNOME, KDE, COSMIC, Niri, XFCE, Tuna | **S:** Pantheon; <br>**U:** GNOME, KDE, COSMIC, Niri, XFCE, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **grouper** | **S:** GNOME, KDE, COSMIC, XFCE, Tuna; <br>**U:** Niri, Pantheon | **S:** GNOME, KDE, XFCE; <br>**U:** COSMIC, Niri, Pantheon, Tuna | **E:** GNOME; <br>**U:** KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **marlin** | **S:** GNOME, KDE, COSMIC, Niri, XFCE, Tuna; <br>**U:** Pantheon | **S:** GNOME; <br>**U:** KDE, COSMIC, Niri, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **flounder** | **S:** KDE, XFCE, Tuna; <br>**U:** GNOME, COSMIC, Niri, Pantheon | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
| **flounder-sid** | **S:** GNOME, KDE, XFCE, Tuna; <br>**U:** COSMIC, Niri, Pantheon | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |

#### Platform parity commitment

Standard aarch64 support is a per-variant commitment, not a claim that every desktop works on every base. The flavor-equality mandate applies to cells marked **S**; it does not turn a missing package stack into a supported cell.

Apple Silicon has **2 active experimental desktop cell(s)**, all derived from enabled `*-asahi` flavors. GNOME is the only Apple Silicon target for a desktop now. KDE, COSMIC, Niri, XFCE, Pantheon, and Tuna are **U — Unsupported** on Apple Silicon, with no parity date or release commitment. Gates control expansion. First, GNOME must pass a gate for boot and session on a real Mac, and the installer must ship. Then each additional desktop needs its own enabled `-asahi` flavor and the same static and hardware evidence.

The scheduled Asahi sweep can continue to inspect old tags after a build cell is disabled. A tag or sweep entry is historical test inventory, not support. See [the hardware tiers for Asahi CI](docs/ASAHI-HARDWARE-TIERS.md) for the missing hardware evidence.

<!-- END GENERATED — scripts/gen-platform-coverage.py -->

### Proposed flavors

| Flavor | Owner | Stage | Acceptance / tracker |
|--------|-------|-------|----------------------|
| Marlin Tuna Desktop, formerly Roost (amd64, rolling) | @hanthor | Proposal, best effort; capacity confirmed and signed served `tuna-desktop` package install verified 2026-10-09 (tunaos-packages run 37881967008); experimental image build enabled; flavor renamed `roost` → `tuna` after [tuna-desktop#536](https://github.com/tuna-os/tuna-desktop/pull/536); the old `marlin:roost` tag remains frozen at its last published image and is no longer updated | Signed Tideforge `tuna-desktop` package, GDM session picker, desktop contract and VM boot, then GHCR publication and bootc switch; [#2990](https://github.com/tuna-os/tunaOS/issues/2990), [upstream #69](https://github.com/tuna-os/tuna-desktop/issues/69). One image/boot cell; no new ISO or LUKS cells. |

### Build Health

⚠️ **CORRECTION (2026-08-14)**: the prior "CI pipeline builds are green" claim is **stale** — **all 13 variant workflows were red on 08-14** (#1570, consolidated root-cause diagnosis: yellowfin, albacore, skipjack, bonito, bonito-rawhide, sailfin, guppy, grouper, marlin, flounder, flounder-sid, gurnard, hummingbird). Every failed job maps to a known root cause (no unexplained failures); fixes are fixable but stranded: the hive GitHub App **lacks `workflows` permission** (#1557), so every `.github/workflows/*.yml` fix PR is rejected at push. **CI recovery is now the Q3 critical path** (strategist #1571) — flavor equality (#1316), NVIDIA family (#1383), and release parity (#1254) staff tests all depend on a green matrix. 08-22 checkpoint decision required: STAFF CI-recovery with first-PR-by-09-01, plus maintainer grant of the App `workflows` permission.

✅ **Downloads VERIFIED WORKING** (2026-08-08): tunaos.org/download serves 179 ISOs from R2 (newest 08-07, HTTP 200 GB-scale). ✅ **GitHub Releases RESUMED 2026-08-09**: `gnome-20260809` published 11:38 UTC with assets (incl. SBOM spdx, 52.5 MB) — first release since 07-12; the `a4b147f8` fix (build-run selection, not artifact name — see #1106) and the #1147 cadence backstop are confirmed effective. #936 (tacklebox pin) is **not** a live-boot fix hold: the `image-versions.yaml` fallback was moved to the live-boot fix (tacklebox `4fa6041`) on 07-31 by #937. What is left is a separate, narrower thing — `publish-iso-groups.yml` sets its own `TACKLEBOX_SHA: a105d6d3` (61 commits older, pre-dating the appended-overlay live path), and since `publish-isos.yml` is disabled that override is the SHA every scheduled ISO is actually built with. Those ISOs boot-gate green (run 30773566969, 08-03), so this is a divergence to close deliberately with its own boot evidence, not a hold to lift.

### Community

- Pre-Q4 Baseline (2026-08): 56 stars, 3 forks (API), 0 GitHub Release downloads, 0 external production adopters (ADOPTERS.md)
- CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md published (June 2026)
- Discussions enabled
- Multi-agent development active (architect, guide, sec-check, quality, CI, outreach)
- 34+ community outreach issues filed; product-readiness gate (#563) resolved
- ⚠️ Adoption metrics untracked — no usage/telemetry data on the 179 downloadable ISOs (#1174); **plan published 08-10** ([ADOPTION-METRICS.md](./ADOPTION-METRICS.md)) — first monthly download/usage snapshot targeted 2026-11-01 (Q4 "Mature")
<!-- BEGIN GENERATED — scripts/gen-roadmap-coverage.py -->

- 🟡 **Per-repo ROADMAP coverage — 37 of 43 active repos (86%)**, measured 2026-10-22 by [`scripts/gen-roadmap-coverage.py`](./scripts/gen-roadmap-coverage.py).
  Scope is every non-archived, non-private repo in the `tuna-os` org; a repo counts as
  planned when `ROADMAP.md` is at the root of its **default branch**. Archived repos are out
  of scope because a read-only repo cannot be planned.

  **Planned (37)**: .github, bluefin-cli, blueshell, bootc-installer, bootc-migrate, bootsahi, branding, bst-ci, changelog-action, compass, corral, docs, dualcut, finupdate, fisherman, flatpak-index, gnome-hive-monitor, gtk-office-suite, hive, homebrew-tap, iced, iso-builder, mandelbrot, mariner, protota, quickcast, remora, scoop-bucket, spindle, tacklebox, Tavern, tromso, tuna-desktop, tunaOS, tunaos-packages, wootc, xfce-linux.

  Counted on a non-`main` default branch: `blueshell` on `ptyxis-port`, `bootc-installer` on `dev`, `changelog-action` on `master`, `fisherman` on `dev`, `hive` on `v4`, `iced` on `master`, `mariner` on `master` — these are the repos' own default branches, not strandings.

  **Unplanned (6)**: ccleft, hive-operator, libcosmic, PaperWM, rdocx, rust-atomicwrites. Tracked by #2820.

<!-- END GENERATED -->
- ⚪ **"First external contributor" claim retracted (#1317, corrected 2026-08-13)**: the shimonenator commits (EL10/OBS design fixing #777, image-factory completion gate) are **not** a human contribution — maintainer confirmed the account is misattributed by GitHub because the Google Antigravity agent is listed as commit author; `git log` shows `commit.author.name: antigravity` on every one of that account's commits. **Superseded 2026-08-14**: the **first external human contributions landed and merged the same day** — docs #234 (QEMU/KVM guide, dchaudhari7177) and docs #239 (Gurnard Pantheon fix, Elonon901001), both verified human GitHub accounts (created 2022, real-name profiles). These are docs-repo contributions, not core-code: bus-factor risk (#1095) for core repos is unchanged, but the onboarding loop (seed → PR → merge) is now demonstrably end-to-end, which materially strengthens the Hacktoberfest seeding case (#1537).

- 🟡 **Flavor equality mandate (08-11)**: maintainer directive #1315 — all supported flavors are equal tiers; GNOME-first framing and cadence to be retired (#1316)

---


### Per-repo roadmaps

Every active repo in the `tuna-os` org is expected to carry its own `ROADMAP.md`
at the repo root on its default branch. This file plans tunaOS the image; it is
not a place for package, installer, or ecosystem repos to state their milestones.
New repos scaffolded from the `.github` project-starter template start with one
([tuna-os/.github#13](https://github.com/tuna-os/.github/pull/13)).

Before launching a shipped product or distribution channel (Flatpak/Flathub,
binary release, or package-manager entry), its repository must have a root
`ROADMAP.md` on its default branch. This includes desktop tools, shared
infrastructure, and package-manager integrations. The release PR must link the
roadmap and its launch-blocking issues; a roadmap's presence alone does not
establish product readiness. See the [contributor release check](CONTRIBUTING.md#roadmap-before-launch).

For the three repositories named in [#2927](https://github.com/tuna-os/tunaos/issues/2927),
use their local plans and tracking issues rather than duplicating milestones here:

- [mariner roadmap](https://github.com/tuna-os/mariner/blob/master/ROADMAP.md)
  and [planning tracker #123](https://github.com/tuna-os/mariner/issues/123).
- [hive roadmap](https://github.com/tuna-os/hive/blob/v4/ROADMAP.md)
  and [planning tracker #106](https://github.com/tuna-os/hive/issues/106).
  App permission changes remain owner-only work ([#1557](https://github.com/tuna-os/tunaos/issues/1557)).
- [scoop-bucket roadmap](https://github.com/tuna-os/scoop-bucket/blob/main/ROADMAP.md)
  and [planning tracker #64](https://github.com/tuna-os/scoop-bucket/issues/64).

Coverage is **measured, not asserted**. The block in [Community](#community) is
regenerated by [`scripts/gen-roadmap-coverage.py`](./scripts/gen-roadmap-coverage.py)
— run it rather than editing the numbers by hand, and see its docstring for the
two rules that decide the count (which repos are in scope, and where the file has
to live). Do not gate pull requests on `--check`: coverage moves when *another*
repo gains a roadmap, so a byte-exact gate fails unrelated PRs. `--check-structure`
catches the thing a PR can actually break — a hand-edit inside the generated block.

See [SECURITY.md](./SECURITY.md) for vulnerability reporting.

---
*Generated by strategist agent at ACMM L6. Updated 2026-08-11 for flavor equality mandate (#1315) + first external contributor (#1317). Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*

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
| **External contributor onboarding / Hacktoberfest 2026** | guide / strategist | #1537, #1780, #2304 (#1331 closed) | 🟡 In progress — **09-02 live census: 6 contributable GFI org-wide (tunaos 3, docs 2, spindle 1), below the threshold of 8** and the 10–15 launch target; only 4 carry both `good first issue` and `help wanted`. docs fell from 9 to 2 because six curated tasks were closed by the project's own agent PRs (docs#349–352) between 08-30 and 09-02 (#2304); all three tunaos seeds are the same task type. **Zero curated GFI** in protota, wootc, gtk-office-suite, tunaos-packages, corral and iso-builder; `bootc-installer` is unblocked (#1531 closed, issues enabled) but unseeded. #1331 is closed; live trackers are #1537 (seeding rate), #1780 (composition) and #2304 (consumption). Dated census in [docs/HACKTOBERFEST-2026.md](docs/HACKTOBERFEST-2026.md) |
| Weekly boot report as build gate | ci-maintainer | #989 | 🟡 In progress |
| Outreach sequencing | strategist | #563 | ✅ Done (gate lifted) |
| Populate Q3 milestone | strategist | #562 | ✅ Done (2026-08-08, 9 issues) |
| **User-proven ISO installs roadmap** | ci-maintainer | #763 | 🟡 In progress (Phase 1 baseline dispatched #761; GUI gate #577) |
| **Apple Silicon (Asahi Linux) support** | architect / ci-maintainer | #781 | 🟡 In progress (Bonito & Grouper 36/36 verified #776; D0–D4 installer track active) |
| **Desktop parity floor (non-RPM bases)** | packaging | tunaos-packages#133, tunaos-packages#323, #1294 (successor tunaos-packages#507) | ⬜ Not started — P0 for Q4 (see #1294) |
| **Q3 checkpoint (08-22): staff or descope #272/#1123/#1093/#1094** | strategist | #1299 | 🟡 Date elapsed 08-22 — T-9 refresh 2026-08-23 (evidence updated: nvidia regression closed, Bonito T2 profile merged, wootc shipped); **decisions pending maintainer sign-off by 09-01 staff-test deadline** |
| **Flavor equality mandate (docs wording + cadence parity)** | strategist | #1315, #1254 | 🟡 In progress — catalog parity gate merged 08-11 (#1322, #1281 closed); cadence parity pending (#1316) |
| **NVIDIA flavor family (6 editions, 0 assets since 07-05)** | ci-maintainer | #1383 | 🔴 Broken — nightly overlay regressed 08-12 (#1382); 13/13 variant matrix red 08-14 (#1570) incl. nvidia cells (#1561/#1562/#1564/#1565); staff test: nightly green + gnome-nvidia assets republished by 09-01 (#1376/#1379) |
| **Windows conversion channel (wootc)** | strategist / wootc maintainer | #1988, #1958, wootc#210 | 🟡 In progress — `v0.1.0-alpha.1` shipped 2026-08-22 (five branded installers + deployer artifacts + `SHA256SUMS`, E2E-gated); nightly auto pre-releases live. wootc's own [ROADMAP](https://github.com/tuna-os/wootc/blob/main/ROADMAP.md) (refreshed 08-22) carries the v0.1.0-alpha → v1.0.0 ladder with milestone trackers M2–M5 (wootc#210–#213). Gaps closing under #1988: no Windows entry point from this repo (`README.md`/`MIGRATION.md` have zero wootc references; user ask #1958 filed 08-22 untriaged), and `winget install TunaOS.wootc` blocked on the maintainer-only `WINGET_TOKEN` secret (wootc#221). Next gate: **v0.2.0-alpha — proven on real hardware** (wootc#210) |
| **Flatpak remote ownership and production drift gate** | strategist / accountable remote owner to be named | #2922, #2921; [flatpak-index ROADMAP](https://github.com/tuna-os/flatpak-index/blob/main/ROADMAP.md) | Q3 exit requirement: record the owner and production source in both flatpak-index and docs; define publish-to-availability freshness SLO, incident ownership and rollback; measure catalog, digest, architecture and metadata drift from the served endpoint. Ownership decision precedes Q4 publisher consolidation |
| **Homebrew channel ownership, currency and validation** | strategist / tap and upstream publisher owners | #2922; [homebrew-tap#12](https://github.com/tuna-os/homebrew-tap/issues/12), [#7](https://github.com/tuna-os/homebrew-tap/issues/7); [ROADMAP](https://github.com/tuna-os/homebrew-tap/blob/main/ROADMAP.md) | Q3 exit requirement: each supported entry has an authoritative release source and working publisher or named manual owner; eligible releases reach the tap or receive a visible exception within 48 hours. Resolve publisher credentials through an org admin and explicit package admission; producer-consumer URL, checksum and install validation gates Q4 currency automation |
| **Scoop channel launch and release drift gate** | strategist / bucket and producer owners | #2922; [scoop-bucket#4](https://github.com/tuna-os/scoop-bucket/issues/4), [#14](https://github.com/tuna-os/scoop-bucket/issues/14); [ROADMAP](https://github.com/tuna-os/scoop-bucket/blob/main/ROADMAP.md) | Q3 exit requirement: name publication owner and least-privilege credential model; publish and validate bluefin-cli Windows amd64/arm64 manifest; prove clean Windows bucket-add/install/version journey; make stable-release drift beyond 24 hours owner-visible. Launch evidence precedes Q4 channel expansion |
| **Package sourcing policy (system-repos/tideforge-first + allowlist)** | strategist | #1319, #1323 | 🟡 In progress — PACKAGE-SOURCING.md merged; DNF/COPR audit done 08-13, ahead of the 08-22 checkpoint (2 violations, 6-COPR niri gap, negativo17/rpmfusion allowlist candidates confirmed — #1453); apt/AUR/OBS bases still unaudited, maintainer allowlist sign-off and Phase 2 migration still pending |

### Infrastructure release prerequisites (#2915)

These are Q3 exit gates carried into Q4 until their evidence is available;
feature completion alone does not satisfy them. Owners are the responsible
repository maintainers, coordinated by strategist. Source roadmaps and the
additional-tool audit are linked in [the release tracking rule](docs/INFRASTRUCTURE-RELEASE-GATES.md).
This table defines acceptance, not a snapshot of release availability.

| Goal | Owner | Tracking | Exit evidence |
|------|-------|----------|---------------|
| finupdate versioned updater baseline | finupdate maintainer | [release planning #65](https://github.com/tuna-os/finupdate/issues/65), #2915 | Tagged release, matching versioned OCI reference and GitHub Release; consumer pin and rollback documented |
| tacklebox versioned media baseline | tacklebox maintainer | [tacklebox#237](https://github.com/tuna-os/tacklebox/issues/237), #1192, #2915 | amd64/arm64 binaries and checksums, matching immutable container reference, unit/block/ISO/cross-platform smoke evidence, compatibility and rollback notes |
| branding versioned consumer contract | branding maintainer | [branding#7](https://github.com/tuna-os/branding/issues/7), #2915 | Tagged assets and manifest with digests/source revision, documented consumer pin, and consumer freshness check |
| remora build-verified release baseline | remora maintainer | [remora#55](https://github.com/tuna-os/remora/issues/55), [remora#44](https://github.com/tuna-os/remora/issues/44), #2915 | Generator fix exercised by a real package-install build on a shipped bootc base, stable-digest rebuild check, release carrying the fix and downstream pin review |

---

## Q4 2026 (October–December) — "Mature"

**Theme**: Enterprise readiness, community governance, ecosystem integration.

**Planning started (2026-08-08)**: Q4 milestone #3 created; tracking issue #1159 open. **All 9 Q4 goals now tracked** (#1167 branch protection, #1168 governance, #1186 release automation, #1187 package signing/SBOM). Stale dependency refs (#306/#307/#212/#301 closed) still flagged in #1159. Extended 08-08 evening: adoption metrics (#1174) and variant lifecycle policy (#1175) added as strategist-owned goals. **Update 08-13**: All stale Q4 dependency refs now resolved — Supply chain hardening re-tracked under #1193 (was #212/#301, both closed), Tacklebox decoupling under #1192 (was #306, closed), Upstream snapshot automation under #1194 (was #307, closed). Both #1192 and #1194 already existed and already carried the Q4 milestone — this was a ROADMAP linking gap, not a missing-tracker gap. #1159's recommendation #3 (refresh stale dependency refs) is complete.

**Progress note (2026-08-11)**: keyless Cosign signing + signed SBOM attestations **landed 08-10** for published ISOs and container images (#1303, #1305) — first Q4 supply-chain deliverable. Remaining scope for #1187: signed SBOMs for **every** release artifact across all flavors (blocked on Releases cadence parity #1254) and tunaos-packages artifacts. Package sourcing policy (#1319/#1323) drafted as [PACKAGE-SOURCING.md](./PACKAGE-SOURCING.md) — source inventory feeds the #1187 attestation graph in Q4.

| Goal | Owner | Dependencies |
|------|-------|--------------|
| finupdate release cadence and pin review | finupdate maintainer / strategist | #2915; Q3 baseline above, versioned builds discoverable through the Flatpak index, documented upgrade/rollback results |
| tacklebox release adoption | tacklebox maintainer / architect | #2915, [tacklebox#237](https://github.com/tuna-os/tacklebox/issues/237), #1192; Q3 baseline above, downstream immutable pin review with boot evidence and 30-day install/use feedback |
| branding consumer synchronization | branding maintainer | #2915, [branding#7](https://github.com/tuna-os/branding/issues/7); Q3 contract above, consumer synchronization verified against the pinned manifest |
| remora release qualification | remora maintainer | #2915, [remora#55](https://github.com/tuna-os/remora/issues/55); Q3 build gate above, downstream release pin checked against package-install and rebuild evidence |
| Additional infrastructure release audit | strategist | #2915; [audit scope and follow-up gates](docs/INFRASTRUCTURE-RELEASE-GATES.md#additional-tool-audit), including flatpak-index and debian-copr |
| Tacklebox decoupling | architect | #1192 (tracker; #306 closed) — audited 2026-08-14: of #306's 4 recommendations, 3 already landed (`TACKLEBOX_SHA`/`TACKLEBOX_IMAGE` version pinning via `scripts/lib/common.sh`; tacklebox runs as a `ghcr.io/tuna-os/tacklebox` container image, not a host-installed binary; the flagged `ghcr.io/hanthor/bluefin:lts` `iso.toml` reference no longer exists in this repo's own build path). Real remaining gap: **the version pin has no single source of truth** — `image-versions.yaml` (`4fa6041`, renovate-tracked) diverges from hardcoded overrides in `publish-iso-groups.yml` (`a105d6d3`) and `luks-e2e.yml` (`fd95174`, the documented floor SHA, not the current pin). Consolidating those onto one pin needs real boot evidence before merging (see Build Health note above on why `publish-iso-groups.yml`'s divergence was left as a deliberate, not accidental, gap) — flagged as the concrete next step, not actioned blind |
| Upstream snapshot automation | ci-maintainer | #1194 (tracker; #307 closed) — **live (weekly refresh PRs merging; `snapshot-upstreams.yml` runs Mondays 09:00 UTC)** |
| Branch protection + required CI | strategist | CI health, #1167 — audited 2026-08-13: [BRANCH-PROTECTION.md](./docs/BRANCH-PROTECTION.md), active `main` ruleset has no required-status-checks rule; proposed list is `lint`, `unit-tests` |
| Supply chain hardening | sec-check | #1193 (tracker; #212/#301 closed) — coordinates with #1187 (package signing/SBOM is the largest hardening item, tracked there in detail) |
| Release automation | ci-maintainer | CI health, VERSIONING.md, #1186 |
| Community governance model | strategist | #1168 — [docs/GOVERNANCE.md](./docs/GOVERNANCE.md) |
| **Flavor equality mandate** | strategist | #1315, #1316 (cadence parity #1254) |
| **tromso first stable release** | ci-maintainer | tromso#83 |
| Issue triage policy (queue actionability) | strategist | #1195 — ✅ Done ([TRIAGE-POLICY.md](./TRIAGE-POLICY.md) adopted: milestone-only roadmap signal, verify-before-trust closure, tiered SLA) |
| Package signing / SBOM | sec-check | Supply chain, #1187 |
| **Package sourcing policy (system-repos/tideforge-first + allowlist)** | strategist | #1319, #1323 (audit → #1187) |
| Bonito (Fedora 44) GA carryover | ci-maintainer | #272 — nvidia regression closed (#1499), T2 profile merged (#1256); re-scored STAFF at T-9 refresh |
| Redfin (RHEL 10) alpha GA | ci-maintainer | #609 |
| Fedora 45 base readiness | ci-maintainer | #1171 — [FEDORA-BASE-POLICY.md](./FEDORA-BASE-POLICY.md) adopted 08-13: N+rawhide model, Fedora 45 planning sequenced after Bonito (#272) GA, not parallel |
| Adoption metrics / usage telemetry | strategist | #1174 |
| **Adoption evidence (ADOPTERS.md production entries)** | strategist | #1348 — zero public production adopters vs "Mature" claim; first entries at 2026-11-01 snapshot |
| Variant lifecycle policy (admission + Beta→Stable exit criteria) | strategist | #1196, #1175, #1270, #1254, #1294, #1763 — [VARIANT-LIFECYCLE.md](./VARIANT-LIFECYCLE.md) |
| **Windows conversion channel (wootc) — beta gate + winget** | strategist / wootc maintainer | #1988, wootc#211, wootc#221 — Q3 carryover. Q4 scope: full-tier matrix green (wootc#222), BitLocker path (wootc#223), winget package live, and wootc's adoption numbers folded into the #1174 metrics snapshot and #1743 Q4 sequencing. This is the org's only adoption channel that reaches users not already running Linux |

**Distribution-channel sequencing (#2922)**: Flatpak publisher consolidation,
Homebrew scheduled currency/install checks, and Scoop catalog expansion depend
on the Q3 ownership, freshness and validation gates above. These are exit
requirements, not assertions of current channel health; use each linked local
roadmap and its release/install evidence when assessing completion.

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

Infrastructure distribution channels with near-term quarterly milestones must
also have an org goal-table row naming an accountable owner (or an explicit
ownership decision), release-currency objective, producer/consumer validation
exit evidence, and local roadmap/tracker links. Carry unfinished gates forward
as dependencies of the next quarter's automation or expansion work; a local
roadmap alone does not satisfy org planning visibility (#2922).

See [SECURITY.md](./SECURITY.md) for vulnerability reporting.

---
*Generated by strategist agent at ACMM L6. Updated 2026-08-11 for flavor equality mandate (#1315) + first external contributor (#1317). Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*
