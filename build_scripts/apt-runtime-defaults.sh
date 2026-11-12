#!/usr/bin/env bash
# Runtime state apt-based (Debian/Ubuntu) images must carry in /etc and /usr
# because bootc does not seed the image's /var. 99-cleanup.sh runs this before
# it wipes /var. ROOT (default: empty, i.e. /) lets tests apply it to a tree.
#
# Measured on grouper:gnome (tunaOS#4448, iso-builder run 42912845462):
#
#   * /etc/default/locale is a symlink to ../locale.conf and nothing writes
#     /etc/locale.conf (the `locales` package that would is not installed;
#     locales-all is). accountsservice's Ubuntu language patch reads the system
#     default from /etc/default/locale, logs `Couldn't get validated language:
#     Child process exited with code 1`, and User.SetLanguage then never
#     returns (gdbus call times out after 20 s; libaccountsservice blocked
#     >60 s). GNOME Initial Setup calls it when it saves the account and shows
#     "Initial Setup is not responding" until the strict harness powers off.
#     With LANG=C.UTF-8 in /etc/locale.conf, SetLanguage returns in 0 s.
#   * pwquality logs `/var/cache/cracklib/cracklib_dict.pwd: No such file or
#     directory` every 6 s while the account page is open: cracklib-runtime
#     (only a Recommends of libcrack2) was not installed, and the dictionary
#     its update-cracklib writes lives under /var/cache, which the wipe removes.
set -euo pipefail

ROOT="${ROOT:-}"

# A system locale. `-e` follows the symlink, so a dangling
# /etc/default/locale -> ../locale.conf counts as missing. C.UTF-8 is built
# into glibc and exists on every flavor; GNOME Initial Setup and localed
# overwrite /etc/locale.conf with the user's choice.
if [[ ! -e "${ROOT}/etc/default/locale" ]]; then
	[[ -e "${ROOT}/etc/locale.conf" ]] || printf 'LANG=C.UTF-8\n' >"${ROOT}/etc/locale.conf"
	mkdir -p "${ROOT}/etc/default"
	ln -sfnT ../locale.conf "${ROOT}/etc/default/locale"
fi

# The cracklib dictionary, moved to /usr (where Fedora ships it) and linked
# back. L+ replaces whatever is at the path, so a /var reset re-establishes the
# link; tmpfiles does not create parents for L+, hence the /var/cache line.
dict="${ROOT}/var/cache/cracklib"
if [[ -f "${dict}/cracklib_dict.pwd" && ! -L "${dict}" ]]; then
	rm -rf "${ROOT}/usr/share/cracklib"
	mkdir -p "${ROOT}/usr/share"
	cp -a "${dict}" "${ROOT}/usr/share/cracklib"
	rm -rf "${dict}"
	ln -sT ../../usr/share/cracklib "${dict}"
	mkdir -p "${ROOT}/usr/lib/tmpfiles.d"
	printf 'd /var/cache 0755 root root -\nL+ /var/cache/cracklib - - - - ../../usr/share/cracklib\n' \
		>"${ROOT}/usr/lib/tmpfiles.d/cracklib-usr.conf"
fi
