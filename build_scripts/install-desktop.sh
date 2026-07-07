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

DESKTOP="${1:?Usage: install-desktop.sh <desktop>}"
CONTEXT_PATH="/run/context"
MANIFEST="${CONTEXT_PATH}/manifests/desktops/${DESKTOP}.yaml"

if [[ ! -f "${MANIFEST}" ]]; then
    echo "ERROR: No manifest found at ${MANIFEST}" >&2
    echo "Available desktops:"
    ls "${CONTEXT_PATH}/manifests/desktops/"*.yaml 2>/dev/null | sed 's|.*/||;s|\.yaml||'
    exit 1
fi

source "${CONTEXT_PATH}/build_scripts/lib.sh"

# Ensure yq is available inside the container for manifest parsing.
# yq is a static binary — download once, use for the rest of the build.
YQ="${YQ:-yq}"
if ! command -v "$YQ" &>/dev/null; then
    YQ_ARCH="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
    curl -fsSL "https://github.com/mikefarah/yq/releases/download/v4.53.3/yq_linux_${YQ_ARCH}" -o /usr/bin/yq
    chmod +x /usr/bin/yq
    YQ=/usr/bin/yq
fi
printf "::group:: === install-desktop: %s ===\n" "${DESKTOP}"

# ── Determine OS section to use ──────────────────────────────────────────────
OS_SECTION=""
if [[ "$PKG_MGR" == "apt" ]]; then
    OS_SECTION="apt"
elif [[ "$PKG_MGR" == "pacman" ]]; then
    OS_SECTION="pacman"
elif [[ "$IS_FEDORA" == true ]]; then
    OS_SECTION="fedora"
else
    OS_SECTION="el10"
fi

# Check for CachyOS-specific section (Arch derivative with extra repos)
if [[ "${OS_SECTION}" == "pacman" ]] && [[ -f /etc/cachyos-release ]]; then
    # If the manifest has a cachyos section, merge its repos/packages
    CACHYOS_SECTION="cachyos"
fi

echo "Installing ${DESKTOP} desktop (OS section: ${OS_SECTION})..."

