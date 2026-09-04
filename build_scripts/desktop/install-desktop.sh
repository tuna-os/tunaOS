#!/usr/bin/env bash
# install-desktop.sh — Generic desktop installer driven by YAML manifests.
#
# Reads a desktop manifest from manifests/desktops/<desktop>.yaml and
# installs packages, enables services, applies version locks, and runs
# post-install hooks. Replaces per-DE shell scripts (kde.sh, cosmic.sh, etc.)
# with a single data-driven installer.
#
# Usage:
#   /run/context/build_scripts/desktop/install-desktop.sh <desktop>
#
# Requires yq (mikefarah/yq) available at YQ env var or in PATH.

set -xeuo pipefail

_TD_DESKTOP="${1:?Usage: install-desktop.sh <desktop>}"
_TD_CTX="/run/context"

# lib.sh first: manifest resolution below needs IS_DEBIAN / PKG_MGR.
source "${_TD_CTX}/build_scripts/lib.sh"

# tunaOS#1823: the stage-2 desktop dnf writes inherit an rpmdb in a LOWER
# overlay layer; rpm mmaps it and overlayfs copy-up under an mmap'd write
# corrupts it ("database disk image is malformed"). 20-packages.sh guards
# its own stage, but every desktop stage's install-desktop.sh dnf writes
# hit the same shape on the freshly imported base. Same probe as
# 20-packages.sh — no-op off the dnf path (debian/arch/opensuse/gentoo).
if [[ "${PKG_MGR:-}" == dnf ]]; then
	rawhide_rpmdb_probe
fi

# Per-distro manifest overrides: <desktop>-debian.yaml / <desktop>-arch.yaml
# beat the generic <desktop>.yaml when they exist — package names, session
# files, and display managers differ across distros (kde-debian.yaml
# carries plasma-workspace-wayland + gdm3 is gdm3 not gdm, etc.). Before
# this resolution existed the -debian/-arch manifests were dead files and
# Debian flavors silently installed the Ubuntu package set.
_TD_MANIFEST="${_TD_CTX}/manifests/desktops/${_TD_DESKTOP}.yaml"
if [[ "${IS_DEBIAN:-false}" == true && -f "${_TD_CTX}/manifests/desktops/${_TD_DESKTOP}-debian.yaml" ]]; then
	_TD_MANIFEST="${_TD_CTX}/manifests/desktops/${_TD_DESKTOP}-debian.yaml"
elif [[ "${PKG_MGR:-}" == "pacman" && -f "${_TD_CTX}/manifests/desktops/${_TD_DESKTOP}-arch.yaml" ]]; then
	_TD_MANIFEST="${_TD_CTX}/manifests/desktops/${_TD_DESKTOP}-arch.yaml"
fi

if [[ ! -f "${_TD_MANIFEST}" ]]; then
	echo "ERROR: No manifest found at ${_TD_MANIFEST}" >&2
	echo "Available desktops:"
	ls "${_TD_CTX}/manifests/desktops/"*.yaml 2>/dev/null | sed 's|.*/||;s|\.yaml||'
	exit 1
fi

# Ensure yq is available inside the container for manifest parsing.
# yq is a static binary — download once, use for the rest of the build.
YQ="${YQ:-yq}"
if ! command -v "$YQ" &>/dev/null; then
	YQ_ARCH="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
	curl -fsSL "https://github.com/mikefarah/yq/releases/download/v4.53.3/yq_linux_${YQ_ARCH}" -o /usr/bin/yq
	chmod +x /usr/bin/yq
	YQ=/usr/bin/yq
fi
printf "::group:: === install-desktop: %s ===\n" "${_TD_DESKTOP}"

# ── Determine OS section to use ──────────────────────────────────────────────
_TD_OS=""
if [[ "$PKG_MGR" == "apt" ]]; then
	_TD_OS="apt"
elif [[ "$PKG_MGR" == "pacman" ]]; then
	_TD_OS="pacman"
elif command -v zypper &>/dev/null; then
	_TD_OS="zypper"
elif command -v emerge &>/dev/null; then
	_TD_OS="emerge"
elif [[ "${IS_HUMMINGBIRD:-false}" == true ]]; then
	# Hummingbird gets its own section rather than borrowing fedora's.
	#
	# It IS a Fedora Rawhide rebuild — 30 of 38 core packages carry Rawhide's
	# exact version AND release, differing only in the .hum1 dist tag — so
	# routing it to el10, which lib.sh's substring test does, is a
	# misclassification. But `fedora` is equally wrong, and that is the part
	# worth stating: of the 58 packages the GNOME manifest installs on a
	# Fedora-family host, Hummingbird's 3384-package repository ships exactly
	# ONE (avahi). No cairo, no wayland, no mesa, no gtk, no pipewire; its own
	# SBOM lists 444 names, none of them desktop. It publishes a base OS and
	# no desktop, so the fedora: section would fail exactly as el10: did —
	# just further along. Measured in tuna-os/tunaos-packages#250.
	#
	# Rawhide's own binaries cannot be substituted either: glibc 2.43 vs 2.44
	# (637 Rawhide binaries need GLIBC_2.44), libxml2.so.16 vs .so.2,
	# libcrypto.so.3 vs .so.4. They have to be rebuilt against Hummingbird's
	# buildroot, which is what the hummingbird: manifest sections point at.
	_TD_OS="hummingbird"
elif [[ "${IS_ELN:-false}" == true ]]; then
	# ELN gets its own section for the same reason hummingbird does, and the
	# measurement is the argument. Of the 52 packages the fedora: list
	# installs, ELN's repos carry 42 (`dnf repoquery` against the pinned
	# eln-bootc digest, 2026-08-25) — so `fedora` is close, but the ten
	# misses are a strict `dnf install` away from failing the build:
	#
	#   NetworkManager-{openconnect,ssh,vpnc}-gnome, evince-previewer,
	#   evince-thumbnailer, gnome-backgrounds, gnome-user-share, gvfs-afc,
	#   qadwaitadecorations-qt5, totem-video-thumbnailer
	#
	# and `el10` is worse than close: that section is a GNOME 50 COPR
	# backport for a base that ships GNOME 48, while ELN's own AppStream
	# carries GNOME 51~beta. Routing ELN there would enable a c10s COPR on an
	# EL11 buildroot to install packages ELN already has, newer.
	#
	# What the eln: section supplies is therefore the fedora list minus those
	# ten names, aliased rather than restated — see the manifest.
	_TD_OS="eln"
elif [[ "$IS_FEDORA" == true ]]; then
	_TD_OS="fedora"
else
	_TD_OS="el10"
fi

# Check for CachyOS-specific section (Arch derivative with extra repos)
if [[ "${_TD_OS}" == "pacman" ]] && [[ -f /etc/cachyos-release ]]; then
	# If the manifest has a cachyos section, merge its repos/packages
	_TD_CACHYOS="cachyos"
fi

echo "Installing ${_TD_DESKTOP} desktop (OS section: ${_TD_OS})..."

# ── APT path ─────────────────────────────────────────────────────────────────

