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
| ~~COPR `jreilly1821/c10s-gnome-50-fresh`, `jreilly1821/c10s-gnome-50`~~ | GNOME 50 desktop stack on EL10 | `manifests/desktops/gnome.yaml` (el10) | **Migrated** (2026-09-03) | Replaced by the tunaos-packages `gnome50-el10-x86_64` build chain: the same 50.0 builds, made in GitHub Actions in a CentOS Stream 10 mock root, delivered as an OCI image of the createrepo_c output (`ghcr.io/tuna-os/tunaos-packages:gnome50-el10-x86_64`) and consumed **by digest** -- pinned in `image-versions.yaml`, bind-mounted at `/run/gnome50-el10-packages`, `unsigned: true` because the digest is the signature. Exactly the utah-packages shape, which is the maintainer directive: no more COPR, build in GitHub. Measured before the switch, the COPR entry had never taken effect anyway -- every EL10 GNOME image shipped the base's 49 (tunaOS#2324). The interim https tier at `repo.tunaos.org/gnome50/10-stream-x86_64` was dropped: that prefix was an rclone mirror of the COPR, signed with the COPR project key, so a gpgcheck=1 consumer could not install from it (run 33750514082). x86_64 only until the chain grows an aarch64 cell |
| COPR `zirconium/packages`, `yalter/niri-git`, `avengemedia/danklinux`, `avengemedia/dms-git`, `yselkowitz/wlroots-epel`, `ligenix/enterprise-cosmic` | niri itself, DankMaterialShell suite, wlroots-epel, COSMIC-on-EL10 backport | `build_scripts/desktop/niri.sh` (Fedora/EL10 niri build) | **Violation — largest gap found** | The niri desktop's core WM binary ships from an individual's git-build COPR (`yalter/niri-git`), not Fedora's own `niri` package. Six distinct COPRs feed one desktop flavor. Migrating this is a real Tideforge packaging project, not a quick fix — flagging scope honestly instead of understating it |
| COPR `@asahi/fedora-remix-branding`, `@asahi/u-boot`; CentOS Hyperscale SIG repos; OBS `home:mrkcee` | Apple Silicon (Asahi) hardware enablement: branding, u-boot, kernel | `build_scripts/overlay/asahi.sh` | Tier-3 candidate, scoped exception | Upstream Asahi Linux project's own infrastructure for hardware this org doesn't control the kernel for — narrow, hardware-gated (only applies to `*-asahi` builds), well-precedented pattern for this class of variant |
| `ppa:elementary-os/stable` | Pantheon desktop environment | `build_scripts/desktop/install-desktop.sh` (Gurnard/Pantheon) | Tier-3 candidate, scoped exception | Official upstream elementary OS PPA — the canonical source for Pantheon on Ubuntu, not a third-party mirror |
| Manifest-driven `packages.<os>.copr[]` block (`install-desktop.sh`) | General per-desktop COPR mechanism | Any desktop manifest that declares a `copr:` block | Mechanism, not a violation itself | This is *how* a desktop opts into a COPR — the entries above are what uses it. Worth a lint step (see §Enforcement) so new `copr:` blocks need a matching allowlist entry, not just code review |
| `ppa:ubuntu-asahi/ubuntu-asahi` | Asahi kernel and hardware enablement | `build_scripts/ubuntu-kernel.sh` (Asahi builds) | Tier-3 candidate, hardware-scoped | Upstream Asahi project infrastructure; applies only to Apple Silicon variants and is not a general package source |
| `ppa:avengemedia/danklinux`, `ppa:avengemedia/dms` | Niri/DankMaterialShell packages on Ubuntu | `build_scripts/desktop/niri.sh` (Ubuntu Niri) | Tier-3 candidate, variant-scoped | Supplies packages absent from the Ubuntu archive; migrate to Tideforge where feasible, or admit explicitly before adding new consumers |
| `sharpenedblade/t2linux` COPR | T2 kernel and hardware enablement | `build_scripts/overlay/t2.sh` | Tier-3 candidate, hardware-scoped | Required for Apple T2 hardware support; never enabled on non-T2 images |
| CachyOS repositories | CachyOS kernel and tuning packages | `build_scripts/overlay/cachyos.sh` | Tier-3 candidate, hardware/performance-scoped | Distribution-owned repositories used only by CachyOS overlays; pin and review independently of generic Arch packages |
| Gentoo GURU overlay | Niri and related Gentoo ebuilds | `manifests/desktops/niri.yaml` | Tier-3 candidate, variant-scoped | Community overlay supplies packages missing from Gentoo main; build in-house or record maintainer admission before expanding use |
| openSUSE Virtualization repository | Container tooling on openSUSE | `Containerfile.opensuse` | Tier-3 candidate, base-scoped | Official openSUSE project repository, but separate from the base system repos; verify package necessity and signing before admission |

