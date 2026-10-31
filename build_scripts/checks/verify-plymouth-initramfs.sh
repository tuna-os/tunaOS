#!/usr/bin/env bash
# Prove the variant's own boot splash is what the initramfs will draw.
#
#   verify-plymouth-initramfs.sh <variant> <initramfs.img>
#
# WHY THIS EXISTS (tunaOS#4104)
#
# plymouthd starts inside the initramfs, so the splash a user sees is the one
# dracut copied in, not whatever sits under /usr/share/plymouth in the image.
# The old branding check (verify-branding.sh, "TunaOS plymouth theme active")
# passed whenever /usr/share/plymouth/themes/tunaos existed, which it does on
# every variant. So bonito-rawhide could build with Bonito's fishing-pole in
# its initramfs instead of its own dragon (26-packages-post.sh handed the
# selector the publish name "bonito"), and nothing noticed.
#
# The expected theme comes from plymouth-set-theme.sh --print, i.e. the same
# generated adapter (variant-identity.tsv from tunaos.toml) the selector uses,
# so there is no second variant-to-theme table to drift. <variant> must be the
# canonical id (IMAGE_NAME_VARIANT), not the publish name.
#
# What is asserted, against the image root and then against the unpacked
# initramfs (lsinitrd --unpack, the dracut tool; no lsinitrd is a FAIL, not a
# skip, because then nothing here is proven):
#   - /etc/plymouth/plymouthd.conf Theme= is the variant's theme
#     (plymouth-populate-initrd copies it and plymouthd reads it first);
#   - default.plymouth links to that theme;
#   - the initramfs carries that theme's .plymouth, its ScriptFile, every
#     frame its script loads, and the plugin its ModuleName names;
#   - every theme file is byte-identical (sha256) to the image's copy, and the
#     initramfs has none the image lacks: stale artwork fails;
#   - no other TunaOS theme (a sibling variant's, or the generic fish) is in
#     the initramfs. Having *a* TunaOS theme is not having the right one.
#
# Exit 0 is the variant's splash, 1 is a wrong or incomplete one. Exit 2,
# TUNAOS_PLYMOUTH_BLOCKED, is an image that cannot draw any TunaOS splash:
# no plymouthd, or no plugin the theme's ModuleName names. Those are exactly
# the cases where plymouth-set-theme.sh keeps the distro theme on purpose, so
# the reason is printed and the caller decides whether that is acceptable.
#
# PLYMOUTH_SYSROOT (plymouth-populate-initrd's own name for it) points the
# image-root side at another tree; builds leave it unset.

set -euo pipefail

variant="${1:?usage: verify-plymouth-initramfs.sh <variant> <initramfs.img>}"
initramfs="${2:?usage: verify-plymouth-initramfs.sh <variant> <initramfs.img>}"
sysroot="${PLYMOUTH_SYSROOT:-}"
themes_rel=usr/share/plymouth/themes

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
lib="${here}/../lib"

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

# <root> <module>: the plugin, where Fedora (lib64) or Debian (multiarch) put it.
has_plugin() {
	compgen -G "${1}/usr/lib*/plymouth/${2}.so" >/dev/null ||
		compgen -G "${1}/usr/lib*/*/plymouth/${2}.so" >/dev/null
}
module_of() {
	sed -n 's/^ModuleName[[:space:]]*=[[:space:]]*//p' "$1" 2>/dev/null | head -n 1
}

theme="$("${here}/../plymouth-set-theme.sh" --print "$variant")"
echo "== plymouth theme for ${variant}: ${theme} =="

# Every TunaOS theme some variant (or the project default) selects. Any of
# these other than ${theme} inside the initramfs is another variant's art.
# shellcheck source=../lib/identity.env
source "${lib}/identity.env"
mapfile -t tunaos_themes < <(
	{
		awk -F'\t' '!/^#/ && NF >= 6 { print $6 }' "${lib}/variant-identity.tsv"
		echo "${TUNAOS_PLYMOUTH_THEME}"
	} | sort -u
)

conf_theme() {
	sed -n 's/^[[:space:]]*Theme[[:space:]]*=[[:space:]]*//p' "$1" 2>/dev/null | tail -n 1
}

# <label> <root>: plymouthd.conf and default.plymouth inside <root>.
check_selection() {
	local label="$1" root="$2" got link
	got="$(conf_theme "${root}/etc/plymouth/plymouthd.conf")"
	if [[ "$got" == "$theme" ]]; then
		pass "${label} plymouthd.conf Theme=${got}"
	else
		fail "${label} plymouthd.conf Theme='${got}', want '${theme}'"
	fi
	link="${root}/${themes_rel}/default.plymouth"
	if [[ ! -L "$link" ]]; then
		fail "${label} has no default.plymouth link (want ${theme}/${theme}.plymouth)"
	elif [[ "$(readlink "$link")" == "${theme}/${theme}.plymouth" ||
		"$(readlink "$link")" == "/${themes_rel}/${theme}/${theme}.plymouth" ]]; then
		pass "${label} default.plymouth -> $(readlink "$link")"
	else
		fail "${label} default.plymouth -> '$(readlink "$link")', want ${theme}/${theme}.plymouth"
	fi
}

