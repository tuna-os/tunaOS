#!/bin/bash
# dracut module: name the initramfs after the variant (tunaOS#4865).
#
# dracut-systemd (77) writes usr/lib/initrd-release from /etc/os-release at
# the time dracut runs. On EL10, Fedora, Arch, Debian, Gentoo and openSUSE that
# is before 90-image-info.sh, so it said NAME="AlmaLinux Kitten" and
# PRETTY_NAME="AlmaLinux Kitten 10 (Lion Cub) dracut-107-11.el10 (Initramfs)"
# (published yellowfin:base). systemd prints "Welcome to <PRETTY_NAME>!" from
# it in early boot. This module runs after 77 and rewrites both from
# DEFAULT_HOSTNAME, which initrd-hostname.sh sets before dracut runs. The name
# is DEFAULT_HOSTNAME with a capital first letter, the NAME 90-image-info.sh
# writes later. PRETTY_NAME is "<Name> (Initramfs)" without dracut's version:
# openSUSE's dracut is "112+suse.63.g62ea8ea-1", so sailfin greeted early boot
# with "Welcome to Sailfin dracut-112+suse.63... (Initramfs)!" (Gate, run
# 44910904203). It also writes DEFAULT_HOSTNAME itself: Debian's dracut copies
# only some os-release keys, so flounder's initrd-release had NAME but no
# DEFAULT_HOSTNAME, and verify-initrd-hostname.sh stopped every flounder build
# (canary flounder:xfce, runs 44910904203 and 44927176620). initrd-hostname.sh
# installs the module into the image, so tacklebox's ISO rebuild and every
# later dracut run apply it as well.

check() {
	return 0
}

depends() {
	return 0
}

install() {
	local release="${initdir}/usr/lib/initrd-release" host name
	[[ -f "$release" ]] || return 0
	host="$(sed -n 's/^DEFAULT_HOSTNAME=//p' "${dracutsysrootdir-}/usr/lib/os-release" | tail -n 1 | tr -d "\"'")"
	[[ -n "$host" ]] || return 0
	name="${host^}"
	# Delete then append: Debian's dracut writes no PRETTY_NAME line, so a
	# substitution alone left it empty (canary flounder:xfce, PR #4989).
	sed -i -e '/^NAME=/d' -e '/^PRETTY_NAME=/d' -e '/^DEFAULT_HOSTNAME=/d' "$release"
	printf 'NAME="%s"\nPRETTY_NAME="%s (Initramfs)"\n' "$name" "$name" >>"$release"
	printf 'DEFAULT_HOSTNAME="%s"\n' "$host" >>"$release"
}
