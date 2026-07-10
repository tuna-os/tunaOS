#!/usr/bin/env bash
# gnome-extensions.sh — Build GNOME Shell extensions from source.
#
# Split from gnome.sh so the DE package layer can cache independently
# of extension source changes (submodule updates). This script:
#   1. Installs build tooling (glib2-devel, meson, sassc, cmake, dbus-devel)
#   2. Compiles each extension
#   3. Removes build tooling
#   4. Version-locks the GNOME stack
#
# Run AFTER gnome.sh — requires gnome-shell to already be installed.

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

# ── apt (Ubuntu/Debian) path ──────────────────────────────────────────
if [[ "$PKG_MGR" == "apt" ]]; then
	# Ubuntu ships pre-built extensions; just compile schemas
	if command -v glib-compile-schemas &>/dev/null; then
		glib-compile-schemas /usr/share/glib-2.0/schemas
	fi
	exit 0
fi

# ── Non-dnf RPM-less distros (openSUSE/Gentoo/Arch) ────────────────────
# The source extension build below installs tooling via dnf. Those distros
# don't have dnf, so skip the custom build (compile schemas only) rather than
# fail with "dnf: command not found" (exit 127).
if ! command -v dnf &>/dev/null; then
	command -v glib-compile-schemas &>/dev/null && \
		glib-compile-schemas /usr/share/glib-2.0/schemas || true
	echo "gnome-extensions.sh: skipping source-built extensions on ${PKG_MGR}"
	# Sourced by install-desktop.sh's post_install; return so we don't exit it.
	return 0 2>/dev/null || exit 0
fi
# ── dnf (RPM) path continues below ────────────────────────────────────

printf "::group:: === GNOME Extensions Build ===\n"

# Remove versionlock on glib2 to allow installing glib2-devel (will re-lock after)
warn_on_fail dnf versionlock delete glib2

# Install build tooling
dnf_retry -y install glib2-devel meson sassc cmake dbus-devel unzip

# AppIndicator Support (not present in all GNOME versions/COPRs)
if [ -d /usr/share/gnome-shell/extensions/appindicatorsupport@rgcjonas.gmail.com/schemas ]; then
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/appindicatorsupport@rgcjonas.gmail.com/schemas
fi

# Blur My Shell (requires gnome-extensions pack from gnome-shell)
# We build it and then unzip it into its final location to ensure the structure is correct
if [ -d /usr/share/gnome-shell/extensions/blur-my-shell@aunetx ]; then
	if [ -f /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/Makefile ]; then
		make -C /usr/share/gnome-shell/extensions/blur-my-shell@aunetx build
		unzip -o /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/build/blur-my-shell@aunetx.shell-extension.zip -d /usr/share/gnome-shell/extensions/blur-my-shell@aunetx
		glib-compile-schemas --strict /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/schemas
		rm -rf /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/build
	else
		echo "Skipping blur-my-shell build (Makefile not found)"
	fi
fi

# Caffeine
# The Caffeine extension is in system_files/usr/share/gnome-shell/extensions/tmp/caffeine/caffeine@patapon.info
if [ -d /usr/share/gnome-shell/extensions/tmp/caffeine/caffeine@patapon.info ]; then
	mv /usr/share/gnome-shell/extensions/tmp/caffeine/caffeine@patapon.info /usr/share/gnome-shell/extensions/caffeine@patapon.info
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/caffeine@patapon.info/schemas
fi

# Dash to Dock
if [ -d /usr/share/gnome-shell/extensions/dash-to-dock@micxgx.gmail.com ]; then
	if [ -f /usr/share/gnome-shell/extensions/dash-to-dock@micxgx.gmail.com/Makefile ]; then
		make -C /usr/share/gnome-shell/extensions/dash-to-dock@micxgx.gmail.com
		glib-compile-schemas --strict /usr/share/gnome-shell/extensions/dash-to-dock@micxgx.gmail.com/schemas
	else
		echo "Skipping dash-to-dock build (Makefile not found)"
	fi
