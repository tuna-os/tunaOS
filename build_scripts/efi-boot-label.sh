#!/usr/bin/env bash
# Name the UEFI boot entry after the variant, not the upstream distro.
#
# WHY THIS EXISTS (tunaOS#4864)
#
# `bootc install` runs bootupd from the image being installed. bootupd creates
# the firmware boot entry for \EFI\<vendor>\shim*.efi and names it
# get_product_name(): /etc/system-release up to the word "release", or
# os-release NAME when that file is missing (bootupd src/efi.rs). The EL10 and
# Fedora bases point /etc/system-release at the distro's release file, so the
# installed yellowfin booted `Boot000A "AlmaLinux Kitten" \EFI\almalinux\
# shimx64.efi` (strict log t38, strict-plain-installed-serial.log:1) and bonito
# `"Fedora"`.
#
# shim's fallback.efi creates the same entry from EFI/<vendor>/BOOT<ARCH>.CSV
# when the firmware has none. That file is in bootupd's payload
# (/usr/lib/efi/shim/<ver>/EFI/<vendor>/ on bootupd 0.2.27+, or
# /usr/lib/bootupd/updates/EFI/<vendor>/). It is UTF-16LE with a BOM:
# "shimx64.efi,<label>,<options>,This is the boot entry for <label>".
#
# What this changes, after os-release names the variant:
#   - /etc/system-release becomes a link to /usr/lib/tunaos-release,
#     "<NAME> release <VERSION_ID>". Only where the base ships
#     /etc/system-release (the RPM bases). /etc/redhat-release,
#     /etc/<distro>-release and /etc/system-release-cpe stay as they are: those
#     are what tools read to learn the base. Nothing in this repository,
#     fisherman, tacklebox or wootc reads /etc/system-release; dnf finds
#     $releasever through the RPM provide system-release(releasever).
#   - The label and description fields of each payload CSV become NAME. The
#     CSV is not signed. Signed binaries and the \EFI\<vendor> directory are
#     untouched. bootupd's EFI.json records package versions only, and bootupd
#     records the installed file tree when it installs, so `bootupctl
#     validate` and updates compare against these bytes.
#
# 90-image-info.sh runs this after it writes os-release, on every base and
# again after each desktop install, which can reinstall a release package.
# TUNAOS_SYSROOT points every path at a fixture tree (tests).

set -euo pipefail

R="${TUNAOS_SYSROOT:-}"
value_of() { # <key> <file>
	sed -n "s/^${1}=//p" "$2" | tail -n 1 | tr -d "\"'"
}
name="$(value_of NAME "${R}/usr/lib/os-release")"
version="$(value_of VERSION_ID "${R}/usr/lib/os-release")"
if [[ -z "$name" ]]; then
	echo "efi-boot-label: ${R}/usr/lib/os-release has no NAME" >&2
	exit 1
fi

release="${R}/etc/system-release"
if [[ -e "$release" || -L "$release" ]]; then
	install -d "${R}/usr/lib"
	printf '%s release %s\n' "$name" "$version" >"${R}/usr/lib/tunaos-release"
	# -r: the link is ../usr/lib/tunaos-release, valid in the image and in a
	# fixture tree alike.
	ln -sfnr "${R}/usr/lib/tunaos-release" "$release"
	echo "efi-boot-label: /etc/system-release -> $(readlink "$release") ($(cat "$release"))"
else
	echo "efi-boot-label: no /etc/system-release; bootupd uses os-release NAME=${name}"
fi

mapfile -t csvs < <(find "${R}/usr/lib/efi" "${R}/usr/lib/bootupd/updates" \
	-type f -iname 'boot*.csv' 2>/dev/null | sort)
if ((${#csvs[@]})) && ! command -v iconv >/dev/null 2>&1; then
	echo "efi-boot-label: iconv is missing; cannot relabel ${csvs[*]}" >&2
	exit 1
fi
for csv in "${csvs[@]}"; do
	text="$(iconv -f UTF-16 -t UTF-8 "$csv")"
	relabelled="$(awk -F, -v OFS=, -v n="$name" \
		'NF >= 2 { $2 = n; if (NF >= 4) $4 = "This is the boot entry for " n } { print }' <<<"$text")"
	{
		printf '\xff\xfe'
		printf '%s\n' "$relabelled" | iconv -f UTF-8 -t UTF-16LE
	} >"${csv}.tunaos"
	chmod --reference="$csv" "${csv}.tunaos"
	mv -f "${csv}.tunaos" "$csv"
	echo "efi-boot-label: ${csv#"${R}"}: ${relabelled}"
done
