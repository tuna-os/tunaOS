# tunaOS Roadmap

**Last updated**: 2026-10-23 (Q3 outcomes closed and Q4 evidence gates refreshed — #3050) | **Maintainer**: tuna-os (hanthor)

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
| Hummingbird | Fedora Hummingbird (container-native bootc) | Base, GNOME, COSMIC, Tuna | Experimental (see #1341) |
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
| **hummingbird** | **S:** GNOME, COSMIC, Tuna; <br>**U:** KDE, Niri, XFCE, Pantheon | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna | **U:** GNOME, KDE, COSMIC, Niri, XFCE, Pantheon, Tuna |
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

## Q3 2026 (July–September) — "Expand" CLOSED

**Theme**: Expand variant coverage, harden architecture, grow community.

**Quarter close (2026-10-23)**: the 2026-08-22 checkpoint decision sheet was
never signed; tracker #1299 was closed on 2026-09-24. The final Q3 record below
therefore uses merged artifacts and repository evidence, not the unsigned
STAFF/DESCOPE recommendations. Bonito completeness and Redfin's local-build
alpha shipped, RFC/ADR governance landed, and release-stream parity is now an
enforced gate. Work that still lacks its product evidence is carried into the
Q4 gates rather than left behind an elapsed checkpoint date.

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| **Fix ISO downloads** | ci-maintainer | #543, #561 | ✅ Done — downloads verified working (R2, 08-07) |
| Bonito (Fedora 44) completeness | ci-maintainer | #272 | Delivered — #272 closed 2026-10-11 after clean scheduled builds and ISO publication were recorded. Bonito remains **Beta** in the canonical variant table until an explicit [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md) promotion records all-cell evidence |
| Redfin (RHEL 10) alpha | ci-maintainer | #609, #1123 | Delivered as a reproducible local-build alpha; #1123 closed 2026-10-11. Public CI and publication remain out of scope because RHEL redistribution and RHSM credentials are unavailable to the public runners; see [docs/rhel-setup.md](docs/rhel-setup.md) |
| Ship KDE, COSMIC, Niri, XFCE variants | ci-maintainer | #285, #1254, #2550 | Published; tier-1 stream parity is enforced by PR #2959. A partial release day now fails the cross-stream gate instead of passing silently |
| GitHub Releases page carries ISO assets | ci-maintainer | #1106 | ✅ Verified 08-09 — `gnome-20260809` published with assets; cadence resumed |
| Release-cadence health gate (no silent skip) | ci-maintainer | #1147, #2550 | Delivered — per-stream lookup failures fail closed, and PR #2959 requires every tier-1 stream to publish the same dated release with its required assets |
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
| **Desktop and release parity** | packaging / ci-maintainer | #1294, #2550 | Closed — the size-only desktop finding in #1294 was retired in favor of the release contract in #2550; PR #2959 merged 2026-10-15 with a cross-stream parity job and regression tests. Per-cell installation evidence remains a Q4 lifecycle gate |
| **Q3 checkpoint (08-22): staff or descope #272/#1123/#1093/#1094** | strategist | #1299 | Closed without a signed decision record on 2026-09-24. Final evidence: #272 and #1123 closed 2026-10-11; RFC lifecycle #1093 and ADR coverage #1094 closed 2026-09-24 |
| **Flavor equality mandate (docs wording + cadence parity)** | strategist | #1315, #1254, #2550 | Delivered for release cadence — #1254/#1316 closed and PR #2959 enforces equal dated assets across GNOME, KDE, COSMIC, Niri, and XFCE |
| **NVIDIA flavor family** | ci-maintainer | #1383 | Q3 tracker closed 2026-09-24. NVIDIA publication is judged by the same release and per-cell qualification gates as every other advertised flavor; it is not an exception to flavor equality |
| **Windows conversion channel (wootc)** | wootc maintainer | #1988; wootc#221, wootc#222 | Moved out of this repository's roadmap: #1988 was closed 2026-09-24 with the maintainer decision that wootc work belongs in `tuna-os/wootc`. The Q4 scope boundary and current external gates are recorded below |
| **Flatpak remote ownership and production drift gate** | strategist / accountable remote owner to be named | #2922, #2921; [flatpak-index ROADMAP](https://github.com/tuna-os/flatpak-index/blob/main/ROADMAP.md) | Q3 exit requirement: record the owner and production source in both flatpak-index and docs; define publish-to-availability freshness SLO, incident ownership and rollback; measure catalog, digest, architecture and metadata drift from the served endpoint. Ownership decision precedes Q4 publisher consolidation |
| **Homebrew channel ownership, currency and validation** | strategist / tap and upstream publisher owners | #2922; [homebrew-tap#12](https://github.com/tuna-os/homebrew-tap/issues/12), [#7](https://github.com/tuna-os/homebrew-tap/issues/7); [ROADMAP](https://github.com/tuna-os/homebrew-tap/blob/main/ROADMAP.md) | Q3 exit requirement: each supported entry has an authoritative release source and working publisher or named manual owner; eligible releases reach the tap or receive a visible exception within 48 hours. Resolve publisher credentials through an org admin and explicit package admission; producer-consumer URL, checksum and install validation gates Q4 currency automation |
| **Scoop channel launch and release drift gate** | strategist / bucket and producer owners | #2922; [scoop-bucket#4](https://github.com/tuna-os/scoop-bucket/issues/4), [#14](https://github.com/tuna-os/scoop-bucket/issues/14); [ROADMAP](https://github.com/tuna-os/scoop-bucket/blob/main/ROADMAP.md) | Q3 exit requirement: name publication owner and least-privilege credential model; publish and validate bluefin-cli Windows amd64/arm64 manifest; prove clean Windows bucket-add/install/version journey; make stable-release drift beyond 24 hours owner-visible. Launch evidence precedes Q4 channel expansion |
| **Package sourcing policy (system-repos/tideforge-first + allowlist)** | strategist / sec-check | #1319, #1323; [PACKAGE-SOURCING.md](PACKAGE-SOURCING.md) | Policy and cross-family audit delivered: DNF/COPR audited 2026-08-13; apt, Arch, openSUSE, and Gentoo follow-up added 2026-08-31; CI blocks newly introduced unapproved sources. Formal allowlist decisions, remaining migrations, and final source-graph attestation carry into Q4 |

---

## Q4 2026 (October–December) — "Mature"

**Theme**: Enterprise readiness, community governance, ecosystem integration.

**Evidence refresh (2026-10-23)**: milestone #3 reports 11 closed trackers and
0 open trackers, but issue closure is not completion evidence. The operative
contract remains [Q4-MATURE-DEFINITION.md](Q4-MATURE-DEFINITION.md): each claim
needs its named artifact, run, ruleset, or public snapshot. The rows below state
the gate and current evidence boundary instead of inferring success from a
closed planning issue.

| Goal | Owner | Gate / current evidence |
|------|-------|-------------------------|
| Tacklebox dependency | architect | **Pin-consolidation gate met.** `image-versions.yaml` is the single Renovate-tracked `versions.tacklebox` pin; `publish-iso-groups.yml` and `luks-e2e.yml` no longer carry divergent SHA overrides. Future bumps must preserve the documented ancestry floors and pass the live-boot and LUKS paths that consume this pin |
| Upstream snapshot automation | ci-maintainer | #1194 (tracker; #307 closed) — **live (weekly refresh PRs merging; `snapshot-upstreams.yml` runs Mondays 09:00 UTC)** |
| Branch protection + required CI | strategist | CI health, #1167 — audited 2026-08-13: [BRANCH-PROTECTION.md](./docs/BRANCH-PROTECTION.md), active `main` ruleset has no required-status-checks rule; proposed list is `lint`, `unit-tests` |
| Supply chain hardening | sec-check | #1193 (tracker; #212/#301 closed) — coordinates with #1187 (package signing/SBOM is the largest hardening item, tracked there in detail) |
| Release automation | ci-maintainer | PR #2959 enforces same-day GNOME/KDE/COSMIC/Niri/XFCE releases and required assets. Q4 exit still requires the [Q4 maturity contract](Q4-MATURE-DEFINITION.md) evidence: at least two consecutive weekly cycles plus installation qualification for every advertised release cell |
| Community governance model | strategist | #1168 — [docs/GOVERNANCE.md](./docs/GOVERNANCE.md) |
| **Flavor equality mandate** | strategist | Release-cadence dependency met by PR #2959. Promotion remains downstream of exact-image boot, installation, update, and recovery evidence for every advertised cell; a green default desktop cannot promote sibling cells |
| **tromso first stable release** | ci-maintainer | tromso#83 |
| Issue triage policy (queue actionability) | strategist | #1195 — ✅ Done ([TRIAGE-POLICY.md](./TRIAGE-POLICY.md) adopted: milestone-only roadmap signal, verify-before-trust closure, tiered SLA) |
| Package signing / SBOM | sec-check | Supply chain, #1187 |
| **Package sourcing policy (system-repos/tideforge-first + allowlist)** | strategist / sec-check | Audit complete and new-source CI enforcement active. At the 2026-11-15 Q4 health check, every candidate in [PACKAGE-SOURCING.md](PACKAGE-SOURCING.md) must have either maintainer/security sign-off with a review date or a linked migration. By Q4 close, the resulting source inventory must feed the release attestation graph |
| Bonito (Fedora 44) promotion | ci-maintainer | Q3 completeness tracker #272 is closed; Bonito remains Beta. Promotion requires the all-cell evidence ledger in [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md), including release parity and exact-image installation qualification |
| Redfin (RHEL 10) local-build alpha | ci-maintainer | Q3 outcome complete. Reproducible local builds and [docs/rhel-setup.md](docs/rhel-setup.md) are the supported scope; no public CI/publish dependency is implied |
| Fedora base readiness | ci-maintainer | #1171 — [FEDORA-BASE-POLICY.md](./FEDORA-BASE-POLICY.md) sequences the next Fedora base after Bonito's explicit lifecycle decision, not merely after closure of #272 |
| Adoption metrics / usage telemetry | strategist | [ADOPTION-METRICS.md](ADOPTION-METRICS.md) defines the data sources and monthly cadence. First snapshot: **2026-11-01**, covering October; it must report Releases/R2 downloads, stars/forks, external contributors, adoption-call conversion, and the external `ADOPTERS.md` count |
| **Adoption evidence** | strategist | Current baseline: 0 production and 0 external evaluation entries in [ADOPTERS.md](ADOPTERS.md). Q4 "Mature" floor: at least 1 consent-confirmed production adopter with a verifiable reference. Q4 funnel target: 2–3 external production/evaluation entries. Count monthly from `ADOPTERS.md`; ecosystem dependencies and project self-use do not count |
| Variant lifecycle policy (admission + Beta→Stable exit criteria) | strategist | [VARIANT-LIFECYCLE.md](./VARIANT-LIFECYCLE.md) is the gate. Release parity is a prerequisite, not sufficient evidence: every advertised cell also needs fresh boot, installation, update, and recovery results |
| **Windows conversion channel (wootc) — external scope** | wootc maintainer | Not a tunaOS Q4 completion gate after the maintainer's #1988 scope decision. In `tuna-os/wootc`, #221 remains blocked on the owner adding `WINGET_TOKEN`, then dispatching submission, passing moderation, and proving a clean install; #222 requires one full-tier matrix with no unexplained reds. BitLocker tracker #223 is closed. Include wootc figures in a tunaOS adoption snapshot only when the snapshot names wootc as its source |

**Distribution-channel sequencing (#2922)**: Flatpak publisher consolidation,
Homebrew scheduled currency/install checks, and Scoop catalog expansion depend
on the Q3 ownership, freshness and validation gates above. These are exit
requirements, not assertions of current channel health; use each linked local
roadmap and its release/install evidence when assessing completion.

**Milestone fidelity (2026-10-23)**: milestone #3 currently reports 11 closed
trackers and 0 open trackers. That metadata is useful for queue accounting, not
for the "Mature" claim: adoption entries, the 2026-11-01 snapshot, ruleset
configuration, release assets, and qualification runs remain independently
verifiable exit evidence. Assess the quarter against
[Q4-MATURE-DEFINITION.md](Q4-MATURE-DEFINITION.md), and reopen or replace a
tracker when its required evidence is absent.

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

This roadmap is maintained by the strategist agent. Propose changes via PR to
this file with an issue reference.

### Quarterly refresh cadence

The strategist coordinates a review of active repositories' roadmaps after
each calendar quarter closes. Each repository's maintainer reviews its local
priorities; contributors can prepare the documentation PR. Complete the review
within seven calendar days of quarter close: **January 7, April 7, July 7, and
October 7 (UTC)**. Also update affected rows when a major milestone lands.

Use the generated Community inventory above to find local roadmaps. At the
[weekly contributor triage](CONTRIBUTING.md#weekly-contributor-triage), check
which refreshes still need a PR or review. An overdue refresh stays on that
agenda until its PR merges; opening a tracker alone does not refresh a roadmap.

For each repository:

1. Read the roadmap on its default branch and check open issues and PRs for
   existing refresh work. Reuse one tracker per repository and link it to the
   coordination issue in this repository. File a local issue only when none
   covers the gap, with acceptance criteria scoped to one documentation PR.
2. Label the closed quarter as historical and the new quarter as current.
   Record completed goals with merged-PR or release evidence. Carry unfinished
   goals forward with their owner, tracker, blocker, and next action. A closed
   tracker must have a completed outcome or a linked successor.
3. Check claims against source issues, release records, and workflow results.
   Link generated evidence for changing counts and CI status instead of
   copying a live-status table. Keep unresolved decisions explicit; do not
   invent priorities or mark a goal complete because its quarter ended.
4. Update the review date only after checking the content. Date any retained
   historical measurements separately. Include evidence links and the local
   tracker in the PR, using that repository's required target branch and checks.
5. Link the local PR from the coordination issue. Check the org goal rows for
   affected dependencies and update them in a separate org-roadmap PR when
   needed. Close each local tracker when its refresh merges.

The initial coordination task is [#3131](https://github.com/tuna-os/tunaOS/issues/3131).
Reuse these local trackers for its three refreshes:

- [mariner#158](https://github.com/tuna-os/mariner/issues/158): separate the
  closed Q3 goals from current Q4 priorities and verify their blockers.
- [remora#144](https://github.com/tuna-os/remora/issues/144): replace the Q3
  exit/Q4 transition framing with current Q4 goals and dated Q3 outcomes.
- [fisherman#286](https://github.com/tuna-os/fisherman/issues/286): label the
  Q3 near-term section as historical and Q4 as current.

These links define the follow-up scope. Read the local trackers for progress;
completion of the coordination task does not imply those refreshes have merged.

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
*Maintained by the tunaOS strategist role. Last evidence refresh: 2026-10-23 (#3050).*
