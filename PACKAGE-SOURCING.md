# tunaOS Package Sourcing Policy

**Status**: ACTIVE — adopted 2026-08-11; migration of existing exceptions is tracked below
**Owner**: tuna-os (hanthor) / strategist
**Tracks**: [#1319](https://github.com/tuna-os/tunaos/issues/1319) (maintainer directive), [#1323](https://github.com/tuna-os/tunaos/issues/1323) (strategic framing)
**Interacts with**: Q4 supply-chain hardening ([#1193](https://github.com/tuna-os/tunaos/issues/1193), [#1187](https://github.com/tuna-os/tunaos/issues/1187)), upstream snapshot automation ([#1194](https://github.com/tuna-os/tunaos/issues/1194)), desktop parity ([#1294](https://github.com/tuna-os/tunaos/issues/1294))

---

## Purpose

Define where tunaOS packages come from. The maintainer directive
[#1319](https://github.com/tuna-os/tunaos/issues/1319) is explicit: **default to
system repos / tideforge — not PPAs, COPRs, OBS, or AUR**. Packages missing from
the base image's system repos should be built in-house; a small allowlist of
trusted third-party repos (maintainer cites the codec/Nvidia repos) is
acceptable where building in-house is not yet viable.

This policy operationalizes that directive into a written, reviewable sourcing
contract so every variant's `apt:` / `dnf:` / `zypper:` / `pacman:` / `emerge:`
manifest block has a clear governing rule — and so the Q4 supply-chain goals can
attest *what* is actually being signed and pinned.

## Sourcing tiers (preference order)

| Tier | Source | Use when |
|------|--------|----------|
| 1 | **Base system repos** (Fedora/AlmaLinux/Debian/Ubuntu/openSUSE/Arch/Gentoo defaults) | Package exists, version acceptable, no fork needed |
| 2 | **Tideforge** (in-org build service, [tideforge.org](https://tideforge.org)) | Package missing from base repos or needs tunaOS patches; build from source in-house |
| 3 | **Trusted third-party allowlist** | Genuine gap that in-house building cannot yet cover (e.g. codecs, Nvidia); see admission process below |
| ✗ | **PPAs / COPRs / OBS / AUR and other ad-hoc repos** | **Not allowed** — no exception without an allowlist entry |

## Rules

1. **System-repos-first default** — a manifest must use base system repos
   whenever the package is available there at an acceptable version. Adding a
   tier-2/tier-3 source requires a comment in the manifest citing the gap and
   the governing tracker.
2. **Build-in-house over consume-third-party** — missing packages go to
   Tideforge (or an in-org builder) before any external repo is considered.
   This generalizes the Q2 COPR-elimination win ([#436](https://github.com/tuna-os/tunaos/issues/436)) org-wide.
3. **Allowlist is narrow and reviewed** — the third-party allowlist exists for
   gaps, not convenience. Every entry needs a written justification and a
   review date; see admission process below.
4. **No silent drift** — adding a new external repo to a manifest without an
   allowlist entry is a policy violation and blocks CI/release (enforcement
   path TBD — see §Enforcement below).
5. **Variant exceptions are documented** — an exception applies to a *specific*
   variant+desktop cell, is recorded in that variant's manifest comment or
   [ROADMAP.md](./ROADMAP.md) row, and is re-evaluated at the next quarterly
   checkpoint. Non-RPM bases (sailfin/flounder/grouper/marlin/guppy) are the
   expected home of exceptions during the desktop-parity transition ([#1294](https://github.com/tuna-os/tunaos/issues/1294)).

## Third-party allowlist admission

A repo enters the allowlist only when all of the following hold:

- **Ownership & maintenance**: an identifiable owner/maintainer with a public
  issue tracker and a release process; not a single-commit/abandoned project.
- **Provenance & signing**: packages are reproducibly built or at least
  checksum/signature-verifiable at install time; prefer repos that publish
  signatures.
- **Scope**: the repo supplies exactly the gap (e.g. codecs, Nvidia drivers) —
  not a general-purpose mirror of packages available in tier 1/2.
- **History**: no known supply-chain incidents; activity within the last 6
  months.
- **Documentation**: the entry is recorded in this document's allowlist table
  with a justification, the consuming variants, and a next review date.

### Allowlist (current)

| Repo | Gap covered | Consuming variants | Added | Next review | Justification |
|------|-------------|--------------------|-------|-------------|---------------|
| *(pending maintainer sign-off)* | — | — | — | — | Candidates below come from a code audit (2026-08-13); none are formally admitted yet — that decision stays with the maintainer/sec-check per the admission criteria above |

## Audit findings (2026-08-13, ahead of the 08-22 checkpoint)

`grep`-based inventory of every `build_scripts/`/`manifests/` reference to a
COPR, PPA, OBS project, or other external repo, as it exists on `main` today.
Classified against the sourcing tiers above — **classification only, no
migration performed by this audit**.

| Source | What it provides | Where used | Classification | Notes |
|---|---|---|---|---|
| `rpmfusion` (free + nonfree) | Standard Fedora multimedia/codec/driver packages absent from Fedora's own repos | `build_scripts/10-base-packages.sh` (Bonito) | Tier-3 candidate | Fedora-ecosystem-standard third-party repo; large install base, actively maintained — the kind of repo the allowlist process exists to formalize, not eliminate |
| `negativo17` (`epel-multimedia`, `fedora-nvidia`/`epel-nvidia`) | Multimedia codecs, Nvidia drivers | `build_scripts/10-base-packages.sh`, `build_scripts/overlay/overrides/nvidia/20-nvidia.sh` | Tier-3 candidate | **This is the exact repo #1319 cited by name as acceptable** — highest-priority formal allowlist entry |
| `pkgs.tailscale.com` (vendor repo) | Tailscale VPN mesh client | `build_scripts/20-packages.sh` | Needs clarification | Repo file is written then immediately `enabled=0`'d — unclear if this definition is load-bearing or dead code; flag for the script owner, not necessarily a sourcing violation |
| ~~COPR `trixieua/morewaita-icon-theme`~~ | `morewaita-icon-theme` (GNOME icon theme) | `build_scripts/20-packages.sh` (gnome flavors) | **Migrated** | Was a single-maintainer personal COPR with no allowlist entry. Now built from upstream `somepaulo/MoreWaita` source directly — `install.sh` just copies static icon files, no build step, so cloning the real project at a pinned tag removes the third-party repackage entirely |
| ~~COPR `ublue-os/packages`~~ | `krunner-bazaar` | `build_scripts/desktop/kcm-ublue.sh` | **Migrated** | Was a regression against ROADMAP.md's Q2 goal "ublue-os/packages COPR eliminated" (#436) — this one package still pulled from it on Fedora. Unified onto the source-build path EL10 already used in the same script (a ~10s CMake KF6 plugin build), retiring the last Fedora call site of that COPR |
| COPR `zirconium/packages`, `yalter/niri-git`, `avengemedia/danklinux`, `avengemedia/dms-git`, `yselkowitz/wlroots-epel`, `ligenix/enterprise-cosmic` | niri itself, DankMaterialShell suite, wlroots-epel, COSMIC-on-EL10 backport | `build_scripts/desktop/niri.sh` (Fedora/EL10 niri build) | **Violation — largest gap found** | The niri desktop's core WM binary ships from an individual's git-build COPR (`yalter/niri-git`), not Fedora's own `niri` package. Six distinct COPRs feed one desktop flavor. Migrating this is a real Tideforge packaging project, not a quick fix — flagging scope honestly rather than understating it |
| COPR `@asahi/fedora-remix-branding`, `@asahi/u-boot`; CentOS Hyperscale SIG repos; OBS `home:mrkcee` | Apple Silicon (Asahi) hardware enablement: branding, u-boot, kernel | `build_scripts/overlay/asahi.sh` | Tier-3 candidate, scoped exception | Upstream Asahi Linux project's own infrastructure for hardware this org doesn't control the kernel for — narrow, hardware-gated (only applies to `*-asahi` builds), well-precedented pattern for this class of variant |
| `ppa:elementary-os/stable` | Pantheon desktop environment | `build_scripts/desktop/install-desktop.sh` (Gurnard/Pantheon) | Tier-3 candidate, scoped exception | Official upstream elementary OS PPA — the canonical source for Pantheon on Ubuntu, not a third-party mirror |
| Manifest-driven `packages.<os>.copr[]` block (`install-desktop.sh`) | General per-desktop COPR mechanism | Any desktop manifest that declares a `copr:` block | Mechanism, not a violation itself | This is *how* a desktop opts into a COPR — the entries above are what actually uses it. Worth a lint step (see §Enforcement) so new `copr:` blocks require a matching allowlist entry, not just code review |

**Not yet audited**: apt/AUR/OBS usage outside the entries found above (Debian/
Arch/openSUSE/Gentoo bases largely use their own package managers' extra
repos differently than DNF's COPR model) — this pass focused on the DNF/COPR
ecosystem where the volume was highest. A follow-up pass should cover
`marlin` (Arch/AUR), `flounder`/`flounder-sid` (Debian), `sailfin` (openSUSE
OBS), and `guppy` (Gentoo overlays) before the audit is called complete.

## Audit & transition plan

1. **Audit** — **done 2026-08-13, ahead of the 08-22 checkpoint** (see
   "Audit findings" above; [#1323](https://github.com/tuna-os/tunaos/issues/1323)).
   Found 2 clear violations (`trixieua/morewaita-icon-theme`,
   `ublue-os/packages`/`krunner-bazaar`), one large gap (niri's 6-COPR
   dependency chain), and confirmed `negativo17`/`rpmfusion` as the
   Tier-3 allowlist candidates #1319 already named. Not yet covered:
   apt/AUR/OBS usage on `marlin`/`flounder`/`sailfin`/`guppy` — a
   follow-up audit pass, not silently dropped.
2. **Migrate (Q3–Q4)**: move tier-3/✗ sources that have in-house equivalents
   to Tideforge; drive the 14-recipe COSMIC build-out already tracked in
   [ROADMAP.md](./ROADMAP.md) ([#964](https://github.com/tuna-os/tunaos/issues/964) COSMIC-off-PPA is the flagship migration).
3. **Attest (Q4)**: fold the final source inventory into the supply-chain
   attestation work ([#1187](https://github.com/tuna-os/tunaos/issues/1187)) so SBOMs and signing cover the *actual* source graph.

## Enforcement

- **Checkpoint gate**: the 2026-08-22 Q3 checkpoint ([#1299](https://github.com/tuna-os/tunaos/issues/1299)) reviews the audit table; policy
  violations are surfaced there.
- **CI**: `scripts/check-package-sources.py` blocks new manifest changes that
  add COPR, PPA, OBS, AUR, or an unapproved repository URL. Existing legacy
  declarations remain migration inventory until their package is available in
  Tideforge or a documented allowlist exception is approved.

---

*Drafted by the strategist agent (ACMM L6 — full mode). Review requested from
maintainer (hanthor) and sec-check before promotion from DRAFT.*
