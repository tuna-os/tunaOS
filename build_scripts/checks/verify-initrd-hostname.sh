#!/usr/bin/env bash
# Prove the initramfs names the variant's hostname, not the upstream fallback.
#
#   verify-initrd-hostname.sh <initramfs.img>
#
# WHY THIS EXISTS (tunaOS#4865)
#
# PID 1 sets the hostname inside the initramfs from DEFAULT_HOSTNAME in
# usr/lib/initrd-release, else from systemd's compiled fallback. A system
# without /etc/hostname keeps that name after switch-root. The published
# yellowfin:base initramfs had the upstream AlmaLinux Kitten os-release there,
# with no DEFAULT_HOSTNAME (live: `localhost login:`). Fedora's own os-release
# says DEFAULT_HOSTNAME="fedora" (live bonito: `fedora login:`).
# initrd-hostname.sh now sets the key before dracut runs. This check runs
# after dracut and stops the build when:
#   - initrd-release has no DEFAULT_HOSTNAME;
#   - it is an upstream name;
#   - it differs from DEFAULT_HOSTNAME in the image's os-release;
#   - it differs from the name initrd-hostname.sh --print gives this build.
#
# TUNAOS_SYSROOT points the image-root side at another tree (tests).
# lsinitrd is the dracut tool. Without it the check fails, because then
# nothing is proven.

set -euo pipefail

initramfs="${1:?usage: verify-initrd-hostname.sh <initramfs.img>}"
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
R="${TUNAOS_SYSROOT:-}"

# Names systemd, the distro or a cloud image fall back to. None is a variant.
upstream='^(localhost|fedora|almalinux|centos|rhel|rocky|ubuntu|debian|archlinux|arch|opensuse|suse|gentoo|linux)$'

value_of() { # <key> <file>
	sed -n "s/^${1}=//p" "$2" | tail -n 1 | tr -d "\"'"
}

fail() {
	echo "  FAIL: $*" >&2
	echo "TUNAOS_INITRD_HOSTNAME_FAIL initramfs=${initramfs} hostname=${got:-}" >&2
	exit 1
}

command -v lsinitrd >/dev/null 2>&1 || fail "lsinitrd is unavailable; cannot read the initramfs's initrd-release"
[[ -s "$initramfs" ]] || fail "missing or empty initramfs: ${initramfs}"

release="$(mktemp)"
trap 'rm -f "$release"' EXIT
# dracut writes usr/lib/initrd-release; etc/initrd-release links to it.
lsinitrd -f usr/lib/initrd-release "$initramfs" >"$release" 2>/dev/null || true
[[ -s "$release" ]] || lsinitrd -f etc/initrd-release "$initramfs" >"$release" 2>/dev/null || true
[[ -s "$release" ]] || fail "the initramfs has no usr/lib/initrd-release"

got="$(value_of DEFAULT_HOSTNAME "$release")"
image="$(value_of DEFAULT_HOSTNAME "${R}/usr/lib/os-release")"
want="$("${here}/../initrd-hostname.sh" --print)"
echo "== initramfs hostname: initrd-release DEFAULT_HOSTNAME='${got}', os-release '${image}', build '${want}' =="

[[ -n "$got" ]] || fail "initrd-release has no DEFAULT_HOSTNAME; PID 1 sets systemd's compiled fallback (NAME there: $(value_of NAME "$release"))"
if [[ "${got,,}" =~ $upstream ]]; then
	fail "initrd-release DEFAULT_HOSTNAME='${got}' is an upstream name"
fi
[[ "$got" == "$image" ]] || fail "initrd-release DEFAULT_HOSTNAME='${got}', image os-release has '${image}'"
[[ "$got" == "$want" ]] || fail "initrd-release DEFAULT_HOSTNAME='${got}', this build is '${want}'"
# systemd prints "Welcome to <PRETTY_NAME>!" from initrd-release in early boot.
name="$(value_of NAME "$release")"
pretty="$(value_of PRETTY_NAME "$release")"
[[ "$name" == "${want^}" ]] || fail "initrd-release NAME='${name}', want '${want^}' (the 99tunaos-identity dracut module did not run)"
# Exactly "<Name> (Initramfs)": dracut's own version string can name the base
# (openSUSE's "dracut-112+suse.63...").
[[ "$pretty" == "${want^} (Initramfs)" ]] || fail "initrd-release PRETTY_NAME='${pretty}', want '${want^} (Initramfs)'"
echo "TUNAOS_INITRD_HOSTNAME_OK hostname=${got} name=${name} pretty=${pretty// /_}"