# ── APT path ─────────────────────────────────────────────────────────────────
if [[ "${OS_SECTION}" == "apt" ]]; then
    # Handle PPAs (Ubuntu only — Debian uses native repos)
    PPA_COUNT=$($YQ -r ".packages.apt.ppa | length // 0" "${MANIFEST}" 2>/dev/null)
    for ((i=0; i<PPA_COUNT; i++)); do
        PPA_REPO=$($YQ -r ".packages.apt.ppa[$i].repo" "${MANIFEST}")
        PPA_COND=$($YQ -r ".packages.apt.ppa[$i].condition" "${MANIFEST}")
        # Only add PPA if condition matches (e.g. "ubuntu" only on Ubuntu)
        if [[ -z "${PPA_COND}" ]] || [[ "$IS_UBUNTU" == true && "${PPA_COND}" == "ubuntu" ]]; then
            if command -v add-apt-repository &>/dev/null; then
                add-apt-repository -y "${PPA_REPO}"
            fi
        fi
    done

    # Install packages (may be under .packages.apt[] or .packages.apt.packages[])
    readarray -t PKGS < <($YQ -r '(.packages.apt.packages // .packages.apt)[]' "${MANIFEST}" 2>/dev/null)
    if ((${#PKGS[@]} > 0)); then
        pkg_install "${PKGS[@]}"
    fi
    # Enable display manager
    DM=$($YQ -r '.display_manager' "${MANIFEST}")
    if [[ -n "${DM}" ]]; then
        systemctl enable "${DM}" || true
    fi
    printf "::endgroup::\n"
    exit 0
fi

# ── Pacman path (Arch Linux / CachyOS) ───────────────────────────────────────
if [[ "${OS_SECTION}" == "pacman" ]]; then
    # Install CachyOS repos if applicable
    if [[ -n "${CACHYOS_SECTION:-}" ]]; then
        REPO_COUNT=$($YQ -r ".packages.${CACHYOS_SECTION}.repos | length // 0" "${MANIFEST}" 2>/dev/null)
        for ((i=0; i<REPO_COUNT; i++)); do
            REPO_NAME=$($YQ -r ".packages.${CACHYOS_SECTION}.repos[$i].name" "${MANIFEST}")
            REPO_URL=$($YQ -r ".packages.${CACHYOS_SECTION}.repos[$i].url" "${MANIFEST}")
            if ! grep -q "\\[${REPO_NAME}\\]" /etc/pacman.conf; then
                printf '\n[%s]\nServer = %s\n' "${REPO_NAME}" "${REPO_URL}" >> /etc/pacman.conf
            fi
        done
        pacman -Sy --noconfirm
        # Install CachyOS-specific packages
        readarray -t CACHY_PKGS < <($YQ -r ".packages.${CACHYOS_SECTION}.packages[]" "${MANIFEST}" 2>/dev/null)
        if ((${#CACHY_PKGS[@]} > 0)); then
            pacman -S --noconfirm --needed "${CACHY_PKGS[@]}"
        fi
    fi

    readarray -t PKGS < <($YQ -r ".packages.pacman[]" "${MANIFEST}" 2>/dev/null)
    if ((${#PKGS[@]} > 0)); then
        pacman -S --noconfirm --needed "${PKGS[@]}"
    fi

    # Enable display manager
    DM=$($YQ -r '.display_manager' "${MANIFEST}")
    if [[ -n "${DM}" ]]; then
        systemctl enable "${DM}" || true
    fi
    printf "::endgroup::\n"
    exit 0
fi

# ── DNF path ─────────────────────────────────────────────────────────────────

# Install groups
GROUP_OPTIONS=$($YQ -r ".packages.${OS_SECTION}.group_options" "${MANIFEST}")
readarray -t GROUPS < <($YQ -r ".packages.${OS_SECTION}.groups[]" "${MANIFEST}" 2>/dev/null)
readarray -t GROUP_EXCLUDES < <($YQ -r ".packages.${OS_SECTION}.group_exclude[]" "${MANIFEST}" 2>/dev/null)

if ((${#GROUPS[@]} > 0)); then
    EXCLUDE_ARGS=()
    for exc in "${GROUP_EXCLUDES[@]}"; do
        [[ -n "$exc" ]] && EXCLUDE_ARGS+=("-x" "$exc")
    done
    # shellcheck disable=SC2086 # GROUP_OPTIONS may be empty or contain flags
    dnf group install -y ${GROUP_OPTIONS} "${EXCLUDE_ARGS[@]}" "${GROUPS[@]}"
fi

# Install packages
readarray -t PKGS < <($YQ -r ".packages.${OS_SECTION}.packages[]" "${MANIFEST}" 2>/dev/null)
readarray -t EXCLUDES < <($YQ -r ".packages.${OS_SECTION}.exclude[]" "${MANIFEST}" 2>/dev/null)

if ((${#PKGS[@]} > 0)); then
    EXCLUDE_ARGS=()
    for exc in "${EXCLUDES[@]}"; do
        [[ -n "$exc" ]] && EXCLUDE_ARGS+=("-x" "$exc")
    done
    dnf_retry -y install "${EXCLUDE_ARGS[@]}" "${PKGS[@]}"
fi

# COPR packages (EL10 primarily)
COPR_COUNT=$($YQ -r ".packages.${OS_SECTION}.copr | length // 0" "${MANIFEST}" 2>/dev/null)
for ((i=0; i<COPR_COUNT; i++)); do
    COPR_REPO=$($YQ -r ".packages.${OS_SECTION}.copr[$i].repo" "${MANIFEST}")
    readarray -t COPR_PKGS < <($YQ -r ".packages.${OS_SECTION}.copr[$i].packages[]" "${MANIFEST}")
    COPR_OPTS=$($YQ -r ".packages.${OS_SECTION}.copr[$i].options" "${MANIFEST}")

    dnf -y copr enable "${COPR_REPO}"
    dnf -y copr disable "${COPR_REPO}"
    REPO_ID="copr:copr.fedorainfracloud.org:$(echo "${COPR_REPO}" | tr '/' ':')"
    # shellcheck disable=SC2086
    dnf -y --enablerepo="${REPO_ID}" install ${COPR_OPTS} "${COPR_PKGS[@]}" || true
done

# Optional packages (best-effort)
readarray -t OPTIONAL < <($YQ -r ".packages.${OS_SECTION}.optional[]" "${MANIFEST}" 2>/dev/null)
if ((${#OPTIONAL[@]} > 0)); then
    install_available "${OPTIONAL[@]}"
fi

# Optional group (e.g. fcitx5 — install all if the first one is available)
readarray -t OPT_GROUP < <($YQ -r ".packages.${OS_SECTION}.optional_group[]" "${MANIFEST}" 2>/dev/null)
if ((${#OPT_GROUP[@]} > 0)); then
    FIRST="${OPT_GROUP[0]}"
    if dnf repoquery --available --qf '%{name}\n' "$FIRST" 2>/dev/null | grep -qx "$FIRST"; then
        dnf_retry -y install "${OPT_GROUP[@]}"
    else
        echo "Skipping optional group (${FIRST} not available in repos)"
    fi
fi

# ── Version locks ────────────────────────────────────────────────────────────
readarray -t LOCKS < <($YQ -r '.versionlock[]' "${MANIFEST}" 2>/dev/null)
if ((${#LOCKS[@]} > 0)); then
    # Ensure versionlock plugin is available
    dnf -y install python3-dnf-plugin-versionlock 2>/dev/null || true
    for lock in "${LOCKS[@]}"; do
        [[ -n "$lock" ]] && dnf versionlock add "$lock" 2>/dev/null || true
    done
fi

# ── Display manager ──────────────────────────────────────────────────────────
DM=$($YQ -r '.display_manager' "${MANIFEST}")
if [[ -n "${DM}" ]]; then
    safe_enable "${DM}.service"
fi

# ── Disable desktop files ────────────────────────────────────────────────────
readarray -t DISABLE_DESKTOPS < <($YQ -r '.disable_desktop_files[]' "${MANIFEST}" 2>/dev/null)
for df in "${DISABLE_DESKTOPS[@]}"; do
    if [[ -n "$df" && -f "/usr/share/applications/${df}" ]]; then
        mv "/usr/share/applications/${df}" "/usr/share/applications/${df}.disabled"
    fi
done

# ── Post-install scripts ─────────────────────────────────────────────────────
readarray -t POST_SCRIPTS < <($YQ -r '.post_install[]' "${MANIFEST}" 2>/dev/null)
for script in "${POST_SCRIPTS[@]}"; do
    if [[ -n "$script" && -f "${CONTEXT_PATH}/build_scripts/${script}" ]]; then
        echo "Running post-install: ${script}"
        source "${CONTEXT_PATH}/build_scripts/${script}"
    fi
done

# Inline post-install commands
readarray -t POST_INLINE < <($YQ -r '.post_install_inline[]' "${MANIFEST}" 2>/dev/null)
for cmd in "${POST_INLINE[@]}"; do
    if [[ -n "$cmd" ]]; then
        eval "$cmd"
    fi
done

printf "::endgroup::\n"
