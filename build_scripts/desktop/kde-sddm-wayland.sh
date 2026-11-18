#!/usr/bin/env bash
# Give an installed SDDM without an X server a Wayland greeter.
#
# SDDM's built-in default is DisplayServer=x11. Fedora's sddm packaging ships
# a drop-in that switches it to Wayland; Ubuntu's does not, and grouper:kde
# ships no X server at all. The live ISO writes its own config
# (live-iso/common/src/desktop-kde.sh), but the installed system never got
# one, so SDDM ran /usr/bin/X, failed, and first boot stayed on the text
# console: grouper:kde strict diag run 43547709594, 60 frames of boot log and
# no greeter on both legs while e2e-runtime-checks reported sddm.service
# active (tunaOS#4459).
#
# configure-desktop-runtime.sh calls this only when the KDE DM is sddm;
# images on plasmalogin (EL10) are not touched. It acts only when no X
# server exists, so bases whose packaging already chose a display server are
# left alone. TUNAOS_DM_ROOT points it at a scratch root
# for tests (same convention as kde-set-look-and-feel.sh).
set -euo pipefail

root="${TUNAOS_DM_ROOT:-}"

if command -v Xorg >/dev/null 2>&1 || command -v X >/dev/null 2>&1; then
	echo "kde-sddm-wayland: an X server is installed; leaving SDDM's display server alone"
	exit 0
fi

mkdir -p "${root}/etc/sddm.conf.d" "${root}/usr/lib/systemd/system"
# CompositorCommand belongs in [Wayland]; under [General] SDDM drops it
# silently and falls back to weston (see desktop-kde.sh). The value is
# Fedora's sddm-wayland-plasma one, as the live ISO uses.
cat >"${root}/etc/sddm.conf.d/10-tunaos-wayland.conf" <<'EOF'
[General]
DisplayServer=wayland

[Wayland]
CompositorCommand=kwin_wayland --drm --no-lockscreen --no-global-shortcuts --locale1
EOF

# SDDM reads no config at all when the newest mtime among its config files is
# 0 (ConfigBase::load(), measured on grouper:kde, tunaOS#4459). Image layers
# can carry normalised mtimes, so stamp the drop-ins with the boot time before
# the greeter starts, as the live ISO does. ($$ is systemd's escape for $.)
cat >"${root}/usr/lib/systemd/system/tunaos-sddm-config-mtime.service" <<'EOF'
[Unit]
Description=Give the SDDM config a readable mtime
DefaultDependencies=no
After=local-fs.target
Before=display-manager.service sddm.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'for d in /etc/sddm.conf.d; do [ -d "$$d" ] && touch -c "$$d" "$$d"/*; done; exit 0'

[Install]
WantedBy=sddm.service
EOF

systemctl ${root:+--root="$root"} enable tunaos-sddm-config-mtime.service
echo "kde-sddm-wayland: no X server; wrote the Wayland greeter config"
