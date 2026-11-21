#!/usr/bin/env bash
# Install the runtime branding contract into the image being built: the one
# checker (/usr/libexec/tunaos/verify-branding --runtime), its runtime library,
# every per-desktop checker, the generated identity table the checker reads,
# and tunaos-branding-contract.service, which runs it on every boot and prints
# TUNAOS_BRANDING_REPORT / TUNAOS_BRANDING_OK|FAIL on the serial console.
#
# WHY IT IS CALLED FROM 90-image-info.sh
#
# That is the only script every base runs (docs/BRANDING.md, "every base runs
# it"). 40-services.sh is not: Containerfile.gentoo never calls it, and its
# apt and pacman/zypper/emerge paths `exit 0` before the base-contract install
# at its end, so a unit installed there would be absent from Ubuntu, Debian,
# Arch, openSUSE and Gentoo images while a test that it is "installed" passed
# (AGENTS.md: "Being invoked is not being reached"). Installing on base
# flavors is the point: the build-time check only ever ran in desktop stages,
# so no base image carried a branding check at all.
#
# Idempotent: 90-image-info.sh runs more than once per build (Containerfile.el10
# re-runs it after each desktop install), and each run rewrites the same files.
#
# USAGE
#   install-branding-contract.sh                  checker + unit (90-image-info.sh)
#   install-branding-contract.sh --desktop <d>    the desktop drop-in, from the
#                                                 two desktop install paths
#                                                 (install-desktop.sh and
#                                                 configure-desktop-runtime.sh)

set -euo pipefail

ctx="${TUNAOS_BUILD_CONTEXT:-/run/context}"
dest="${TUNAOS_BRANDING_DEST:-}"
libexec="${dest}/usr/libexec/tunaos"

if [[ "${1:-}" == --desktop ]]; then
	desktop="${2:?usage: install-branding-contract.sh --desktop <desktop>}"
	# Which per-desktop checker runs, and ordering after the greeter and the
	# desktop contract so the applied look is read once the session machinery
	# that writes it has started. Without this drop-in the checker falls back to
	# image-info.json's image-flavor.
	install -d "${dest}/usr/lib/systemd/system/tunaos-branding-contract.service.d"
	cat >"${dest}/usr/lib/systemd/system/tunaos-branding-contract.service.d/10-desktop.conf" <<DROPIN
[Unit]
After=display-manager.service dconf-update.service tunaos-desktop-contract.service

[Service]
Environment=TUNAOS_BRANDING_DESKTOP=${desktop}
DROPIN
	echo "branding contract: desktop=${desktop}"
	exit 0
fi

install -Dm0755 "${ctx}/build_scripts/checks/verify-branding.sh" "${libexec}/verify-branding"
install -Dm0644 "${ctx}/build_scripts/checks/verify-branding-runtime.sh" "${libexec}/verify-branding-runtime.sh"
for desktop in gnome kde niri cosmic xfce pantheon; do
	install -Dm0755 "${ctx}/build_scripts/checks/verify-branding-${desktop}.sh" "${libexec}/verify-branding-${desktop}"
done
# The checker derives the variant's splash theme from this table, the same
# generated file plymouth-set-theme.sh selects the theme from.
install -Dm0644 "${ctx}/build_scripts/lib/variant-identity.tsv" \
	"${dest}/usr/share/tunaos/branding/variant-identity.tsv"

install -d "${dest}/usr/lib/systemd/system"
cat >"${dest}/usr/lib/systemd/system/tunaos-branding-contract.service" <<'UNIT'
[Unit]
Description=Verify TunaOS branding on the running system
# The units that change what is checked must have run: the base contract
# (system bus up), first-boot setup, and the units that add flatpak remotes
# at boot (flatpak-add-fedora-repos.service added Fedora's remotes on bonito,
# t68 serial.log:240). Ordering after a unit that does not exist is a no-op.
After=multi-user.target tunaos-base-contract.service ublue-system-setup.service
After=flatpak-add-fedora-repos.service flatpak-preinstall.service flatpak-system-helper.service

[Service]
Type=oneshot
# No leading '-': a branding failure fails this unit. It is its own unit so
# that failure does not cancel the desktop contract's later ExecStart lines.
ExecStart=/usr/libexec/tunaos/verify-branding --runtime
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT
# The preset (system_files/.../50-tunaos.preset) keeps it enabled through the
# first-boot preset pass; the symlink enables it in the image itself.
if [[ -z "$dest" ]] && command -v systemctl >/dev/null 2>&1; then
	systemctl enable tunaos-branding-contract.service
else
	install -d "${dest}/etc/systemd/system/multi-user.target.wants"
	ln -sfn /usr/lib/systemd/system/tunaos-branding-contract.service \
		"${dest}/etc/systemd/system/multi-user.target.wants/tunaos-branding-contract.service"
fi
echo "branding contract installed: /usr/libexec/tunaos/verify-branding --runtime via tunaos-branding-contract.service"