The follow-up inventory above covers the previously unreviewed apt, Arch,
openSUSE, and Gentoo paths. It found no additional AUR or OBS source used by a
published package path beyond the scoped repositories listed here. These are
classifications, not admissions: each candidate still needs maintainer/security
sign-off or migration to Tideforge before it is treated as approved.

## R2 build dependency inventory (`repo.tunaos.org`)

This section lists each `https://repo.tunaos.org/` URL that an image build reads.
It supports epic [#3470](https://github.com/tuna-os/tunaOS/issues/3470): ISO delivery without Cloudflare R2.
A build that needs no row below has no R2 package dependency.

Measured on 2026-10-25. Each size is the sum of `<size package=…>` in the public `primary.xml` of the prefix.
For apt it is `Size:` in `Packages.gz`. For pacman it is `%CSIZE%` in the database.
The "OCI today" column comes from the anonymous tag list of `ghcr.io/tuna-os/tunaos-packages`, which holds two family tags: `gnome50-el10-x86_64` and `hummingbird-aarch64`.
"Cell" is a `tunaos-packages` planner id (`scripts/plan-package-factory.py`).

`tests/test_r2_build_dependency_inventory.py` compares the first column with the URLs in
`tunaos.toml`, `build_scripts/`, `Containerfile*` and `image-versions.yaml`.
It fails when a URL has no row, and when a row has no URL.
Delete a row in the same change that removes its URL.

<!-- r2-inventory:start -->
| Prefix | Read by | Builds | Package set and channel | OCI today | Smallest next step |
|---|---|---|---|---|---|
| `hummingbird/20251124-$basearch/` | `build_scripts/10-base-packages.sh` (base stage); `desktops.gnome` and `desktops.cosmic` `packages.hummingbird` | `hummingbird` base, gnome, cosmic (amd64 only) | x86_64: 14,353 packages, 32.27 GB. aarch64: 8,344 packages, 19.65 GB (not built by tunaOS). Frozen datestamp snapshot of a rolling base | No. Cell `hummingbird-x86_64` has no tag. Tag `hummingbird-aarch64` holds a 19.5 GB layer. GNOME 51 already comes from `utah-packages` by digest | Record which packages one `hummingbird` build installs from the snapshot. Publish only that set as an OCI repository and pin its digest. The full prefix is 3.6 times the 9 GB ORAS ceiling in tunaos-packages#937 |
| `repo/10-stream-x86_64/` | `desktops.cosmic.packages.el10` (`tunaos-cosmic`, priority 10) | `cosmic` on `yellowfin`, `albacore`, `skipjack` (and their `-hwe` and `-nvidia` flavors) | 385 packages, 1.77 GB. Rolling. Written by the Tideforge RPM publisher | No. The ORAS lane covers build-chain cells only | Add Tideforge RPM cells to the OCI publisher (tunaos-packages `docs/R2-GHCR-MIGRATION.md` lists this as a follow-on). The set fits the layer ceiling |
| `repo/10/x86_64/` | `desktops.tuna.packages.el10` (`tunaos-el10`, priority 100) | `tuna` on `yellowfin`, `albacore`, `skipjack` | 385 packages, 1.77 GB. Same count and bytes as `repo/10-stream-x86_64/` on the measure date | No | Same step as the row above. Pin one digest for both rows |
| `xfce/10-stream-x86_64/` | `desktops.xfce.packages.el10` (priority 10); `desktops.tuna.packages.el10` (`tunaos-xfce`) | `xfce` and `tuna` on `yellowfin`, `albacore`, `skipjack` | 114 packages, 38 MB. Rolling | No. Cell `xfce-el10-x86_64` publishes this prefix and has no tag | Publish the family tag for `xfce-el10-x86_64`. Mount it in `Containerfile.el10` next to `gnome50-el10-packages` and pin the digest in `image-versions.yaml` |
| `xfce/44-x86_64/` | `desktops.tuna.packages.fedora` (`tunaos-fedora`) | `tuna` on `bonito` | 11 packages, 18 MB. Rolling | No. Cell `xfce-fedora-x86_64` and the Tideforge cell `tuna-desktop-fedora` write this prefix. Neither has a tag | Publish the family tag. Mount and pin it as for the EL10 xfce row. A Fedora Containerfile mount does not exist yet |
| `rpm/eln/x86_64/` | `desktops.tuna.packages.eln` (`tunaos-eln`) | `tuna` on `wahoo` | 4 packages, 13 MB. Rolling | No. Tideforge cell only | Needs the Tideforge OCI lane. Smallest set of all |
| `rpm/rawhide/x86_64/` | `desktops.tuna.packages.rawhide` (`tunaos-rawhide`) | `tuna` on `bonito-rawhide` | 1 package, 10 MB. Rolling | No. Tideforge cell only | Needs the Tideforge OCI lane |
| `rpm/opensuse-tumbleweed/x86_64/` | `desktops.tuna.packages.zypper` (`tunaos-opensuse`) | `tuna` on `sailfin` | 22 packages, 165 MB. Rolling | No. Tideforge cell only | Needs the Tideforge OCI lane. Then prove that `zypper` accepts a bind-mounted `file:` repository with `pkg_gpgcheck=1` |
| `tideforge/ubuntu/` | `desktops.cosmic` and `desktops.tuna` `packages.apt.repos` (`condition = "ubuntu"`) | `cosmic` and `tuna` on `grouper` | 12 packages, 41 MB. Rolling signed apt index | No. APT is not an OCI client | Mount an OCI-hosted flat repository as a `file:` apt source and run the build against it. Not tested |
| `tideforge/debian-sid/` | `desktops.tuna.packages.apt.repos` (`condition = "debian-sid"`) | `tuna` on `flounder-sid` | 20 packages, 49 MB. Rolling signed apt index | No | Same step as `tideforge/ubuntu/` |
| `tideforge/debian-trixie/` | `desktops.tuna.packages.apt.repos` (`condition = "debian-trixie"`) | `tuna` on `flounder` | 4 packages, 24 MB. Rolling signed apt index | No | Same step as `tideforge/ubuntu/` |
| `pacman/arch/$arch` | `Containerfile.arch` (`tuna` stage, `[tunaos]` section) | `tuna` on `marlin` | 4 packages, 36 MB. Rolling | No. Pacman is not an OCI client | Mount an OCI-hosted `file:` repository in the `tuna` stage. Not tested |
| `public.gpg` | `build_scripts/desktop/install-desktop.sh` (zypper key import; `gpgkey=` in each signed `.repo` file) | Every build that uses a signed `https` rpm repository above | One public key | No | Commit the key with a pinned SHA-256 and import that file. Installed systems still read the URL from the `.repo` files that ship in the image |
| `tideforge/ubuntu/tideforge.gpg`, `tideforge/debian-sid/tideforge.gpg`, `tideforge/debian-trixie/tideforge.gpg` | `keyring_url` in the apt rows above | Same builds as the apt rows | Three public keyrings | No | Commit the keyrings with pinned SHA-256 values and read them from the repository |
<!-- r2-inventory:end -->

These builds already read no R2 package URL:

- `gnome` on `yellowfin`, `albacore` and `skipjack`. It uses `gnome50-el10-packages`, pinned by digest in `image-versions.yaml`. The package set is 345 packages, 521 MB.
- `gnome` on `hummingbird`. It uses `utah-packages`, pinned by digest, but the `hummingbird` base stage still reads the first row.

Three limits apply to every row:

1. **Installed systems.** `install-desktop.sh` writes each `https` repository into `/etc/yum.repos.d` and the file stays in the image.
   It removes only `file://` repositories ([`tests/test_a_build_only_repo_does_not_ship.py`](tests/test_a_build_only_repo_does_not_ship.py)).
   A cutover to a bind mount ends the build dependency. It does not end the runtime dependency.
   Booted systems read R2 for updates until a signed HTTP path replaces it.
2. **Layer ceiling.** The ORAS lane in `tunaos-packages` has no layer limit today.
   Pull request [#937](https://github.com/tuna-os/tunaos-packages/pull/937) would reject a layer above 9,000,000,000 bytes.
   Only the first row is larger.
   GHCR holds a 19.5 GB layer, so that ceiling is a policy and not a measured registry limit.
3. **Signatures.** An `https` repository must stay signed.
   A digest-pinned bind mount may use `unsigned: true` because the digest is the pin.
   Do not move a row to an unsigned mount without a digest.

Regenerate the evidence with these commands.
They need no credentials.

```bash
# Package count and bytes for one rpm prefix
curl -s "https://repo.tunaos.org/${PREFIX}/repodata/repomd.xml"
# GHCR tags and layer sizes
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:tuna-os/tunaos-packages:pull" | jq -r .token)
curl -s -H "Authorization: Bearer $TOKEN" https://ghcr.io/v2/tuna-os/tunaos-packages/tags/list
# Build cells and their R2 paths (in a tunaos-packages checkout)
python3 scripts/plan-package-factory.py --selector engine=build-chain
```

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
