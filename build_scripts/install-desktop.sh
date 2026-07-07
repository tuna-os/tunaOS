#!/usr/bin/env bash
# install-desktop.sh — Generic desktop installer driven by YAML manifests.
#
# Reads a desktop manifest from manifests/desktops/<desktop>.yaml and
# installs packages, enables services, applies version locks, and runs
# post-install hooks. Replaces per-DE shell scripts (kde.sh, cosmic.sh, etc.)
# with a single data-driven installer.
#
# Usage:
#   /run/context/build_scripts/install-desktop.sh <desktop>
#
# Requires yq (mikefarah/yq) available at YQ env var or in PATH.

set -xeuo pipefail

_TD_DESKTOP="${1:?Usage: install-desktop.sh <desktop>}"
_TD_CTX="/run/context"
_TD_MANIFEST="${_TD_CTX}/manifests/desktops/${_TD_DESKTOP}.yaml"

if [[ ! -f "${_TD_MANIFEST}" ]]; then
    echo "ERROR: No manifest found at ${_TD_MANIFEST}" >&2
    echo "Available desktops:"
    ls "${_TD_CTX}/manifests/desktops/"*.yaml 2>/dev/null | sed 's|.*/||;s|\.yaml||'
    exit 1
fi

source "${_TD_CTX}/build_scripts/lib.sh"

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
if [[ "${_TD_OS}" == "apt" ]]; then
    # Handle PPAs (Ubuntu only — Debian uses native repos)
    _TD_PPA_COUNT=$($YQ -r ".packages.apt.ppa | length // 0" "${_TD_MANIFEST}" 2>/dev/null)
    for ((i=0; i<_TD_PPA_COUNT; i++)); do
        _TD_PPA_REPO=$($YQ -r ".packages.apt.ppa[$i].repo" "${_TD_MANIFEST}")
        _TD_PPA_COND=$($YQ -r ".packages.apt.ppa[$i].condition" "${_TD_MANIFEST}")
        # Only add PPA if condition matches (e.g. "ubuntu" only on Ubuntu)
        if [[ -z "${_TD_PPA_COND}" ]] || [[ "$IS_UBUNTU" == true && "${_TD_PPA_COND}" == "ubuntu" ]]; then
            if command -v add-apt-repository &>/dev/null; then
                add-apt-repository -y "${_TD_PPA_REPO}"
            fi
        fi
    done

    # Install packages (may be under .packages.apt[] or .packages.apt.packages[])
    readarray -t _TD_PKGS < <($YQ -r '(.packages.apt.packages // .packages.apt)[]' "${_TD_MANIFEST}" 2>/dev/null || true)
    if ((${#_TD_PKGS[@]} > 0)); then
        pkg_install "${_TD_PKGS[@]}"
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
        for ((i=0; i<_TD_REPO_COUNT; i++)); do
            _TD_REPO_NAME=$($YQ -r ".packages.${_TD_CACHYOS}.repos[$i].name" "${_TD_MANIFEST}")
            _TD_REPO_URL=$($YQ -r ".packages.${_TD_CACHYOS}.repos[$i].url" "${_TD_MANIFEST}")
            if ! grep -q "\\[${_TD_REPO_NAME}\\]" /etc/pacman.conf; then
                printf '\n[%s]\nServer = %s\n' "${_TD_REPO_NAME}" "${_TD_REPO_URL}" >> /etc/pacman.conf
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

# ── DNF path ─────────────────────────────────────────────────────────────────

# Install groups
_TD_GROUP_OPTS=$($YQ -r ".packages.${_TD_OS}.group_options" "${_TD_MANIFEST}")
readarray -t GROUPS < <($YQ -r ".packages.${_TD_OS}.groups[]" "${_TD_MANIFEST}" 2>/dev/null || true)
readarray -t _TD_GROUP_EXC < <($YQ -r ".packages.${_TD_OS}.group_exclude[]" "${_TD_MANIFEST}" 2>/dev/null || true)

if ((${#GROUPS[@]} > 0)); then
    _TD_EXCL_ARGS=()
    for exc in "${_TD_GROUP_EXC[@]}"; do
        [[ -n "$exc" ]] && _TD_EXCL_ARGS+=("-x" "$exc")
    done
    # shellcheck disable=SC2086 # _TD_GROUP_OPTS may be empty or contain flags
    dnf group install -y ${_TD_GROUP_OPTS} "${_TD_EXCL_ARGS[@]}" "${GROUPS[@]}"
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
for ((i=0; i<_TD_COPR_COUNT; i++)); do
    _TD_COPR_REPO=$($YQ -r ".packages.${_TD_OS}.copr[$i].repo" "${_TD_MANIFEST}")
    readarray -t _TD_COPR_PKGS < <($YQ -r ".packages.${_TD_OS}.copr[$i].packages[]" "${_TD_MANIFEST}" 2>/dev/null || true)
    _TD_COPR_OPTS=$($YQ -r ".packages.${_TD_OS}.copr[$i].options" "${_TD_MANIFEST}")

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

# ── Display manager ──────────────────────────────────────────────────────────
_TD_DM=$($YQ -r '.display_manager' "${_TD_MANIFEST}")
if [[ -n "${_TD_DM}" ]]; then
    safe_enable "${_TD_DM}.service"
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
    if [[ -n "$script" && -f "${_TD_CTX}/build_scripts/${script}" ]]; then
        echo "Running post-install: ${script}"
        source "${_TD_CTX}/build_scripts/${script}"
    fi
done

# Inline post-install commands
readarray -t _TD_POST_INLINE < <($YQ -r '.post_install_inline[]' "${_TD_MANIFEST}" 2>/dev/null || true)
for cmd in "${_TD_POST_INLINE[@]}"; do
    if [[ -n "$cmd" ]]; then
        eval "$cmd"
    fi
done

printf "::endgroup::\n"
