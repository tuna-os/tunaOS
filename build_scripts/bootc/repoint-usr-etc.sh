#!/usr/bin/env bash
# Repoint display-manager config at /etc once /usr/etc is gone.
#
# openSUSE ships vendor config under /usr/etc. A bootc image may not carry
# /usr/etc (ostree owns that path), so Containerfile.opensuse copies it into
# /etc and deletes it. Shell scripts survive that: they try /etc first and fall
# back to /usr/etc. LightDM's vendor defaults do not. Tumbleweed's
# /usr/share/lightdm/lightdm.conf.d/50-suse-defaults.conf names
#
#   session-wrapper=/usr/etc/X11/xdm/Xsession
#   session-setup-script=/usr/etc/X11/xdm/Xstartup
#
# so every LightDM login on sailfin:xfce, autologin included, ran a script that
# did not exist. The greeter still painted, because /etc/lightdm/lightdm.conf
# overrides greeter-setup-script. The live session sat at the "Live User"
# greeter with no xfce4-session process (iso-builder run 43439582829, sysrq task
# dump on serial).
#
# Rewrite only a path whose /etc copy exists, so a reference to something the
# move did not produce stays visibly broken rather than silently wrong.
#
# Usage: repoint-usr-etc.sh [ROOT]   (ROOT prefixes paths, for tests)
set -euo pipefail

root="${1:-}"
shopt -s nullglob
for conf in "${root}"/usr/share/lightdm/lightdm.conf.d/*.conf \
	"${root}"/usr/lib/sddm/sddm.conf.d/*.conf; do
	while IFS= read -r ref; do
		target="/etc/${ref#/usr/etc/}"
		if [[ -e "${root}${target}" ]]; then
			sed -i "s#\(=[[:space:]]*\)${ref}[[:space:]]*\$#\1${target}#" "${conf}"
			echo "repoint-usr-etc: ${conf#"${root}"}: ${ref} -> ${target}"
		else
			echo "repoint-usr-etc: WARNING ${conf#"${root}"} names ${ref}; ${target} does not exist" >&2
		fi
	done < <(grep -oE '=[[:space:]]*/usr/etc/[^[:space:]]+' "${conf}" | sed -E 's/^=[[:space:]]*//' | sort -u)
done
