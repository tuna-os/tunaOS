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
if [[ "${_TD_OS}" == "zypper" ]]; then
	readarray -t _TD_ZYPPER_PKGS < <($YQ -r '.packages.zypper[]' "${_TD_MANIFEST}" 2>/dev/null || true)
	if ((${#_TD_ZYPPER_PKGS[@]} > 0)); then
		zypper install -y "${_TD_ZYPPER_PKGS[@]}"
	fi
fi

# ── Emerge path ────────────────────────────────────────────────────────────────
if [[ "${_TD_OS}" == "emerge" ]]; then
	readarray -t _TD_EMERGE_PKGS < <($YQ -r '.packages.emerge[]' "${_TD_MANIFEST}" 2>/dev/null || true)
	if ((${#_TD_EMERGE_PKGS[@]} > 0)); then
		emerge --verbose "${_TD_EMERGE_PKGS[@]}"
	fi
fi

if [[ "${_TD_OS}" == "apt" ]]; then
	# The apt section is either a plain package list (!!seq) or a map with
	# .packages and optional .ppa. Branch on the type explicitly: mikefarah
	# yq has NO if/then/else and indexing a seq with a string is an error,
	# so the old one-liners either always failed (PPA count: type is
	# "!!map", never "object") or errored and were swallowed by `|| true`
	# (package list) — every apt flavor shipped a desktop-less image that
	# still passed CI.
	_TD_APT_TYPE=$($YQ -r '.packages.apt | type' "${_TD_MANIFEST}")

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
			if command -v add-apt-repository &>/dev/null; then
				add-apt-repository -y "${_TD_PPA_REPO}"
			fi
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
	exit 0
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
	if ((${#_TD_PKGS[@]} > 0)); then
		pacman -S --noconfirm --needed "${_TD_PKGS[@]}"
	fi

	# Enable display manager
	_TD_DM=$($YQ -r '.display_manager' "${_TD_MANIFEST}")
	if [[ -n "${_TD_DM}" ]]; then
		systemctl enable "${_TD_DM}" || true
	fi
	printf "::endgroup::\n"
	exit 0
fi

# ── DNF path (el10/fedora only) ──────────────────────────────────────────────
# These sections are maps (groups/group_options/copr/optional/versionlock). The
# list-style sections (apt/pacman/zypper/emerge) installed above and must skip
# this — indexing an array with .group_options etc. is a hard yq error.
if [[ "${_TD_OS}" == "el10" || "${_TD_OS}" == "fedora" ]]; then

	# Plain (non-COPR) baseurl repos — e.g. the tuna-os xfce-wayland repo,
	# which lives at its own R2 path (repo.tunaos.org/xfce/...), not the main
	# $releasever tree. Must be added BEFORE groups/packages so the
	# transaction can see them. COPR repos still go through the copr block.
	_TD_REPO_COUNT=$($YQ -r ".packages.${_TD_OS}.repos | length // 0" "${_TD_MANIFEST}" 2>/dev/null)
	for ((i = 0; i < _TD_REPO_COUNT; i++)); do
		_TD_RN=$($YQ -r ".packages.${_TD_OS}.repos[$i].name" "${_TD_MANIFEST}")
		_TD_RB=$($YQ -r ".packages.${_TD_OS}.repos[$i].baseurl" "${_TD_MANIFEST}")
		_TD_RP=$($YQ -r ".packages.${_TD_OS}.repos[$i].priority // \"\"" "${_TD_MANIFEST}")
		[[ -z "${_TD_RN}" || "${_TD_RN}" == "null" ]] && continue
		{
			echo "[${_TD_RN}]"
			echo "name=${_TD_RN}"
			echo "baseurl=${_TD_RB}"
			echo "enabled=1"
			echo "gpgcheck=0"
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
		dnf group install -y ${_TD_GROUP_OPTS} "${_TD_EXCL_ARGS[@]}" "${_TD_GROUPS[@]}"
	fi

	# Install packages
	readarray -t _TD_PKGS < <($YQ -r ".packages.${_TD_OS}.packages[]" "${_TD_MANIFEST}" 2>/dev/null || true)
	readarray -t _TD_EXCLUDES < <($YQ -r ".packages.${_TD_OS}.exclude[]" "${_TD_MANIFEST}" 2>/dev/null || true)

	if ((${#_TD_PKGS[@]} > 0)); then
		_TD_EXCL_ARGS=()
		for exc in "${_TD_EXCLUDES[@]}"; do
			[[ -n "$exc" ]] && _TD_EXCL_ARGS+=("-x" "$exc")
		done
		dnf_retry -y install "${_TD_EXCL_ARGS[@]}" "${_TD_PKGS[@]}"
	fi

	# COPR packages (EL10 primarily)
	_TD_COPR_COUNT=$($YQ -r ".packages.${_TD_OS}.copr | length // 0" "${_TD_MANIFEST}" 2>/dev/null)
	for ((i = 0; i < _TD_COPR_COUNT; i++)); do
		_TD_COPR_REPO=$($YQ -r ".packages.${_TD_OS}.copr[$i].repo" "${_TD_MANIFEST}")
		readarray -t _TD_COPR_PKGS < <($YQ -r ".packages.${_TD_OS}.copr[$i].packages[]" "${_TD_MANIFEST}" 2>/dev/null || true)
		_TD_COPR_OPTS=$($YQ -r ".packages.${_TD_OS}.copr[$i].options // \"\"" "${_TD_MANIFEST}")

		dnf -y copr enable "${_TD_COPR_REPO}"
		dnf -y copr disable "${_TD_COPR_REPO}"
		_TD_REPO_ID="copr:copr.fedorainfracloud.org:$(echo "${_TD_COPR_REPO}" | tr '/' ':')"
		# shellcheck disable=SC2086
		dnf -y --enablerepo="${_TD_REPO_ID}" install ${_TD_COPR_OPTS} "${_TD_COPR_PKGS[@]}" || true
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
if [[ -n "${_TD_DM}" && "${_TD_DM}" != "null" ]]; then
	safe_enable "${_TD_DM}.service"
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

# A package transaction is not sufficient evidence that the requested desktop
# exists. Validate its session, compositor and display manager, then install a
# runtime contract checked by the VM promotion gate. The contract unit also
# runs the snosi-derived installed-system TAP checks (e2e-runtime-checks.sh)
# as a second, non-fatal ExecStart — their markers are harvested from the
# serial console by scripts/iso-e2e.sh.
if [[ "${_TD_DESKTOP}" == gnome || "${_TD_DESKTOP}" == kde || "${_TD_DESKTOP}" == niri || "${_TD_DESKTOP}" == cosmic || "${_TD_DESKTOP}" == xfce ]]; then
	"${_TD_CTX}/build_scripts/checks/verify-desktop-experience.sh" "${_TD_DESKTOP}"
	install -Dm0755 "${_TD_CTX}/build_scripts/checks/verify-desktop-experience.sh" \
		/usr/libexec/tunaos/verify-desktop-experience
	install -Dm0755 "${_TD_CTX}/build_scripts/checks/e2e-runtime-checks.sh" \
		/usr/libexec/tunaos/e2e-runtime-checks
	cat >/usr/lib/systemd/system/tunaos-desktop-contract.service <<EOF
[Unit]
Description=Verify TunaOS ${_TD_DESKTOP} desktop experience
After=display-manager.service
Requires=display-manager.service

[Service]
Type=oneshot
ExecStart=/usr/libexec/tunaos/verify-desktop-experience ${_TD_DESKTOP} --runtime
ExecStart=-/usr/libexec/tunaos/e2e-runtime-checks ${_TD_DESKTOP}
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=90

[Install]
WantedBy=graphical.target
EOF
	safe_enable tunaos-desktop-contract.service
fi

printf "::endgroup::\n"
