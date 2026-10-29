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
attest *what* is being signed and pinned.

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
   tier-2/tier-3 source needs a comment in the manifest citing the gap and
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

No third-party package source currently has an active admission in this table.

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
| ~~COPR `jreilly1821/c10s-gnome-50-fresh`, `jreilly1821/c10s-gnome-50`~~ | GNOME 50 desktop stack on EL10 | `manifests/desktops/gnome.yaml` (el10) | **Migrated** (2026-09-03) | Replaced by the tunaos-packages `gnome50-el10-x86_64` build chain: the same 50.0 builds, made in GitHub Actions in a CentOS Stream 10 mock root, delivered as an OCI image of the createrepo_c output (`ghcr.io/tuna-os/tunaos-packages:gnome50-el10-x86_64`) and consumed **by digest** -- pinned in `image-versions.yaml`, bind-mounted at `/run/gnome50-el10-packages`, `unsigned: true` because the digest is the signature. Exactly the utah-packages shape, which is the maintainer directive: no more COPR, build in GitHub. Measured before the switch, the COPR entry had never taken effect anyway -- every EL10 GNOME image shipped the base's 49 (tunaOS#2324). The interim https tier at `repo.tunaos.org/gnome50/10-stream-x86_64` was dropped: that prefix was an rclone mirror of the COPR, signed with the COPR project key, so a gpgcheck=1 consumer could not install from it (run 33750514082). x86_64 only until the chain grows an aarch64 cell |
| COPR `zirconium/packages`, `yalter/niri-git`, `avengemedia/danklinux`, `avengemedia/dms-git`, `yselkowitz/wlroots-epel`, `ligenix/enterprise-cosmic` | niri itself, DankMaterialShell suite, wlroots-epel, COSMIC-on-EL10 backport | `build_scripts/desktop/niri.sh` (Fedora/EL10 niri build) | **Violation — largest gap found** | The niri desktop's core WM binary ships from an individual's git-build COPR (`yalter/niri-git`), not Fedora's own `niri` package. Six distinct COPRs feed one desktop flavor. Migrating this is a real Tideforge packaging project, not a quick fix — flagging scope honestly instead of understating it |
| COPR `@asahi/fedora-remix-branding`, `@asahi/u-boot`; CentOS Hyperscale SIG repos; OBS `home:mrkcee` | Apple Silicon (Asahi) hardware enablement: branding, u-boot, kernel | `build_scripts/overlay/asahi.sh` | Tier-3 candidate, scoped exception | Upstream Asahi Linux project's own infrastructure for hardware this org doesn't control the kernel for — narrow, hardware-gated (only applies to `*-asahi` builds), well-precedented pattern for this class of variant |
| `ppa:elementary-os/stable` | Pantheon desktop environment | `build_scripts/desktop/install-desktop.sh` (Gurnard/Pantheon) | Tier-3 candidate, scoped exception | Official upstream elementary OS PPA — the canonical source for Pantheon on Ubuntu, not a third-party mirror |
| Manifest-driven `packages.<os>.copr[]` block (`install-desktop.sh`) | General per-desktop COPR mechanism | Any desktop manifest that declares a `copr:` block | Mechanism, not a violation itself | This is *how* a desktop opts into a COPR — the entries above are what uses it. Worth a lint step (see §Enforcement) so new `copr:` blocks need a matching allowlist entry, not just code review |
| `ppa:ubuntu-asahi/ubuntu-asahi` | Asahi kernel and hardware enablement | `build_scripts/ubuntu-kernel.sh` (Asahi builds) | Tier-3 candidate, hardware-scoped | Upstream Asahi project infrastructure; applies only to Apple Silicon variants and is not a general package source |
| `ppa:avengemedia/danklinux`, `ppa:avengemedia/dms` | Niri/DankMaterialShell packages on Ubuntu | `build_scripts/desktop/niri.sh` (Ubuntu Niri) | Tier-3 candidate, variant-scoped | Supplies packages absent from the Ubuntu archive; migrate to Tideforge where feasible, or admit explicitly before adding new consumers |
| `sharpenedblade/t2linux` COPR | T2 kernel and hardware enablement | `build_scripts/overlay/t2.sh` | Tier-3 candidate, hardware-scoped | Required for Apple T2 hardware support; never enabled on non-T2 images |
| CachyOS repositories | CachyOS kernel and tuning packages | `build_scripts/overlay/cachyos.sh` | Tier-3 candidate, hardware/performance-scoped | Distribution-owned repositories used only by CachyOS overlays; pin and review independently of generic Arch packages |
| Gentoo GURU overlay | Niri and related Gentoo ebuilds | No published consumer | **Tier-3 candidate** | Community overlay supplies packages missing from Gentoo main, but no current manifest enables it; admission is required before adding a consumer. |
| openSUSE Virtualization repository | Container tooling on openSUSE | `Containerfile.opensuse` | Tier-3 candidate, base-scoped | Official openSUSE project repository, but separate from the base system repos; verify package necessity and signing before admission |

