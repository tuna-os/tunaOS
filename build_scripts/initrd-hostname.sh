#!/usr/bin/env bash
# Give the initramfs the variant's DEFAULT_HOSTNAME before dracut builds it.
#
#   initrd-hostname.sh           # write DEFAULT_HOSTNAME into os-release
#   initrd-hostname.sh --print   # print the name, change nothing
#
# WHY THIS EXISTS (tunaOS#4865)
#
# PID 1 sets the hostname first inside the initramfs. With no /etc/hostname
# it uses DEFAULT_HOSTNAME from the initramfs's os-release
# (usr/lib/initrd-release), else systemd's compiled fallback ("localhost" on
# EL). After switch-root, a system without /etc/hostname keeps the name the
# initramfs set (systemd src/shared/hostname-setup.c, hostname_setup()).
# dracut's dracut-systemd module writes initrd-release from the image's
# /etc/os-release at the time dracut runs.
#
# On EL10, Fedora, Arch, Debian, Gentoo and openSUSE, dracut runs before
# 90-image-info.sh writes the identity, so initrd-release is the upstream
# os-release. Measured: the published yellowfin:base initramfs has
# NAME="AlmaLinux Kitten" and no DEFAULT_HOSTNAME; fedora-bootc:43's
# os-release says DEFAULT_HOSTNAME="fedora". The live sessions showed
# `localhost login:` (yellowfin) and `fedora login:` (bonito). This script
# runs right before each of those dracut runs and sets that one key.
# 90-image-info.sh later writes the full identity with the same value. An
# installer-written /etc/hostname still wins after switch-root.
#
# The name is the one 90-image-info.sh gives DEFAULT_HOSTNAME: IMAGE_NAME
# (the publish name), else IMAGE_NAME_VARIANT, folded through the alias table.
# No name is an error: a guessed one is the upstream leak this prevents.
#
# TUNAOS_SYSROOT points the os-release side at a fixture tree (tests).

set -euo pipefail

print_only=false
if [[ "${1:-}" == --print ]]; then
	print_only=true
fi

lib="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib"
name="${IMAGE_NAME:-${IMAGE_NAME_VARIANT:-}}"
if [[ -z "$name" ]]; then
	echo "initrd-hostname: neither IMAGE_NAME nor IMAGE_NAME_VARIANT is set; refusing to guess a hostname" >&2
	exit 1
fi
owner="$(awk -F'\t' -v alias="$name" '$1 == alias { print $2 }' "${lib}/variant-aliases.tsv")"
name="${owner:-$name}"
if $print_only; then
	echo "$name"
	exit 0
fi

R="${TUNAOS_SYSROOT:-}"
usr="${R}/usr/lib/os-release"
etc="${R}/etc/os-release"
files=("$usr")
if [[ -e "$etc" ]] && ! [[ "$etc" -ef "$usr" ]]; then
	files+=("$etc")
fi
for file in "${files[@]}"; do
	if grep -q '^DEFAULT_HOSTNAME=' "$file"; then
		sed -i "s|^DEFAULT_HOSTNAME=.*|DEFAULT_HOSTNAME=\"${name}\"|" "$file"
	else
		echo "DEFAULT_HOSTNAME=\"${name}\"" >>"$file"
	fi
done
echo "initrd-hostname: DEFAULT_HOSTNAME=${name} in ${files[*]}"

# The initramfs NAME and PRETTY_NAME follow from the same key: the module
# rewrites them in initrd-release after dracut-systemd writes it.
module="${R}/usr/lib/dracut/modules.d/99tunaos-identity"
install -Dm0755 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/dracut/99tunaos-identity/module-setup.sh" \
	"${module}/module-setup.sh"
echo "initrd-hostname: installed ${module#"${R}"}"
