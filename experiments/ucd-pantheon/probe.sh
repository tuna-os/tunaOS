#!/usr/bin/env bash
# Probe: can Pantheon's session core build against the Ubuntu 26.04 (core26)
# library set? For each component, try the newest release tag, then main.
# Runs inside ubuntu:26.04. Prints a Markdown table.
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq --no-install-recommends ca-certificates git meson ninja-build valac gettext sassc pkg-config \
	libglib2.0-dev libgtk-4-dev libgtk-3-dev libadwaita-1-dev libgee-0.8-dev libgranite-7-dev libgnome-desktop-4-dev \
	libmutter-18-dev libhandy-1-dev libsqlite3-dev libsystemd-dev systemd-dev libibus-1.0-dev gobject-introspection \
	libgirepository1.0-dev libatk-bridge2.0-dev libgdk-pixbuf-2.0-dev libwayland-dev wayland-protocols \
	desktop-file-utils appstream libgnome-bg-4-dev libpolkit-gobject-1-dev libpolkit-agent-1-dev libfwupd-dev \
	libpackagekit-glib2-dev libgexiv2-dev libgeoclue-2-dev libaccountsservice-dev liblightdm-gobject-1-dev \
	libxml2-utils libnm-dev libglib2.0-dev-bin libgtk-4-bin libjson-glib-dev libcanberra-dev libpulse-dev \
	libgnome-desktop-3-dev libxfixes-dev libxi-dev libxcursor-dev libxdamage-dev libxext-dev libxcomposite-dev \
	libxkbcommon-dev libinput-dev libgraphene-1.0-dev libdrm-dev libgbm-dev libudev-dev libgl-dev libegl-dev \
	libsecret-1-dev libwacom-dev libgcr-4-dev >/dev/null 2>&1 || echo "apt install failed"
mkdir -p /src /out
cd /src
tag_of() {
	case $1 in
	granite) echo 6.2.0 ;;
	pantheon-wayland) echo 1.1.0 ;;
	gala) echo 8.6.2 ;;
	wingpanel) echo 8.0.4 ;;
	greeter) echo 8.1.2 ;;
	settings) echo 8.0.3 ;;
	settings-daemon) echo 8.5.0 ;;
	notifications) echo 8.1.2 ;;
	portals) echo 8.2.0 ;;
	pantheon-agent-polkit) echo 8.1.0 ;;
	dock) echo 8.3.3 ;;
	stylesheet) echo 8.2.2 ;;
	default-settings) echo 8.1.1 ;;
	session-settings) echo 8.1.0 ;;
	esac
}
echo '| Component | Release tag | Tag builds | main builds |'
echo '| :--- | :--- | :--- | :--- |'
try() { # repo ref tag
	local r=$1 ref=$2 d="/src/$1-$2"
	rm -rf "$d"
	git clone -q --depth=1 -b "$ref" "https://github.com/elementary/$r" "$d" 2>/dev/null || {
		echo "no-ref"
		return
	}
	if meson setup "$d/build" "$d" --prefix=/usr >"/out/$r-$ref.setup.log" 2>&1 && ninja -C "$d/build" >"/out/$r-$ref.build.log" 2>&1; then
		case $r in granite | pantheon-wayland | gala)
			ninja -C "$d/build" install >/dev/null 2>&1
			ldconfig
			;;
		esac
		echo "yes"
	else
		echo "no: $(grep -h -m1 -E 'ERROR|error:' /out/$r-$ref.setup.log /out/$r-$ref.build.log 2>/dev/null | head -1 | sed 's/|/\\|/g' | cut -c1-110)"
	fi
}
for r in ${COMPONENTS:-granite pantheon-wayland gala wingpanel greeter settings settings-daemon notifications portals pantheon-agent-polkit dock stylesheet default-settings session-settings}; do
	tag=$(tag_of "$r")
	t=$(try "$r" "$tag")
	if [ "$t" = yes ]; then m="(not needed)"; else m=$(try "$r" main); fi
	echo "| $r | $tag | $t | $m |"
done