# ── Zypper path ────────────────────────────────────────────────────────────────
# The zypper section is either a plain package list (!!seq) or a map with
# .packages and an optional .display_manager — the same two shapes the apt
# section supports, and the shape el10/fedora already use. XFCE needs the map
# form: openSUSE's XFCE ships lightdm, while the manifest's top-level
# display_manager is gdm (correct for Fedora/EL10), so a list-shaped section
# left sailfin:xfce enabling a DM that is not installed. safe_enable no-ops on
# a missing unit and the graphical.target.wants link is guarded by the unit
# file existing, so the image booted to graphical.target with no display
# manager at all — no error, no greeter.
#
# Branch on the node kind rather than relying on `.packages.zypper.packages[]
# // .packages.zypper[]`: mikefarah yq errors on indexing a sequence with a
# string, and `//` rescues a null, not an error.
if [[ "${_TD_OS}" == "zypper" ]]; then
	if [[ "$($YQ -r '.packages.zypper | type' "${_TD_MANIFEST}" 2>/dev/null)" == "!!map" ]]; then
		readarray -t _TD_ZYPPER_PKGS < <($YQ -r '.packages.zypper.packages[]' "${_TD_MANIFEST}" 2>/dev/null || true)
	else
		readarray -t _TD_ZYPPER_PKGS < <($YQ -r '.packages.zypper[]' "${_TD_MANIFEST}" 2>/dev/null || true)
	fi
	# A zypper base that parsed no packages would build a desktop-flavored
	# image with no desktop in it and still exit 0 — the failure mode that
	# shipped sailfin. Match the pacman/apt paths and fail loudly instead.
	if ((${#_TD_ZYPPER_PKGS[@]} == 0)); then
		echo "ERROR: no zypper packages parsed from ${_TD_MANIFEST}" >&2
		echo "       This would yield an image tagged ${_TD_DESKTOP} with no desktop in it." >&2
		exit 1
	fi
	# Refresh before installing, and retry by refreshing again.
	#
	# #1011 read the 404 storm on sailfin —
	#   Preloading: libwebpmux3-1.6.0-2.3.x86_64.rpm [Error: 404 ...]
	# — as manifests pinning versions that Tumbleweed had rotated out. The
	# zypper sections pin nothing: gnome 62 packages, kde 47, xfce 37,
	# cosmic 41, niri 40, zero version constraints among them.
	#
	# The actual mechanism is stale metadata. This stage installs with the
	# repo index cached by the BASE stage, and layer caching makes that index
	# arbitrarily old — while Tumbleweed deletes superseded builds within
	# days. zypper therefore resolves an exact version the mirrors no longer
	# carry, and every mirror 404s because none of them has it. Nothing is
	# wrong with the package list; the index describing it has expired.
	#
	# So a plain retry is useless here — retrying the same stale resolution
	# 404s identically. Refreshing between attempts is what fixes it. The
	# `|| true` on refresh keeps a single unreachable mirror from failing the
	# build before the install has even been tried.
	_td_zypper_install_retry() {
		local attempt=1
		until zypper --non-interactive install -y "$@"; do
			if ((attempt >= 3)); then
				echo "ERROR: zypper install failed after ${attempt} attempts" >&2
				return 1
			fi
			echo "zypper install attempt ${attempt} failed; refreshing metadata and retrying" >&2
			zypper --non-interactive --gpg-auto-import-keys refresh --force || true
			attempt=$((attempt + 1))
			sleep $((attempt * 5))
		done
	}
	zypper --non-interactive --gpg-auto-import-keys refresh || true
	_td_zypper_install_retry "${_TD_ZYPPER_PKGS[@]}"

	# Re-assert the Packman multimedia stack AFTER the desktop transaction
	# (tunaOS#1832). The base stage installs Packman's full-codec ffmpeg with
	# --allow-vendor-change, but the desktop install can pull a NEWER
	# openSUSE-vendor ffmpeg through a dependency bump — vendor stickiness
	# does not survive a version-forced upgrade — and openSUSE's build
	# compiles the h264/hevc/vc1 decoders out. Every sailfin desktop then
	# failed the codec baseline deterministically:
	#
	#   ffmpeg cannot decode h264 — a free/crippled libavcodec is installed
	#   configure --disable-decoder='h264,hevc,vc1,prores_raw,vvc'
	#
	# The dup is a no-op when Packman already owns the stack, so this is
	# idempotent, and the codec baseline in verify-desktop-experience.sh
	# remains the assertion that it worked.
	if zypper --non-interactive repos packman-essentials >/dev/null 2>&1; then
		attempt=0
		until zypper --non-interactive dup --from packman-essentials --allow-vendor-change; do
			attempt=$((attempt + 1))
			if ((attempt >= 3)); then
				echo "ERROR: could not re-assert Packman multimedia after the desktop install (tunaOS#1832)" >&2
				exit 1
			fi
			zypper --non-interactive --gpg-auto-import-keys refresh --force || true
			sleep $((attempt * 5))
		done

		# The dup is VERSION-driven, and that is not enough — but the first
		# forced-install attempt (run 32047331620 follow-up, 32052422745)
		# also taught us WHICH packages matter. The Packman codec model on
		# openSUSE keeps the distro's ffmpeg/gstreamer packages
		# openSUSE-vendored; full decoding comes from Packman's LIBRARY
		# complements. Essentials carries NO package literally named
		# `ffmpeg` (measured against the live index 2026-08-17: only
		# ffmpeg-3..8 and libavcodecNN), so forcing the openSUSE names was
		# a no-op: 'ffmpeg' not found in package names → "already
		# installed" → Nothing to do → crippled decoders survive.
		#
		# The invariant: every installed libavcodecNN (the soname the
		# ffmpeg binary actually loads decoders from) plus the
		# gstreamer *-codecs complements and vlc-codecs must be
		# Packman-vendored. Force any that are not, downgrades allowed.
		# 'ffmpeg-[0-9]' also covers the CLI: openSUSE's versioned ffmpeg-N
		# packages exist in both repos, and only Packman's build ships the
		# h264/hevc decoders — an openSUSE-vendored ffmpeg-8 is the same
		# crippled stack with a working library underneath it. (The
		# unversioned `ffmpeg` name is deliberately not installed at all —
		# see Containerfile.opensuse; if a dependency ever drags it in, the
		# availability gate below surfaces it as TUNAOS_CODEC_GAP because
		# Packman publishes no package of that name.)
		_td_pm_lost=()
		while IFS= read -r _td_pkg; do
			[[ -n "$_td_pkg" ]] || continue
			rpm -q --qf '%{VENDOR}\n' "$_td_pkg" | grep -qi packman ||
				_td_pm_lost+=("$_td_pkg")
		done < <(rpm -qa --qf '%{NAME}\n' 'libavcodec*' 'ffmpeg-[0-9]' 'ffmpeg' 2>/dev/null)
		for _td_pkg in gstreamer-plugins-bad-codecs \
			gstreamer-plugins-ugly-codecs vlc-codecs; do
			if ! rpm -q "$_td_pkg" >/dev/null 2>&1; then
				# The complement is not installed at all — that is the same
				# hole with a different spelling.
				_td_pm_lost+=("$_td_pkg")
			elif ! rpm -q --qf '%{VENDOR}\n' "$_td_pkg" | grep -qi packman; then
				_td_pm_lost+=("$_td_pkg")
			fi
		done
		# A soname generation Packman has not published cannot be forced
		# from packman-essentials. During a Tumbleweed ffmpeg major
		# transition the openSUSE build is briefly the ONLY build — run
		# 32068513822 killed all five amd64 desktops because openSUSE
		# shipped libavcodec63 (ffmpeg 9) while Packman's newest is
		# libavcodec62, so the forced install was a no-op and the assert
		# below (correctly) refused to hope. Failing the image for that
		# gap goes red on something no change in this repository can fix:
		# force what Packman offers, surface the rest with a greppable
		# marker, and let the codec baseline in
		# verify-desktop-experience.sh keep asserting that the primary
		# ffmpeg stack still decodes h264 (it links the Packman soname).
		_td_force=()
		for _td_pkg in "${_td_pm_lost[@]}"; do
			if zypper --non-interactive search --match-exact --type package \
				--repo packman-essentials "$_td_pkg" >/dev/null 2>&1; then
				_td_force+=("$_td_pkg")
			else
				echo "TUNAOS_CODEC_GAP: ${_td_pkg} is not Packman-vendored and packman-essentials publishes no build to force; its consumers decode with openSUSE's crippled build until Packman catches up (tunaOS#1832)"
			fi
		done
		if ((${#_td_force[@]} > 0)); then
			echo "Packman must own the codec libraries; forcing: ${_td_force[*]} (tunaOS#1832)"
			attempt=0
			until zypper --non-interactive install -y --oldpackage \
				--allow-vendor-change --force-resolution \
				--from packman-essentials "${_td_force[@]}"; do
				attempt=$((attempt + 1))
				if ((attempt >= 3)); then
					echo "ERROR: could not force the codec libraries back to Packman (tunaOS#1832)" >&2
					exit 1
				fi
				zypper --non-interactive --gpg-auto-import-keys refresh --force || true
				sleep $((attempt * 5))
			done
			# Assert, don't hope: a second no-op here means the force above
			# quietly failed and the codec baseline will fail later anyway —
			# fail HERE, where the zypper output is still on screen.
			for _td_pkg in "${_td_force[@]}"; do
				rpm -q --qf '%{VENDOR}\n' "$_td_pkg" | grep -qi packman || {
					echo "ERROR: ${_td_pkg} still not Packman-vendored after the forced install (tunaOS#1832)" >&2
					exit 1
				}
			done
		fi
	fi
fi

# ── Emerge path ────────────────────────────────────────────────────────────────
if [[ "${_TD_OS}" == "emerge" ]]; then
	readarray -t _TD_EMERGE_PKGS < <($YQ -r '.packages.emerge[]' "${_TD_MANIFEST}" 2>/dev/null || true)
	# Same guard as the zypper/pacman/apt paths, and for the same reason: a
	# desktop with no emerge section would otherwise install nothing and still
	# exit 0, publishing a desktop-flavored image with no desktop in it. That
	# is what shipped as flounder:niri (tunaOS#915). It is a live risk on
	# Gentoo specifically — niri and cosmic have no ebuilds in the main tree,
	# so their emerge sections are deliberately absent, and the only thing
	# stopping guppy:niri from repeating flounder:niri is that nobody has
	# declared the flavor. Fail loudly instead of relying on that.
	if ((${#_TD_EMERGE_PKGS[@]} == 0)); then
		echo "ERROR: no emerge packages parsed from ${_TD_MANIFEST}" >&2
		if [[ "${_TD_DESKTOP}" == "niri" || "${_TD_DESKTOP}" == "cosmic" ]]; then
			echo "       Gentoo has no ${_TD_DESKTOP} ebuilds in the main tree;" >&2
			echo "       do not declare guppy:${_TD_DESKTOP} until an upstream or" >&2
			echo "       explicitly maintained overlay provides and tests the packages." >&2
		fi
		echo "       This would yield an image tagged ${_TD_DESKTOP} with no desktop in it." >&2
		exit 1
	fi

	# Binhost version lock — tuna-os/tunaOS#1802. getbinpkg is configured
	# (Containerfile.gentoo, base stage) but only substitutes a binary on an
	# exact CPV match; a bare `emerge --sync` races ahead of the binhost's own
	# rebuild cadence for fast-moving categories like kde-plasma, so nothing
	# in the anchor package's dependency chain (packages.emerge[0] — the
	# meta/-light/-4-meta package for kde/gnome/xfce) gets served as binary.
	# Best-effort and fails open; see the script header for the full story.
	"${_TD_CTX}/build_scripts/desktop/gentoo-binhost-version-lock.sh" \
		"${_TD_EMERGE_PKGS[0]%%/*}" "${_TD_EMERGE_PKGS[@]}" || true

	emerge --verbose "${_TD_EMERGE_PKGS[@]}"
fi

# Add a Launchpad PPA as a deb822 source, WITHOUT add-apt-repository.
#
# add-apt-repository cannot be used here, and the reason is a collision between
# two things this repo does deliberately:
#
#   * 90-image-info.sh rewrites VERSION_CODENAME in os-release to the variant's
#     fish codename, and keeps UBUNTU_CODENAME as the real Launchpad suite.
#   * add-apt-repository resolves the suite through python-apt's aptsources,
#     which looks the codename up in /usr/share/python-apt/templates/Ubuntu.info.
#
# So on a branded image it dies:
#
#   aptsources.distro.NoDistroTemplateException: Error: could not find a
#   distribution template for Ubuntu/Chelidonichthys lucerna
#
# That is tunaOS#1014 — gurnard:pantheon, whose desktop exists only in
# ppa:elementary-os/stable and nowhere in the Ubuntu archive, so the failure is
# total rather than cosmetic. There is no flag to tell add-apt-repository which
# suite to use; it always asks os-release.
#
# A PPA is a fully specified URL shape, so write the source ourselves from
# UBUNTU_CODENAME. build_scripts/desktop/niri.sh already does exactly this for
# the avengemedia PPAs, with the same comment about UBUNTU_CODENAME — this is
# that knowledge moved somewhere every manifest-declared PPA gets it.
#
# The signing key is fetched armored and referenced as .asc rather than
# dearmored, so no gnupg is needed in the image.
_td_add_ppa() {
	local ppa="$1"
	local spec="${ppa#ppa:}"
	local owner="${spec%%/*}"
	local name="${spec#*/}"
	# `ppa:owner` with no archive means owner's default archive, named "ppa".
	[[ "$name" == "$spec" ]] && name="ppa"

	local suite=""
	if [[ -r /etc/os-release ]]; then
		# shellcheck disable=SC1091
		suite="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-}")"
	fi
	if [[ -z "$suite" ]]; then
		echo "ERROR: ${_TD_MANIFEST} declares PPA ${ppa}, but this image's os-release has no" >&2
		echo "       UBUNTU_CODENAME. VERSION_CODENAME is the TunaOS fish name and cannot" >&2
		echo "       name a Launchpad suite. Every package that exists only in that PPA" >&2
		echo "       would be silently missing." >&2
		return 1
	fi

	local fp
	fp="$(curl -fsSL --retry 3 "https://api.launchpad.net/devel/~${owner}/+archive/ubuntu/${name}" |
		grep -o '"signing_key_fingerprint": *"[^"]*"' | head -1 | cut -d'"' -f4 || true)"
	if [[ -z "$fp" ]]; then
		echo "ERROR: could not read a signing key fingerprint for ${ppa} from Launchpad." >&2
		return 1
	fi

	install -d -m 0755 /etc/apt/keyrings
	local keyring="/etc/apt/keyrings/${owner}-${name}.asc"
	curl -fsSL --retry 3 \
		"https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${fp}" -o "$keyring"
	grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$keyring" || {
		echo "ERROR: key fetched for ${ppa} (${fp}) is not an armored PGP key." >&2
		return 1
	}
	chmod 0644 "$keyring"

	cat >"/etc/apt/sources.list.d/${owner}-${name}.sources" <<EOF
Types: deb
URIs: https://ppa.launchpadcontent.net/${owner}/${name}/ubuntu
Suites: ${suite}
Components: main
Signed-By: ${keyring}
EOF
	echo "Added PPA ${ppa} for suite ${suite}"
}

if [[ "${_TD_OS}" == "apt" ]]; then
	# The apt section is either a plain package list (!!seq) or a map with
	# .packages, optional .ppa, and optional .repos (Tideforge or other
	# custom apt repos — tunaOS#964). Branch on the type explicitly:
	# mikefarah yq has NO if/then/else and indexing a seq with a string is
	# an error, so the old one-liners either always failed (PPA count: type
	# is "!!map", never "object") or errored and were swallowed by `|| true`
	# (package list) — every apt flavor shipped a desktop-less image that
	# still passed CI.
	_TD_APT_TYPE=$($YQ -r '.packages.apt | type' "${_TD_MANIFEST}")

	# Handle custom apt repos (e.g. Tideforge — tunaOS#964).
	# Each entry: name, uri, suite, keyring_url, optional condition.
	# Added BEFORE PPAs so Tideforge priority beats third-party sources.
	_TD_APT_REPO_COUNT=0
	if [[ "${_TD_APT_TYPE}" == "!!map" ]]; then
		_TD_APT_REPO_COUNT=$($YQ -r '.packages.apt.repos | length // 0' "${_TD_MANIFEST}" 2>/dev/null || echo 0)
	fi
	for ((i = 0; i < _TD_APT_REPO_COUNT; i++)); do
		_TD_AR_NAME=$($YQ -r ".packages.apt.repos[$i].name" "${_TD_MANIFEST}")
		_TD_AR_URI=$($YQ -r ".packages.apt.repos[$i].uri" "${_TD_MANIFEST}")
		_TD_AR_SUITE=$($YQ -r ".packages.apt.repos[$i].suite" "${_TD_MANIFEST}")
		_TD_AR_KEYRING=$($YQ -r ".packages.apt.repos[$i].keyring_url" "${_TD_MANIFEST}")
		_TD_AR_COND=$($YQ -r ".packages.apt.repos[$i].condition // \"\"" "${_TD_MANIFEST}")
		# Only add repo if condition matches (e.g. "ubuntu" only on Ubuntu)
		if [[ -z "${_TD_AR_COND}" ]] || [[ "$IS_UBUNTU" == true && "${_TD_AR_COND}" == "ubuntu" ]]; then
			install -d -m 0755 /etc/apt/keyrings
			_TD_AR_KEYRING_PATH="/etc/apt/keyrings/${_TD_AR_NAME}.gpg"
			curl -fsSL --retry 3 "${_TD_AR_KEYRING}" -o "${_TD_AR_KEYRING_PATH}"
			chmod 0644 "${_TD_AR_KEYRING_PATH}"
			cat >"/etc/apt/sources.list.d/${_TD_AR_NAME}.list" <<EOF
deb [signed-by=${_TD_AR_KEYRING_PATH}] ${_TD_AR_URI} ${_TD_AR_SUITE}
EOF
			echo "Added apt repo ${_TD_AR_NAME} -> ${_TD_AR_URI}"
			# The new repo's index has to be visible to the install below.
			apt-get update -qq
		fi
	done

	# Handle PPAs (Ubuntu only — Debian uses native repos)
	_TD_PPA_COUNT=0
	if [[ "${_TD_APT_TYPE}" == "!!map" ]]; then
		_TD_PPA_COUNT=$($YQ -r '.packages.apt.ppa | length' "${_TD_MANIFEST}")
	fi
	for ((i = 0; i < _TD_PPA_COUNT; i++)); do
		_TD_PPA_REPO=$($YQ -r ".packages.apt.ppa[$i].repo" "${_TD_MANIFEST}")
		_TD_PPA_COND=$($YQ -r ".packages.apt.ppa[$i].condition" "${_TD_MANIFEST}")
		# Only add PPA if condition matches (e.g. "ubuntu" only on Ubuntu)
		if [[ -z "${_TD_PPA_COND}" ]] || [[ "$IS_UBUNTU" == true && "${_TD_PPA_COND}" == "ubuntu" ]]; then
			_td_add_ppa "${_TD_PPA_REPO}"
			# The new repo's index has to be visible to the install below.
			apt-get update -qq
		fi
	done

	# Install packages (under .packages.apt[] or .packages.apt.packages[])
	_TD_PKGS=()
	case "${_TD_APT_TYPE}" in
	"!!map") readarray -t _TD_PKGS < <($YQ -r '.packages.apt.packages // [] | .[]' "${_TD_MANIFEST}") ;;
	"!!seq") readarray -t _TD_PKGS < <($YQ -r '.packages.apt[]' "${_TD_MANIFEST}") ;;
	esac
	if ((${#_TD_PKGS[@]} > 0)); then
		pkg_install "${_TD_PKGS[@]}"
	elif [[ "${_TD_APT_TYPE}" != "!!null" ]]; then
		# Fail loudly: an apt section exists but nothing parsed out of it.
		# Silence here is exactly how the desktop-less-image bug shipped.
		echo "ERROR: ${_TD_MANIFEST} has a packages.apt section but no packages parsed" >&2
		exit 1
	fi
	# Enable display manager
	_TD_DM=$($YQ -r '.display_manager' "${_TD_MANIFEST}")
	if [[ -n "${_TD_DM}" ]]; then
		systemctl enable "${_TD_DM}" || true
	fi
	printf "::endgroup::\n"
	# Deliberately NO `exit 0` here, for the same reason the pacman branch
	# below says so. Returning early skips everything shared that follows:
	# disable_desktop_files, post_install hooks, post_install_inline, the
	# curated experiences/<desktop>/files overlay, and the installation of the
	# desktop-experience contract (tunaOS#959).
fi

# ── Pacman path (Arch Linux / CachyOS) ───────────────────────────────────────
if [[ "${_TD_OS}" == "pacman" ]]; then
	# Install CachyOS repos if applicable
	if [[ -n "${_TD_CACHYOS:-}" ]]; then
		_TD_REPO_COUNT=$($YQ -r ".packages.${_TD_CACHYOS}.repos | length // 0" "${_TD_MANIFEST}" 2>/dev/null)
		for ((i = 0; i < _TD_REPO_COUNT; i++)); do
			_TD_REPO_NAME=$($YQ -r ".packages.${_TD_CACHYOS}.repos[$i].name" "${_TD_MANIFEST}")
			_TD_REPO_URL=$($YQ -r ".packages.${_TD_CACHYOS}.repos[$i].url" "${_TD_MANIFEST}")
			if ! grep -q "\\[${_TD_REPO_NAME}\\]" /etc/pacman.conf; then
				printf '\n[%s]\nServer = %s\n' "${_TD_REPO_NAME}" "${_TD_REPO_URL}" >>/etc/pacman.conf
			fi
		done
		pacman -Sy --noconfirm
		# Install CachyOS-specific packages
		readarray -t _TD_CACHY_PKGS < <($YQ -r ".packages.${_TD_CACHYOS}.packages[]" "${_TD_MANIFEST}" 2>/dev/null || true)
		if ((${#_TD_CACHY_PKGS[@]} > 0)); then
			pacman -S --noconfirm --needed "${_TD_CACHY_PKGS[@]}"
		fi
	fi

	readarray -t _TD_PKGS < <($YQ -r ".packages.pacman[]" "${_TD_MANIFEST}" 2>/dev/null || true)
	# An empty list here is a misconfigured manifest, not "nothing to do".
	# cosmic.yaml, niri.yaml and xfce.yaml have no `pacman` section and no
	# -arch sibling, so on Arch this silently installed NOTHING and the script
	# still exited 0 — producing images tagged cosmic/niri/xfce with no
	# desktop in them at all (tunaOS#858). The VM boot Gate caught it much
	# later, after the image had already been built and pushed.
	if ((${#_TD_PKGS[@]} == 0)); then
		echo "ERROR: ${_TD_MANIFEST} has no .packages.pacman list." >&2
		echo "       Installing no packages would yield an image tagged" >&2
		echo "       '${_TD_DESKTOP}' with no desktop in it. Add a pacman" >&2
		echo "       section, or a manifests/desktops/${_TD_DESKTOP}-arch.yaml." >&2
		exit 1
	fi
	pacman -S --noconfirm --needed "${_TD_PKGS[@]}"

	# Enable display manager
	_TD_DM=$($YQ -r '.display_manager' "${_TD_MANIFEST}")
	if [[ -n "${_TD_DM}" ]]; then
		# Not `|| true`: a manifest naming a DM that the packages did not
		# provide means the package set is wrong. This printed "Failed to
		# enable unit: Unit greetd.service does not exist" and carried on.
		systemctl enable "${_TD_DM}"
	fi
	printf "::endgroup::\n"
	# Deliberately NO `exit 0` here. The pacman branch used to return early,
	# skipping the desktop-experience contract check below — which is exactly
	# the check that would have caught an image with no session files. Arch
	# now runs the same gate every other package manager does.
fi

# ── DNF path (el10/fedora/hummingbird/eln) ───────────────────────────────────
# These sections are maps (groups/group_options/copr/optional/versionlock). The
# list-style sections (apt/pacman/zypper/emerge) installed above and must skip
# this — indexing an array with .group_options etc. is a hard yq error.
#
# hummingbird belongs here because it is dnf-driven like the other two; what
# differs is only WHICH repository satisfies the names, which the manifest's
# hummingbird: section supplies. Leaving it out would route a dnf base down
# the list-style path and produce that same yq error.
if [[ "${_TD_OS}" == "el10" || "${_TD_OS}" == "fedora" || "${_TD_OS}" == "hummingbird" || "${_TD_OS}" == "eln" ]]; then

	# Plain (non-COPR) baseurl repos — e.g. the tuna-os xfce-wayland repo,
	# which lives at its own R2 path (repo.tunaos.org/xfce/...), not the main
	# $releasever tree. Must be added BEFORE groups/packages so the
	# transaction can see them. COPR repos still go through the copr block.
	# Same list-vs-map trap as the display_manager lookup below: indexing a
	# list-shaped section makes yq exit 1, and under `set -e` the assignment
	# aborts the whole install even with stderr suppressed. No dnf-path section
	# is list-shaped today, so this is latent rather than broken — guarded so
	# it stays that way if someone writes `el10:` as a plain package list.
	_TD_REPO_COUNT=0
	if [[ "$($YQ -r ".packages.${_TD_OS} | type" "${_TD_MANIFEST}" 2>/dev/null)" == "!!map" ]]; then
		_TD_REPO_COUNT=$($YQ -r ".packages.${_TD_OS}.repos | length // 0" "${_TD_MANIFEST}" 2>/dev/null || echo 0)
	fi
	for ((i = 0; i < _TD_REPO_COUNT; i++)); do
		_TD_RN=$($YQ -r ".packages.${_TD_OS}.repos[$i].name" "${_TD_MANIFEST}")
		_TD_RB=$($YQ -r ".packages.${_TD_OS}.repos[$i].baseurl" "${_TD_MANIFEST}")
		_TD_RP=$($YQ -r ".packages.${_TD_OS}.repos[$i].priority // \"\"" "${_TD_MANIFEST}")
		_TD_RU=$($YQ -r ".packages.${_TD_OS}.repos[$i].unsigned // false" "${_TD_MANIFEST}")
		[[ -z "${_TD_RN}" || "${_TD_RN}" == "null" ]] && continue
		# `unsigned: true` is allowed for exactly one shape of repo: a
		# file:// path the Containerfile bind-mounted out of an OCI image
		# that is pinned BY DIGEST in image-versions.yaml (utah-packages,
		# /run/utah-packages). There the digest is the signature: the bytes
		# cannot differ from what was reviewed, so per-RPM gpgcheck adds
		# nothing and the RPMs carry no signature to check. Anything fetched
		# over the network at build time has no such pin and MUST stay
		# signed (tuna-os/tunaOS#1655) -- so an unsigned https:// repo is a
		# manifest error, not a config choice.
		if [[ "${_TD_RU}" == "true" && "${_TD_RB}" != file://* ]]; then
			echo "ERROR: ${_TD_MANIFEST}: repo ${_TD_RN} is 'unsigned: true' but its baseurl is not file:// (${_TD_RB}); only digest-pinned, bind-mounted content may skip gpgcheck" >&2
			exit 1
		fi
		{
			echo "[${_TD_RN}]"
			echo "name=${_TD_RN}"
			echo "baseurl=${_TD_RB}"
			echo "enabled=1"
			if [[ "${_TD_RU}" == "true" ]]; then
				echo "gpgcheck=0"
			else
				# gpgcheck=1 verifies each RPM against the tuna-os signing key
				# (every repo.tunaos.org publish pipeline runs `rpmsign --addsign`
				# before upload — see tuna-os/tunaos-packages#394). repo_gpgcheck
				# stays 0: repomd.xml isn't detached-signed yet (no repomd.xml.asc
				# published), so turning that on would hard-fail every dnf
				# transaction against these repos, not just add a check. Matches
				# the already-working contrib/install-gnome49.sh pattern rather
				# than tuna-os/tunaOS#1655's literal ask of both =1.
				echo "gpgcheck=1"
				echo "gpgkey=https://repo.tunaos.org/public.gpg"
			fi
			echo "repo_gpgcheck=0"
			echo "skip_if_unavailable=False"
			[[ -n "${_TD_RP}" && "${_TD_RP}" != "null" ]] && echo "priority=${_TD_RP}"
		} >"/etc/yum.repos.d/${_TD_RN}.repo"
		echo "Added repo ${_TD_RN} -> ${_TD_RB}"
	done

	# Install groups
	_TD_GROUP_OPTS=$($YQ -r ".packages.${_TD_OS}.group_options // \"\"" "${_TD_MANIFEST}")
	_yq_array _TD_GROUPS -r ".packages.${_TD_OS}.groups[]" "${_TD_MANIFEST}"
	readarray -t _TD_GROUP_EXC < <($YQ -r ".packages.${_TD_OS}.group_exclude[]" "${_TD_MANIFEST}" 2>/dev/null || true)

	if ((${#_TD_GROUPS[@]} > 0)); then
		_TD_EXCL_ARGS=()
		for exc in "${_TD_GROUP_EXC[@]}"; do
			[[ -n "$exc" ]] && _TD_EXCL_ARGS+=("-x" "$exc")
		done
		# shellcheck disable=SC2086 # _TD_GROUP_OPTS may be empty or contain flags
		dnf group install -y --skip-unavailable ${_TD_GROUP_OPTS} "${_TD_EXCL_ARGS[@]}" "${_TD_GROUPS[@]}" || true
	fi

	# Install packages
	readarray -t _TD_PKGS < <($YQ -r ".packages.${_TD_OS}.packages[]" "${_TD_MANIFEST}" 2>/dev/null || true)
	readarray -t _TD_EXCLUDES < <($YQ -r ".packages.${_TD_OS}.exclude[]" "${_TD_MANIFEST}" 2>/dev/null || true)

	if ((${#_TD_PKGS[@]} > 0)); then
		_TD_EXCL_ARGS=()
		for exc in "${_TD_EXCLUDES[@]}"; do
			[[ -n "$exc" ]] && _TD_EXCL_ARGS+=("-x" "$exc")
		done
		# --skip-unavailable is command-scoped in dnf5: it goes AFTER
		# `install`, never between `-y` and it. Spelled the other way it
		# is not a warning, it is `Unknown argument … (It has to be
		# placed after the command.)` — and the `||` below then quietly
		# re-runs the whole set through install_available, which ignores
		# the exclude list above and forces install_weak_deps=False.
		# Build Hummingbird #66 (run 32907940350) shipped all 52 gnome
		# packages that way. tests/test_dnf_flags_land_after_the_
		# subcommand.py lints for it tree-wide.
		if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then
			dnf_retry -y install --skip-unavailable "${_TD_EXCL_ARGS[@]}" "${_TD_PKGS[@]}" || install_available "${_TD_PKGS[@]}"
			# Whichever branch ran, --skip-unavailable can have dropped
			# packages without saying so. install_available reports its own
			# misses; the transaction above reports nothing, so ask the rpm
			# database what actually landed.
			record_unsatisfied_requests "install-desktop.sh:${_TD_DESKTOP}" "${_TD_PKGS[@]}"
		else
			dnf_retry -y install "${_TD_EXCL_ARGS[@]}" "${_TD_PKGS[@]}"
		fi
	fi

	# COPR packages (EL10 primarily)
	_TD_COPR_COUNT=$($YQ -r ".packages.${_TD_OS}.copr | length // 0" "${_TD_MANIFEST}" 2>/dev/null)
	for ((i = 0; i < _TD_COPR_COUNT; i++)); do
		_TD_COPR_REPO=$($YQ -r ".packages.${_TD_OS}.copr[$i].repo" "${_TD_MANIFEST}")
		readarray -t _TD_COPR_PKGS < <($YQ -r ".packages.${_TD_OS}.copr[$i].packages[]" "${_TD_MANIFEST}" 2>/dev/null || true)
		_TD_COPR_OPTS=$($YQ -r ".packages.${_TD_OS}.copr[$i].options // \"\"" "${_TD_MANIFEST}")

		# One transaction per provider name — listing them together made dnf
		# discard all of them whenever one was unmatched, which on EL10 is
		# always (#1016). See install_dnf_plugin_providers in lib.sh.
		install_dnf_plugin_providers
		if ! dnf -y copr enable "${_TD_COPR_REPO}"; then
			echo "TUNAOS_COPR_ENABLE_FAILED repo=${_TD_COPR_REPO} — packages from it will fall back to base repos" >&2
		fi
		dnf -y copr disable "${_TD_COPR_REPO}" || true
		_TD_REPO_ID="copr:copr.fedorainfracloud.org:$(echo "${_TD_COPR_REPO}" | tr '/' ':')"
		# `packages: []` is the enable-only idiom: the block exists so the
		# repo FILE is written and a later block can name it in --enablerepo.
		# Running `dnf install` with no arguments there is a guaranteed error
		# swallowed by `|| true`, which buries a real failure in noise the
		# reader has learned to ignore. Skip it and say why.
		if ((${#_TD_COPR_PKGS[@]} == 0)); then
			echo "Enabled ${_TD_COPR_REPO} (no packages listed — repo enabled for a later --enablerepo)"
			continue
		fi
		# shellcheck disable=SC2086
		if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then
			dnf -y --enablerepo="${_TD_REPO_ID}" install --skip-unavailable ${_TD_COPR_OPTS} "${_TD_COPR_PKGS[@]}" || install_available "${_TD_COPR_PKGS[@]}" || true
		else
			dnf -y --enablerepo="${_TD_REPO_ID}" install ${_TD_COPR_OPTS} "${_TD_COPR_PKGS[@]}" || true
		fi
	done

	# Optional packages (best-effort)
	readarray -t _TD_OPTIONAL < <($YQ -r ".packages.${_TD_OS}.optional[]" "${_TD_MANIFEST}" 2>/dev/null || true)
	if ((${#_TD_OPTIONAL[@]} > 0)); then
		install_available "${_TD_OPTIONAL[@]}"
	fi

	# Optional group (e.g. fcitx5 — install all if the first one is available)
	readarray -t _TD_OPT_GROUP < <($YQ -r ".packages.${_TD_OS}.optional_group[]" "${_TD_MANIFEST}" 2>/dev/null || true)
	if ((${#_TD_OPT_GROUP[@]} > 0)); then
		_TD_FIRST="${_TD_OPT_GROUP[0]}"
		if dnf repoquery --available --qf '%{name}\n' "$_TD_FIRST" 2>/dev/null | grep -qx "$_TD_FIRST"; then
			dnf_retry -y install "${_TD_OPT_GROUP[@]}"
		else
			echo "Skipping optional group (${_TD_FIRST} not available in repos)"
		fi
	fi

	# ── Version locks ────────────────────────────────────────────────────────────
	readarray -t _TD_LOCKS < <($YQ -r '.versionlock[]' "${_TD_MANIFEST}" 2>/dev/null || true)
	if ((${#_TD_LOCKS[@]} > 0)); then
		# Ensure versionlock plugin is available
		dnf -y install python3-dnf-plugin-versionlock 2>/dev/null || true
		for lock in "${_TD_LOCKS[@]}"; do
			[[ -n "$lock" ]] && dnf versionlock add "$lock" 2>/dev/null || true
		done
	fi

	# ── Retire the build-only repos ──────────────────────────────────────────────
	# A file:// repo is a bind mount that exists for the duration of one RUN
	# (Containerfile.el10 mounts /run/utah-packages and
	# /run/gnome50-el10-packages out of digest-pinned OCI images). The .repo file
	# the loop above wrote is NOT scoped to that RUN -- 99-cleanup.sh runs in
	# base-no-de, before the desktop stages fork from it, so nothing removes it
	# and it ships. On a booted host the baseurl names a path that does not
	# exist, and the loop writes skip_if_unavailable=False, so it is not a
	# harmless stale entry: it fails every dnf transaction the user runs.
	#
	# Only the file:// ones go. The https tiers are reachable from a booted host
	# and some are deliberately left enabled (10-base-packages.sh writes
	# tunaos-hummingbird.repo the same way).
	for ((i = 0; i < _TD_REPO_COUNT; i++)); do
		_TD_RN=$($YQ -r ".packages.${_TD_OS}.repos[$i].name" "${_TD_MANIFEST}")
		_TD_RB=$($YQ -r ".packages.${_TD_OS}.repos[$i].baseurl" "${_TD_MANIFEST}")
		[[ -z "${_TD_RN}" || "${_TD_RN}" == "null" ]] && continue
		if [[ "${_TD_RB}" == file://* ]]; then
			rm -f "/etc/yum.repos.d/${_TD_RN}.repo"
			echo "Removed build-only repo ${_TD_RN} (${_TD_RB} is a bind mount, not a runtime path)"
		fi
	done

fi # end DNF path (el10/fedora)

# ── Display manager (all OSes) ───────────────────────────────────────────────
# Per-OS-section override beats the global key: the same desktop can ship a
# Wayland-native greeter (greetd) on one base and gdm on another during a
# transition. apt/pacman paths handle their own DM and exit earlier; this
# block is reached by el10/fedora/zypper/emerge.
# The per-OS section is only a map for some OSes: el10/fedora carry
# `display_manager:` alongside `packages:`, while zypper/emerge/apt/pacman are
# plain package LISTS. Indexing a list with a key makes yq exit non-zero —
#   Error: cannot index array with 'display_manager'
# — and `//` cannot rescue an error, only a null. That aborted the desktop
# install on every list-shaped base (sailfin, flounder, grouper, marlin,
# guppy), so check the node kind before reaching into it.
_TD_DM=""
if [[ "$($YQ -r ".packages.${_TD_OS} | type" "${_TD_MANIFEST}" 2>/dev/null)" == "!!map" ]]; then
	_TD_DM=$($YQ -r ".packages.${_TD_OS}.display_manager // \"\"" "${_TD_MANIFEST}" 2>/dev/null)
fi
if [[ -z "${_TD_DM}" || "${_TD_DM}" == "null" ]]; then
	_TD_DM=$($YQ -r '.display_manager // ""' "${_TD_MANIFEST}" 2>/dev/null)
fi
# Plasma 6.6 renamed SDDM to PlasmaLogin. The manifests declare the DM family
# ("sddm"), but on EL10 the image actually ships plasma-login-manager, whose
# scriptlet claims display-manager.service. Resolve the declared name to the
# unit this image really has, rather than editing every kde*.yaml -- the
# manifest states intent, the build resolves it.
#
# Getting this wrong is not a no-op. The block below FORCE-LINKS the resolved
# unit into graphical.target.wants, so leaving it as "sddm" pulls sddm.service
# into graphical.target while display-manager.service points at plasmalogin --
# two display managers racing for seat0/VT1, and the loser fails to start.
#
# _TD_DM is a BARE name here (".service" is appended at each use below), so
# this cannot call kde_dm_unit(), which returns a full unit name. Assigning
# "plasmalogin.service" would yield "plasmalogin.service.service": safe_enable
# swallows the failure, the -f test below is false so nothing is force-linked,
# and the image ships with no display manager enabled at all.
if [[ "${_TD_DM}" == "sddm" && -f /usr/lib/systemd/system/plasmalogin.service ]]; then
	echo "install-desktop: manifest declares sddm but image ships plasmalogin.service — resolving to plasmalogin"
	_TD_DM="plasmalogin"
fi
# Same shape, for COSMIC on apt. cosmic-greeter is not a rival display manager
# to greetd -- it IS greetd, wrapped:
#   ExecStart=greetd --config /etc/greetd/cosmic-greeter.toml   (vt = "1")
# and the deb declares `Provides: x-display-manager`, `Pre-Depends: greetd`.
# Its postinst then points /etc/systemd/system/display-manager.service at
# cosmic-greeter.service via debconf (the unit's own `[Install] Alias=` is
# commented out and debconf-managed), and it arrives as a cosmic-session
# dependency, so it is installed even though cosmic.yaml's apt list never names
# it.
#
# configure-desktop-runtime.sh already defers to that claim (it has to: its
# `systemctl enable` is not `|| true`, and the conflict killed the whole
# grouper:cosmic build in LUKS run 31135761136). This is the other half, and it
# is not cosmetic: leaving _TD_DM as the manifest's "greetd" force-links
# greetd.service into graphical.target.wants below, and Ubuntu's greetd.service
# carries `[Install] Alias=display-manager.service` and NO WantedBy=, so that
# link is the only thing that would ever start it. Two units then run `greetd`
# on vt1 -- both with Restart=always -- which is the two-DMs-racing-for-seat0
# failure the sibling-link cleanup below exists to prevent.
#
# Narrow on purpose, for the same reason as configure-desktop-runtime.sh: keyed
# on the alias the distro's own packaging has ALREADY set, not on
# cosmic-greeter.service merely existing. Fedora and EL10 install cosmic-greeter
# too, and their cosmic cells are green with greetd as the DM, so a
# package-presence test would repoint them; the symlink test cannot.
if [[ "${_TD_DM}" == "greetd" ]]; then
	_TD_DM_ALIAS_NOW="$(readlink -f /etc/systemd/system/display-manager.service 2>/dev/null || true)"
	if [[ -n "${_TD_DM_ALIAS_NOW}" && -e "${_TD_DM_ALIAS_NOW}" ]] &&
		[[ "$(basename "${_TD_DM_ALIAS_NOW}")" == "cosmic-greeter.service" ]]; then
		echo "install-desktop: display-manager.service is already cosmic-greeter (greetd wrapper) — resolving greetd to cosmic-greeter"
		_TD_DM="cosmic-greeter"
	fi
fi

if [[ -n "${_TD_DM}" && "${_TD_DM}" != "null" ]]; then
	safe_enable "${_TD_DM}.service"
	# openSUSE's gdm.service ships only `[Install] Alias=display-manager.service`
	# with no `WantedBy=graphical.target` (it relies on a distro preset +
	# openSUSE's own display-manager.service launcher, which our cross-distro
	# gdm alias replaces). So `systemctl enable gdm` creates the alias but leaves
	# graphical.target.wants empty — nothing pulls the DM at boot, and the image
	# comes up to a bare console (sailfin desktop Gate: "no graphical session",
	# contract service never runs because it Requires=display-manager.service).
	# Force the wants link so graphical.target starts the DM, matching the
	# WantedBy the rpm/deb DMs carry. Idempotent where enable already made it.
	if [[ -f "/usr/lib/systemd/system/${_TD_DM}.service" ]]; then
		mkdir -p /etc/systemd/system/graphical.target.wants
		ln -sf "/usr/lib/systemd/system/${_TD_DM}.service" \
			"/etc/systemd/system/graphical.target.wants/${_TD_DM}.service"
		# Exactly one DM may be pulled into graphical.target. sddm and
		# plasmalogin both ship on EL10 KDE (plasma-login-manager does not
		# Obsolete sddm), and if both are wanted they race for seat0/VT1 and
		# whichever loses reports "Failed to start". Drop the sibling's link.
		case "${_TD_DM}" in
		plasmalogin) rm -f /etc/systemd/system/graphical.target.wants/sddm.service ;;
		sddm) rm -f /etc/systemd/system/graphical.target.wants/plasmalogin.service ;;
		esac
		# ...and take over the display-manager.service alias. openSUSE's
		# displaymanager-sysconfig package ships
		# /etc/systemd/system/display-manager.service already, pointing at
		# display-manager-legacy.service (its own sysconfig-driven launcher).
		# systemd refuses to create an [Install] Alias over an existing
		# symlink, so `systemctl enable <dm>` does not merely skip the alias —
		# it FAILS outright:
		#   Failed to enable unit: File '/etc/systemd/system/display-manager.service'
		#   already exists and is a symlink to /usr/lib/systemd/system/display-manager-legacy.service
		# safe_enable swallows that (|| true). The wants-link above still
		# starts the DM, so the desktop comes up, but the alias keeps
		# resolving to the legacy launcher — and the runtime contract asserts
		# on the alias (`systemctl show -P Id display-manager.service` against
		# ^(gdm|gdm3|lightdm|greetd)\.service$). A working desktop would fail
		# its own contract. Point the alias at the DM we actually installed.
		# Idempotent and a no-op on rpm/deb bases, where enable already made
		# this exact link.
		#
		# But do NOT stomp an alias the distro has already pointed at a REAL
		# display manager. Measured on the published yellowfin:kde: Plasma 6.6
		# renamed SDDM to PlasmaLogin, plasma-login-manager's scriptlet sets
		# display-manager.service -> plasmalogin.service, and it does not
		# obsolete sddm, so BOTH units exist. kde.yaml says display_manager:
		# sddm, so an unconditional force here would repoint every EL10/Fedora
		# KDE image away from the DM the distro chose — silently changing which
		# greeter boots, and re-creating the conditions behind tunaOS#824
		# (autologin written for one DM, a different one running).
		#
		# Only claim the alias when it is absent, dangling, or held by
		# openSUSE's display-manager-legacy launcher — which is a sysconfig
		# shim, not a display manager, and is the case this exists for.
		_TD_ALIAS=/etc/systemd/system/display-manager.service
		_TD_ALIAS_TARGET="$(readlink -f "${_TD_ALIAS}" 2>/dev/null || true)"
		if [[ ! -e "${_TD_ALIAS}" ]] ||
			[[ -z "${_TD_ALIAS_TARGET}" ]] ||
			[[ ! -e "${_TD_ALIAS_TARGET}" ]] ||
			[[ "$(basename "${_TD_ALIAS_TARGET}")" == "display-manager-legacy.service" ]]; then
			ln -sf "/usr/lib/systemd/system/${_TD_DM}.service" "${_TD_ALIAS}"
		else
			echo "display-manager.service already points at $(basename "${_TD_ALIAS_TARGET}"); leaving it"
		fi
	fi
	# Server-oriented bootc bases such as AlmaLinux default to
	# multi-user.target. Enabling a display manager alone does not change the
	# boot target, so an otherwise complete desktop image would only reach a
	# console and its graphical runtime contract would never execute.
	systemctl set-default graphical.target
fi

# ── Disable desktop files ────────────────────────────────────────────────────
readarray -t _TD_DISABLE < <($YQ -r '.disable_desktop_files[]' "${_TD_MANIFEST}" 2>/dev/null || true)
for df in "${_TD_DISABLE[@]}"; do
	if [[ -n "$df" && -f "/usr/share/applications/${df}" ]]; then
		mv "/usr/share/applications/${df}" "/usr/share/applications/${df}.disabled"
	fi
done

# ── Post-install scripts ─────────────────────────────────────────────────────
readarray -t _TD_POST_SCRIPTS < <($YQ -r '.post_install[]' "${_TD_MANIFEST}" 2>/dev/null || true)
for script in "${_TD_POST_SCRIPTS[@]}"; do
	# Post-install helpers live alongside this installer in
	# build_scripts/desktop/, so manifests can reference them by bare name.
	if [[ -n "$script" && -f "${_TD_CTX}/build_scripts/desktop/${script}" ]]; then
		echo "Running post-install: ${script}"
		source "${_TD_CTX}/build_scripts/desktop/${script}"
	fi
done

# Inline post-install commands
readarray -t _TD_POST_INLINE < <($YQ -r '.post_install_inline[]' "${_TD_MANIFEST}" 2>/dev/null || true)
for cmd in "${_TD_POST_INLINE[@]}"; do
	if [[ -n "$cmd" ]]; then
		eval "$cmd"
	fi
done

# Desktop communities own their curated defaults as plain files. This keeps
# opinions reviewable and portable without creating a package for a few config
# files; any contributor can maintain experiences/<desktop>/files/.
_TD_EXPERIENCE_FILES="${_TD_CTX}/experiences/${_TD_DESKTOP}/files"
if [[ -d "${_TD_EXPERIENCE_FILES}" ]]; then
	echo "Applying curated ${_TD_DESKTOP} experience defaults"
	cp -a "${_TD_EXPERIENCE_FILES}/." /
fi

# A package transaction is not sufficient evidence that the requested desktop
# exists. Validate its session, compositor and display manager, then install a
# runtime contract checked by the VM promotion gate. The contract unit also
# runs the snosi-derived installed-system TAP checks (e2e-runtime-checks.sh)
# as a second, non-fatal ExecStart — their markers are harvested from the
# serial console by scripts/iso-e2e.sh.
if [[ "${_TD_DESKTOP}" == gnome || "${_TD_DESKTOP}" == kde || "${_TD_DESKTOP}" == niri || "${_TD_DESKTOP}" == cosmic || "${_TD_DESKTOP}" == xfce ]]; then
	# Compile dconf databases now so verify-desktop-experience.sh doesn't
	# fail on uncompiled keyfiles. dconf-update.service handles this at
	# first boot and 40-services.sh runs `dconf update` in the base stage,
	# but desktop keyfiles land after that, so recompile here for the
	# build-time verify check.
	if command -v dconf &>/dev/null && compgen -G "/etc/dconf/db/*.d/*" >/dev/null 2>&1; then
		dconf update || true
	fi
	"${_TD_CTX}/build_scripts/checks/verify-desktop-experience.sh" "${_TD_DESKTOP}"
	install -Dm0755 "${_TD_CTX}/build_scripts/checks/verify-desktop-experience.sh" \
		/usr/libexec/tunaos/verify-desktop-experience
	install -Dm0755 "${_TD_CTX}/build_scripts/checks/e2e-runtime-checks.sh" \
		/usr/libexec/tunaos/e2e-runtime-checks

	# Branding contract — common to every desktop, plus per-desktop surfaces.
	# Same pattern as the desktop-experience check: run at build time, install
	# as a runtime unit for the VM promotion gate. The branding scripts take
	# the VARIANT (fish codename lookup), not the desktop flavor.
	"${_TD_CTX}/build_scripts/checks/verify-branding.sh" "${IMAGE_NAME:-${_TD_DESKTOP}}"
	install -Dm0755 "${_TD_CTX}/build_scripts/checks/verify-branding.sh" \
		/usr/libexec/tunaos/verify-branding
	BRANDING_EXTRA=""
	case "${_TD_DESKTOP}" in
	kde)
		# Plasma's packages own /etc/xdg/kdeglobals and overwrite the copy
		# system_files laid down in the base stage, so the look-and-feel has to
		# be re-asserted here, after the install (#1008).
		"${_TD_CTX}/build_scripts/desktop/kde-set-look-and-feel.sh"
		"${_TD_CTX}/build_scripts/checks/verify-branding-kde.sh" "${IMAGE_NAME:-${_TD_DESKTOP}}"
		install -Dm0755 "${_TD_CTX}/build_scripts/checks/verify-branding-kde.sh" \
			/usr/libexec/tunaos/verify-branding-kde
		BRANDING_EXTRA="ExecStart=-/usr/libexec/tunaos/verify-branding-kde ${IMAGE_NAME:-${_TD_DESKTOP}} --runtime"
		;;
	niri)
		"${_TD_CTX}/build_scripts/checks/verify-branding-niri.sh" "${IMAGE_NAME:-${_TD_DESKTOP}}"
		install -Dm0755 "${_TD_CTX}/build_scripts/checks/verify-branding-niri.sh" \
			/usr/libexec/tunaos/verify-branding-niri
		BRANDING_EXTRA="ExecStart=-/usr/libexec/tunaos/verify-branding-niri ${IMAGE_NAME:-${_TD_DESKTOP}} --runtime"
		;;
	esac
	cat >/usr/lib/systemd/system/tunaos-desktop-contract.service <<EOF
[Unit]
Description=Verify TunaOS ${_TD_DESKTOP} desktop experience
# dconf-update.service compiles /etc/dconf/db/*.d keyfiles at boot. On bases
# where the compiled db is baked at build this is a no-op; on guppy:gnome the
# baked db was absent and the contract raced the compile at first boot,
# failing on "missing compiled dconf database" while dconf-update would have
# fixed it moments later (boot-gate run 32323551841). Order after it so the
# check judges the settled state — a genuinely broken dconf still fails.
After=display-manager.service dconf-update.service
Wants=dconf-update.service
Requires=display-manager.service

[Service]
Type=oneshot
ExecStart=/usr/libexec/tunaos/verify-desktop-experience ${_TD_DESKTOP} --runtime
ExecStart=-/usr/libexec/tunaos/verify-branding ${IMAGE_NAME:-${_TD_DESKTOP}} --runtime
${BRANDING_EXTRA}
ExecStart=-/usr/libexec/tunaos/e2e-runtime-checks ${_TD_DESKTOP}
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=90

[Install]
WantedBy=graphical.target
EOF
	safe_enable tunaos-desktop-contract.service
fi

emit_packages_manifest

printf "::endgroup::\n"