fi

# GSConnect
if [ -d /usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io ]; then
	if [ -f /usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io/meson.build ]; then
		meson setup --prefix=/usr /usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io /usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io/_build
		meson install -C /usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io/_build --skip-subprojects
		# GSConnect installs schemas to /usr/share/glib-2.0/schemas and meson compiles them automatically
	else
		echo "Skipping GSConnect build (meson.build not found)"
	fi
fi

# Gradia Capture — area screenshot integration for the Gradia screenshot
# app. (Ported from ublue-os/bluefin-lts d32c9ea3 — feat(extension):
# Add gradia capture extension.) Build mirrors blur-my-shell: `build.sh`
# inside the submodule produces a shell-extension.zip which we unzip in
# place, then compile the schemas.
if [ -d /usr/share/gnome-shell/extensions/gradia-integration@alexandervanhee.github.io ]; then
	if [ -f /usr/share/gnome-shell/extensions/gradia-integration@alexandervanhee.github.io/build.sh ]; then
		bash /usr/share/gnome-shell/extensions/gradia-integration@alexandervanhee.github.io/build.sh
		unzip -o /usr/share/gnome-shell/extensions/gradia-integration@alexandervanhee.github.io/gradia-integration@alexandervanhee.github.io.shell-extension.zip \
			-d /usr/share/gnome-shell/extensions/gradia-integration@alexandervanhee.github.io
		rm -f /usr/share/gnome-shell/extensions/gradia-integration@alexandervanhee.github.io/gradia-integration@alexandervanhee.github.io.shell-extension.zip
		glib-compile-schemas --strict /usr/share/gnome-shell/extensions/gradia-integration@alexandervanhee.github.io/schemas
	else
		echo "Skipping gradia-capture build (build.sh not found)"
	fi
fi

# Logo Menu
# xdg-terminal-exec is required for this extension as it opens up terminals using that script
# Only install if submodule is present
if [ -f /usr/share/gnome-shell/extensions/logomenu@aryan_k/distroshelf-helper ]; then
	install -Dpm0755 -t /usr/bin /usr/share/gnome-shell/extensions/logomenu@aryan_k/distroshelf-helper
	install -Dpm0755 -t /usr/bin /usr/share/gnome-shell/extensions/logomenu@aryan_k/missioncenter-helper
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/logomenu@aryan_k/schemas
else
	echo "Skipping logomenu (submodule not available)"
fi

# Search Light
if [ -d /usr/share/gnome-shell/extensions/search-light@icedman.github.com/schemas ]; then
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/search-light@icedman.github.com/schemas
else
	echo "Skipping search-light (submodule not available)"
fi

# Recompile all schemas
rm -f /usr/share/glib-2.0/schemas/gschemas.compiled
glib-compile-schemas /usr/share/glib-2.0/schemas

# Cleanup build tooling
dnf_retry -y remove glib2-devel meson sassc cmake dbus-devel
rm -rf /usr/share/gnome-shell/extensions/tmp

# Disable GNOME COPR if it was left enabled by gnome.sh
# (gnome.sh no longer disables it — we do it here after build tooling is gone)
for copr_file in /etc/yum.repos.d/_copr:copr.fedorainfracloud.org:jreilly1821:c10s-gnome-*.repo; do
	if [ -f "$copr_file" ]; then
		sed -i 's/^enabled=1/enabled=0/' "$copr_file"
	fi
done

# Versionlock glib2 and the full GNOME stack to prevent dnf from upgrading
# back to whatever EL10 ships by default (which may not be the COPR version)
dnf versionlock add \
	glib2 \
	fontconfig \
	gdm \
	gnome-shell \
	mutter \
	gnome-session-wayland-session \
	gnome-settings-daemon \
	gnome-control-center \
	gsettings-desktop-schemas \
	gtk4 \
	libadwaita \
	pango \
	xdg-desktop-portal \
	xdg-desktop-portal-gnome || true

printf "::endgroup::\n"
