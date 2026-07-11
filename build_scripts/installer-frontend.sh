#!/usr/bin/env bash
# installer-frontend.sh — wire the desktop-matched TunaOS installer frontend.
#
# Sourced by install-desktop.sh via a manifest's post_install list, so
# ${_TD_DESKTOP} is in scope. Conventions come from the shared frontends spec
# (tuna-os workspace INSTALLER-FRONTENDS.md):
#
#   - tuna-os Flatpak remote (tunaos.org/flatpak) in /etc/flatpak/remotes.d
#   - flatpak preinstall.d entry for org.tunaos.Installer<DE>
#   - shared host polkit action org.tunaos.Installer.install (pkexec
#     escalation for the sandboxed fisherman backend)
#   - /etc/tuna-installer/offline-stores probe list for embedded OCI stores
#
# GNOME flavors keep the upstream GTK bootc-installer and only get the
# remote + polkit + offline-stores pieces.

set -euo pipefail

_IF_DESKTOP="${_TD_DESKTOP:-${1:-}}"

case "${_IF_DESKTOP}" in
kde*) _IF_APP="org.tunaos.InstallerKde" ;;
niri*) _IF_APP="org.tunaos.InstallerNiri" ;;
cosmic*) _IF_APP="org.tunaos.InstallerCosmic" ;;
xfce*) _IF_APP="org.tunaos.InstallerXfce" ;;
*) _IF_APP="" ;; # gnome uses upstream bootc-installer
esac

echo "installer-frontend: desktop=${_IF_DESKTOP} app=${_IF_APP:-<upstream bootc-installer>}"

# ── tuna-os Flatpak remote ───────────────────────────────────────────────────
mkdir -p /etc/flatpak/remotes.d
curl --retry 3 --fail -sSL \
	-o /etc/flatpak/remotes.d/tuna-os.flatpakrepo \
	"https://tunaos.org/flatpak/tuna-os.flatpakrepo"
chmod 0644 /etc/flatpak/remotes.d/tuna-os.flatpakrepo

# ── Preinstall the desktop-matched installer frontend ────────────────────────
if [[ -n "${_IF_APP}" ]]; then
	mkdir -p /usr/share/flatpak/preinstall.d
	cat >"/usr/share/flatpak/preinstall.d/tuna-installer.preinstall" <<EOF
[Flatpak Preinstall ${_IF_APP}]
Branch=latest
IsRuntime=false
EOF
fi

# ── Shared polkit action for the fisherman backend ───────────────────────────
# One action ID across every frontend; the sandboxed apps escalate with
# pkexec /app/bin/fisherman. Same policy the fisherman repo ships.
mkdir -p /usr/share/polkit-1/actions
curl --retry 3 --fail -sSL \
	-o /usr/share/polkit-1/actions/org.tunaos.Installer.policy \
	"https://raw.githubusercontent.com/projectbluefin/fisherman/dev/data/polkit/org.tunaos.Installer.policy"
chmod 0644 /usr/share/polkit-1/actions/org.tunaos.Installer.policy

# ── Offline image store probe list ───────────────────────────────────────────
# Frontends read this to find embedded OCI stores on live media and pass them
# to fisherman as additionalImageStores. Paths that don't exist are ignored,
# so the default entry is harmless on installed systems.
mkdir -p /etc/tuna-installer
cat >/etc/tuna-installer/offline-stores <<'EOF'
# OCI store roots probed by the TunaOS installer for offline images.
# One absolute path per line; missing paths are skipped.
/usr/share/tuna-installer/oci-store
EOF
chmod 0644 /etc/tuna-installer/offline-stores
