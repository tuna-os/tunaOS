#!/usr/bin/env bash
# Prove the UEFI boot entry this image creates is named after the variant.
#
#   verify-efi-boot-label.sh
#
# WHY THIS EXISTS (tunaOS#4864)
#
# The installed yellowfin booted `Boot000A "AlmaLinux Kitten"
# \EFI\almalinux\shimx64.efi` and bonito `"Fedora"`. This check computes the
# two labels the firmware can get from this image and fails the build unless
# both are os-release NAME:
#   - bootupd's product name, the label `bootc install` gives the entry. Same
#     rule as bootupd get_product_name() (src/efi.rs): /etc/system-release up
#     to the word "release", trimmed; os-release NAME when that file is missing.
#   - the label field of every shim fallback CSV (BOOT<ARCH>.CSV, UTF-16) in
#     bootupd's payload, /usr/lib/efi and /usr/lib/bootupd/updates. fallback.efi
#     creates the entry from it when the firmware has none.
# It also fails when NAME is an upstream distro name, which would make both
# comparisons pass for the wrong reason.
#
# TUNAOS_SYSROOT points every path at a fixture tree (tests).

set -euo pipefail

R="${TUNAOS_SYSROOT:-}"
value_of() { # <key> <file>
	sed -n "s/^${1}=//p" "$2" | tail -n 1 | tr -d "\"'"
}
fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}

name="$(value_of NAME "${R}/usr/lib/os-release")"
echo "== UEFI boot entry label: os-release NAME='${name}' =="
if [[ -z "$name" ]]; then
	fail "os-release has no NAME"
elif grep -qiwE 'almalinux|alma linux|kitten|centos|fedora|rhel|red hat|rocky|ubuntu|debian|opensuse|suse|gentoo|arch linux|archlinux' <<<"$name"; then
	fail "os-release NAME='${name}' is an upstream name"
fi

release="${R}/etc/system-release"
if [[ -e "$release" ]]; then
	contents="$(cat "$release")"
	product="${contents%%release*}"
	source_file="/etc/system-release"
else
	product="$(value_of NAME "${R}/etc/os-release" 2>/dev/null || true)"
	product="${product:-$(value_of NAME "${R}/usr/lib/os-release")}"
	source_file="os-release NAME"
fi
product="$(sed 's/^[[:space:]]*//; s/[[:space:]]*$//' <<<"$product")"
if [[ "$product" == "$name" ]]; then
	echo "  ok: bootupd product name '${product}' (from ${source_file})"
else
	fail "bootupd would name the boot entry '${product}' (from ${source_file}), want '${name}'"
fi

csv_count=0
while IFS= read -r csv; do
	csv_count=$((csv_count + 1))
	if ! command -v iconv >/dev/null 2>&1; then
		fail "iconv is missing; cannot read ${csv#"${R}"}"
		continue
	fi
	while IFS=, read -r loader label _; do
		[[ -n "$loader" ]] || continue
		if [[ "$label" == "$name" ]]; then
			echo "  ok: ${csv#"${R}"}: ${loader} -> '${label}'"
		else
			fail "${csv#"${R}"}: ${loader} is labelled '${label}', want '${name}'"
		fi
	done < <(iconv -f UTF-16 -t UTF-8 "$csv" | tr -d '\r')
done < <(find "${R}/usr/lib/efi" "${R}/usr/lib/bootupd/updates" -type f -iname 'boot*.csv' 2>/dev/null | sort)

if ((fails)); then
	echo "TUNAOS_EFI_LABEL_FAIL name=${name// /_} product=${product// /_} csvs=${csv_count} failures=${fails}" >&2
	exit 1
fi
echo "TUNAOS_EFI_LABEL_OK name=${name// /_} product=${product// /_} csvs=${csv_count}"
