#!/usr/bin/env bats
# COSMIC's icon theme has two spellings, and the manifest must use the right
# one per package manager.
#
#   RPM (Fedora, EL10):        cosmic-icon-theme
#   Debian/Ubuntu, openSUSE:   cosmic-icons
#
# manifests/desktops/cosmic.yaml carried the RPM name in its apt section. apt
# aborts the entire transaction on the first name it cannot resolve —
#
#   E: Unable to locate package cosmic-icon-theme
#
# — so one wrong entry failed all 21 packages and the whole grouper:cosmic
# build (LUKS run 31135209477). The zypper section had cosmic-icons already;
# only apt was left behind.
#
# Verified against what ppa:hepp3n/cosmic-epoch actually publishes:
#
#   curl -fsSL 'https://api.launchpad.net/devel/~hepp3n/+archive/ubuntu/\
#     cosmic-epoch?ws.op=getPublishedBinaries&status=Published'
#
# 46 distinct binaries across 3 pages. cosmic-icons is published;
# cosmic-icon-theme is not.
#
# These tests are offline: they assert the spelling split the measurement
# established, not the live archive. A network-dependent test here would go
# red on Launchpad's availability rather than on this repo's correctness.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
MANIFEST="${REPO_ROOT}/manifests/desktops/cosmic.yaml"

apt_packages() { yq -r '.packages.apt.packages[]' "$MANIFEST"; }

setup() { command -v yq >/dev/null || skip "yq not available"; }

@test "the apt list uses the Debian spelling of the icon theme" {
	run apt_packages
	[ "$status" -eq 0 ]
	grep -qx 'cosmic-icons' <<<"$output"
}

# The regression itself. The RPM name resolves nowhere under apt, and its
# presence fails every other package in the same call.
@test "the apt list does not use the RPM spelling" {
	run apt_packages
	! grep -qx 'cosmic-icon-theme' <<<"$output"
}

# The counterpart: the RPM sections must keep the RPM name. A blanket
# find-and-replace to fix the apt failure would break Fedora and EL10 instead,
# which is the obvious wrong repair and worth pinning.
@test "the rpm sections keep the rpm spelling" {
	run yq -r '.packages.fedora.packages[]' "$MANIFEST"
	grep -qx 'cosmic-icon-theme' <<<"$output"
	# el10 installs the COSMIC set through COPR, so its names live under
	# .copr[].packages, not the flat .packages list (which holds only the
	# stock-repo extras: flatpak, pipewire, and so on).
	run yq -r '.packages.el10.copr[].packages[]' "$MANIFEST"
	grep -qx 'cosmic-icon-theme' <<<"$output"
}

@test "zypper keeps the Debian spelling it already had" {
	run yq -r '.packages.zypper[]' "$MANIFEST"
	grep -qx 'cosmic-icons' <<<"$output"
}

# The apt list is what the PPA publishes plus greetd from the Ubuntu archive.
# Pinned as the set measured on 2026-08-07 so a package added here without
# checking Launchpad fails locally rather than 20 minutes into a container
# build. Update the list when the PPA gains a package — after checking that it
# has.
@test "every apt package is one the PPA publishes, or greetd" {
	local published=(
		adw-gtk3 appstream-data-pop appstream-data-pop-icons
		appstream-data-pop-icons-hidpi calamares-settings-cosmic
		cosmic-app-library cosmic-applets cosmic-bg cosmic-comp
		cosmic-desktop cosmic-desktop-minimal cosmic-edit cosmic-files
		cosmic-greeter cosmic-greeter-daemon cosmic-icons cosmic-idle
		cosmic-initial-setup cosmic-initial-setup-casper cosmic-launcher
		cosmic-monitor cosmic-notifications cosmic-osd cosmic-panel
		cosmic-player cosmic-randr cosmic-screenshot cosmic-session
		cosmic-settings cosmic-settings-daemon cosmic-store cosmic-term
		cosmic-wallpapers cosmic-workspaces
		gnome-shell-extension-pop-battery-icon-fix minimal pop-fonts
		pop-gnome-shell-theme pop-gtk-theme pop-icon-theme pop-launcher
		pop-launcher-system76-power pop-sound-theme pop-theme standard
		xdg-desktop-portal-cosmic
		# Not from the PPA. Ubuntu's own archive ships greetd, which is
		# why niri.sh installs it straight from there too.
		greetd
		# Also not from the PPA: Mesa's software Vulkan driver
		# (lavapipe), added with the cosmic/niri Vulkan change. Measured
		# 2026-09-05 against packages.ubuntu.com for grouper's own base
		# and its neighbours -- resolute, questing and noble all return
		# 200 for mesa-vulkan-drivers. grouper is the only apt variant
		# that declares cosmic, and it is ubuntu:resolute.
		mesa-vulkan-drivers
	)
	local p known fail=0
	while read -r p; do
		[ -n "$p" ] || continue
		known=0
		for k in "${published[@]}"; do
			[ "$p" = "$k" ] && known=1 && break
		done
		if [ "$known" -eq 0 ]; then
			echo "FAIL: cosmic.yaml's apt list names '${p}', which neither" >&2
			echo "      ppa:hepp3n/cosmic-epoch nor the Ubuntu archive was" >&2
			echo "      measured to publish. apt fails the WHOLE install on" >&2
			echo "      an unknown name, not just that package." >&2
			fail=1
		fi
	done < <(apt_packages)
	[ "$fail" -eq 0 ]
}

# The loop above passes trivially if apt_packages returns nothing.
@test "the apt list is non-empty and includes the session" {
	run apt_packages
	[ "$(wc -l <<<"$output")" -ge 15 ]
	grep -qx 'cosmic-session' <<<"$output"
	grep -qx 'cosmic-comp' <<<"$output"
}