The follow-up inventory above covers the previously unreviewed apt, Arch,
openSUSE, and Gentoo paths. It found no additional AUR or OBS source used by a
published package path beyond the scoped repositories listed here. These are
classifications, not admissions: each candidate still needs maintainer/security
sign-off or migration to Tideforge before it is treated as approved.

## R2 build dependency inventory (`repo.tunaos.org`)

This section lists each `https://repo.tunaos.org/` URL that an image build reads.
It supports epic [#3470](https://github.com/tuna-os/tunaOS/issues/3470): ISO delivery without Cloudflare R2.
A build that reads no row below has no R2 package dependency.

This document keeps decisions only: which config reads a prefix, and the next step.
It holds no current state.
`scripts/r2-dependency-report.py` measures it: the package count and bytes of each prefix, and the layer sizes of the `tunaos-packages` OCI tags.
The workflow `r2-dependency-report.yml` runs the script every week and writes the result to its job summary.
A prefix has an OCI equivalent when the report lists a family tag for it.

Two tests keep the table honest.
`tests/test_r2_build_dependency_inventory.py` compares the first two columns with the URLs and the config tables found in `tunaos.toml`, `build_scripts/`, `Containerfile*` and `image-versions.yaml`.
It fails when a URL has no row, when a row has no URL, and when a reader differs.
`tests/test_r2_dependency_report.py` runs the collector against fixtures.
Delete a row in the same change that removes its URL.

The family key in a reader name selects the base.
`el10` applies to the AlmaLinux and CentOS Stream 10 images, `fedora` to Fedora, `eln` to ELN and `rawhide` to Rawhide.
`install-desktop.sh` picks the key by OS detection at build time.

The "Cell" names are `tunaos-packages` planner ids (`scripts/plan-package-factory.py` in that repository).

<!-- r2-inventory:start -->
| Prefix | Read by | Smallest next step |
|---|---|---|
| `hummingbird/20251124-$basearch/` | `desktops.cosmic.packages.hummingbird`, `desktops.gnome.packages.hummingbird`, `10-base-packages.sh` | Install only part of the repository. Record the packages one `hummingbird` build takes from it. Publish that set as an OCI repository and pin its digest. Cell `hummingbird-x86_64` writes this prefix. The datestamp is a seed label, and the factory keeps publishing into the repository (`docs/HUMMINGBIRD.md`). The report shows its size against the layer ceiling |
| `repo/10-stream-x86_64/` | `desktops.cosmic.packages.el10` | Add the Tideforge RPM cells to the OCI publisher, as tunaos-packages `docs/R2-GHCR-MIGRATION.md` lists as a follow-on. Then mount and pin the result as `gnome50-el10-packages` is |
| `repo/10/x86_64/` | `desktops.tuna.packages.el10` | Same step as the row above. Pin one digest for both only when the `Content` column of the report is equal for the two prefixes. That column hashes the sorted package checksums, so equal counts and bytes are not enough |
| `xfce/10-stream-x86_64/` | `desktops.tuna.packages.el10`, `desktops.xfce.packages.el10` | Publish the family tag of cell `xfce-el10-x86_64`. Mount it in `Containerfile.el10` next to `gnome50-el10-packages`. Pin the digest in `image-versions.yaml` |
| `xfce/44-x86_64/` | `desktops.tuna.packages.fedora` | Publish the family tag of cell `xfce-fedora-x86_64`. The Tideforge cell `tuna-desktop-fedora` writes this prefix too. Add a mount for the Fedora build in its Containerfile |
| `rpm/eln/x86_64/` | `desktops.tuna.packages.eln` | Add the Tideforge OCI lane. The report shows the size of the set |
| `rpm/rawhide/x86_64/` | `desktops.tuna.packages.rawhide` | Add the Tideforge OCI lane |
| `rpm/opensuse-tumbleweed/x86_64/` | `desktops.tuna.packages.zypper` | Add the Tideforge OCI lane. Then prove that `zypper` accepts a bind-mounted `file:` repository with `pkg_gpgcheck=1` |
| `tideforge/ubuntu/` | `desktops.cosmic.packages.apt`, `desktops.tuna.packages.apt` | APT is not an OCI client. Test an OCI-hosted flat repository as a `file:` apt source and run the build against it |
| `tideforge/debian-sid/` | `desktops.tuna.packages.apt` | Same step as `tideforge/ubuntu/` |
| `tideforge/debian-trixie/` | `desktops.tuna.packages.apt` | Same step as `tideforge/ubuntu/` |
| `pacman/arch/$arch` | `Containerfile.arch` | Pacman is not an OCI client. Test an OCI-hosted `file:` repository in the `tuna` stage |
| `gentoo/binpkgs/amd64` | `desktops.tuna.packages.emerge` | Portage is not an OCI client. Test an OCI-hosted signed gpkg `file:` binrepo in the `tuna` stage |
| `public.gpg` | `install-desktop.sh` | Commit the key with a pinned SHA-256 and import that file. People who keep the HTTP `.repo` files still need the URL |
| `tideforge/ubuntu/tideforge.gpg` | `desktops.cosmic.packages.apt`, `desktops.tuna.packages.apt` | Commit the keyring with a pinned SHA-256 and read it from the repository |
| `tideforge/debian-sid/tideforge.gpg` | `desktops.tuna.packages.apt` | Same step as the Ubuntu keyring |
| `tideforge/debian-trixie/tideforge.gpg` | `desktops.tuna.packages.apt` | Same step as the Ubuntu keyring |
<!-- r2-inventory:end -->

A digest-pinned OCI tier is not the same as an R2-free build:

- `gnome` on the EL10 family uses `gnome50-el10-packages`, pinned by digest in `image-versions.yaml`. Its table `desktops.gnome.packages.el10` reads no R2 URL. The set does not hold `highway`, which `glycin-loaders` needs. The build takes it from EPEL 10, because `10-base-packages.sh` enables EPEL and CRB. A check of this set must enable EPEL too.
- `gnome` on `hummingbird` takes GNOME from `utah-packages`, pinned by digest. It still reads R2 twice: in the base stage, and through `desktops.gnome.packages.hummingbird`, which `install-desktop.sh` enables before the desktop transaction. Both are in the first row.

Three limits apply to every row:

1. **Image updates and standalone package users.** Image updates use `uupd` and `bootc` ([`docs/USER-GUIDE.md`](docs/USER-GUIDE.md), "Updates"), not these repositories. A cutover to OCI does not block them.
   `install-desktop.sh` writes each manifest repository to `/etc/yum.repos.d` and removes only the `file://` ones ([`tests/test_a_build_only_repo_does_not_ship.py`](tests/test_a_build_only_repo_does_not_ship.py)).
   A repository that stays `https` stays reachable for a person who runs `dnf` on a booted system.
   `10-base-packages.sh` also leaves the hummingbird repository in the image.
   A repository that moves to a bind mount loses that definition.
   For each row, decide if people who use packages directly need an HTTP origin.
2. **Layer ceiling.** The ORAS lane in `tunaos-packages` rejects a layer above 9,000,000,000 bytes by default ([#937](https://github.com/tuna-os/tunaos-packages/pull/937)).
   `--max-layer-bytes` or `ORAS_MAX_LAYER_BYTES` raises it.
   The ceiling is a policy and not a measured registry limit. The report lists the layer of each OCI tag.
3. **Signatures.** An `https` repository must stay signed.
   A digest-pinned bind mount may use `unsigned: true` because the digest is the pin.
   Do not move a row to an unsigned mount without a digest.

To regenerate the measurements, run `python3 scripts/r2-dependency-report.py`.
The script needs no credentials.
Add `--offline` to print only the scan.

## Audit & transition plan

1. **Audit** — **done 2026-08-13, with the follow-up inventory added
   2026-08-31** (see "Audit findings" above; [#1323](https://github.com/tuna-os/tunaos/issues/1323)).
   Found 2 clear violations (`trixieua/morewaita-icon-theme`,
   `ublue-os/packages`/`krunner-bazaar`), one large gap (niri's 6-COPR
   dependency chain), and confirmed `negativo17`/`rpmfusion` as the
   Tier-3 allowlist candidates #1319 already named. The follow-up inventory
   classifies the apt/Arch/openSUSE/Gentoo sources above; no additional AUR or
   OBS package source was found in the published paths.
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