echo "== image root =="
image_theme="${sysroot}/${themes_rel}/${theme}"
if [[ -f "${image_theme}/${theme}.plymouth" ]]; then
	pass "image ships ${themes_rel}/${theme}"
	# The selector's own reasons to keep the distro splash (plymouth-set-theme.sh).
	image_module="$(module_of "${image_theme}/${theme}.plymouth")"
	blocked=""
	if ! command -v plymouthd >/dev/null 2>&1 && ! compgen -G "${sysroot}/usr/*bin/plymouthd" >/dev/null; then
		blocked="plymouth is not installed in the image"
	elif [[ -n "$image_module" ]] && ! has_plugin "$sysroot" "$image_module"; then
		blocked="the image lacks the plymouth ${image_module} plugin ${theme} needs"
	fi
	if [[ -n "$blocked" ]]; then
		echo "  BLOCKED: ${blocked}; the distro splash stays" >&2
		echo "TUNAOS_PLYMOUTH_BLOCKED variant=${variant} theme=${theme} reason=${blocked// /_}" >&2
		exit 2
	fi
else
	fail "image has no ${themes_rel}/${theme}/${theme}.plymouth to compare against"
fi
check_selection image "${sysroot:-/}"

echo "== initramfs =="
unpacked="$(mktemp -d)"
trap 'rm -rf "$unpacked"' EXIT
if [[ ! -s "$initramfs" ]]; then
	fail "missing or empty initramfs: ${initramfs}"
elif ! command -v lsinitrd >/dev/null 2>&1; then
	fail "lsinitrd is unavailable; cannot show which splash the initramfs carries"
else
	img="$(readlink -f "$initramfs")"
	# The exit status is not the verdict: an extractor can complain about a
	# node it may not create and still unpack every file. The files are.
	(cd "$unpacked" && lsinitrd --unpack "$img" >/dev/null 2>&1) ||
		echo "  note: lsinitrd --unpack exited non-zero; judging the unpacked files" >&2
	if [[ ! -d "${unpacked}/etc" && ! -d "${unpacked}/usr" ]]; then
		fail "nothing unpacked from ${initramfs}"
	else
		check_selection initramfs "$unpacked"
		initrd_theme="${unpacked}/${themes_rel}/${theme}"
		def="${initrd_theme}/${theme}.plymouth"
		if [[ ! -f "$def" ]]; then
			fail "initramfs lacks ${themes_rel}/${theme}/${theme}.plymouth"
		else
			pass "initramfs carries ${themes_rel}/${theme}/${theme}.plymouth"

			module="$(module_of "$def")"
			if [[ -z "$module" ]]; then
				fail "${theme}.plymouth names no ModuleName"
			elif has_plugin "$unpacked" "$module"; then
				pass "initramfs carries the ${module} plugin"
			else
				fail "initramfs lacks the ${module}.so plugin ${theme} needs; plymouth falls back to text"
			fi

			script="$(sed -n 's/^ScriptFile[[:space:]]*=[[:space:]]*//p' "$def" | head -n 1)"
			if [[ "$module" == script ]]; then
				if [[ -n "$script" && -f "${unpacked}/${script#/}" ]]; then
					pass "initramfs carries ScriptFile ${script}"
					frames="$(sed -n 's/^FRAME_COUNT = \([0-9]*\);.*/\1/p' "${unpacked}/${script#/}")"
					missing=0
					for ((i = 1; i <= ${frames:-0}; i++)); do
						compgen -G "${initrd_theme}/*-$(printf '%04d' "$i").png" >/dev/null || missing=$((missing + 1))
					done
					if [[ -z "$frames" ]]; then
						fail "${script} declares no FRAME_COUNT"
					elif [[ "$missing" -gt 0 ]]; then
						fail "initramfs lacks ${missing} of the ${frames} frames ${theme} animates"
					else
						pass "initramfs carries all ${frames} ${theme} frames"
					fi
				else
					fail "initramfs lacks ScriptFile '${script}'"
				fi
			fi
		fi

		# Byte parity with the image's copy, both directions.
		if [[ -d "$image_theme" && -d "$initrd_theme" ]]; then
			drift="$(diff <(cd "$image_theme" && find . -type f -exec sha256sum {} + | sort -k2) \
				<(cd "$initrd_theme" && find . -type f -exec sha256sum {} + | sort -k2) || true)"
			if [[ -z "$drift" ]]; then
				pass "initramfs ${theme} assets match the image byte for byte"
			else
				fail "initramfs ${theme} assets differ from the image's (stale or foreign artwork):"$'\n'"${drift}"
			fi
		fi

		stray=""
		for t in "${tunaos_themes[@]}"; do
			[[ "$t" == "$theme" ]] && continue
			[[ -e "${unpacked}/${themes_rel}/${t}" ]] && stray+=" ${t}"
		done
		if [[ -n "$stray" ]]; then
			fail "initramfs carries other variants' themes:${stray}"
		else
			pass "no other TunaOS theme in the initramfs"
		fi
	fi
fi

if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_PLYMOUTH_FAIL variant=${variant} theme=${theme} failures=${fails}" >&2
	exit 1
fi
echo "TUNAOS_PLYMOUTH_OK variant=${variant} theme=${theme}"
