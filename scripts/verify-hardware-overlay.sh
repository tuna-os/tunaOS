#!/usr/bin/env bash
# verify-hardware-overlay.sh <image ref> <profile id> — check a published
# hardware overlay against its [hardware.<id>] profile, without the hardware.
#
# hardware-profile.sh inventories the image while it builds; this reads the
# bytes that were pushed (after chunkah rechunked them) and checks what a
# build-time inventory cannot: that the image is its labelled parent plus the
# profile's packages and nothing else.
#
#   labels      org.tunaos.hardware-overlay.base-digest names a parent index
#               that exists, and base-image names the parent tag
#   inventory   /usr/share/tunaos/hardware-<id>.txt exists, no MISSING line
#   kargs       /usr/lib/bootc/kargs.d/10-<id>.toml carries exactly the
#               profile's kargs, matched to its architectures
#   devicetree  /usr/lib/modules/<kver>/devicetree is the kernel's own copy of
#               the profile DTB, and the kernel-install hook that places it for
#               later kernels is installed
#   initramfs   every profile driver that is a module of this kernel, and every
#               profile dracut module, is in the initramfs; no omitted driver is
#   packages    `rpm -qa` of the image minus that of the parent is exactly the
#               profile's dnf packages, and nothing was removed
#
# Prints one PASS/FAIL line per check and exits 1 on any FAIL.
#
# Environment: PODMAN, SKOPEO (optional) name the binaries; PLATFORM
# (default linux/arm64) the platform to pull; TUNAOS_HARDWARE_PROFILES the
# profile file.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

image="${1:?usage: verify-hardware-overlay.sh <image ref> <profile id>}"
id="${2:?usage: verify-hardware-overlay.sh <image ref> <profile id>}"
PODMAN="${PODMAN:-podman}"
SKOPEO="${SKOPEO:-skopeo}"
PLATFORM="${PLATFORM:-linux/arm64}"
profiles="${TUNAOS_HARDWARE_PROFILES:-build_scripts/lib/hardware-profiles.json}"
profile="$(jq -ce --arg id "$id" '.profiles[$id]' "$profiles")" || {
	echo "ERROR: no hardware profile '$id' in $profiles" >&2
	exit 2
}

failed=0
pass() { printf 'PASS %s: %s\n' "$1" "$2"; }
fail() {
	printf 'FAIL %s: %s\n' "$1" "$2"
	failed=1
}
in_image() { "$PODMAN" run --rm --platform "$PLATFORM" --entrypoint /bin/bash "$1" -c "$2"; }

"$PODMAN" pull -q --platform "$PLATFORM" "$image" >/dev/null

# ── labels ───────────────────────────────────────────────────────────────────
base_digest="$("$PODMAN" image inspect --format '{{index .Labels "org.tunaos.hardware-overlay.base-digest"}}' "$image")"
base_image="$("$PODMAN" image inspect --format '{{index .Labels "org.tunaos.hardware-overlay.base-image"}}' "$image")"
# base-image names the parent tag (ghcr.io/tuna-os/bonito:gnome). A reference
# with both a tag and a digest is not valid for skopeo, so pin the repository.
parent_repo="$base_image"
[[ "${parent_repo##*/}" == *:* ]] && parent_repo="${parent_repo%:*}"
parent=""
if [[ ! "$base_digest" =~ ^sha256:[0-9a-f]{64}$ || -z "$base_image" || "$base_image" == "<no value>" ]]; then
	fail labels "base-digest '${base_digest}' / base-image '${base_image}'"
elif ! "$SKOPEO" inspect --raw --retry-times 3 "docker://${parent_repo}@${base_digest}" >/dev/null; then
	fail labels "parent ${parent_repo}@${base_digest} does not resolve"
else
	parent="${parent_repo}@${base_digest}"
	pass labels "parent ${parent} (${base_image})"
fi

# ── everything inside the image, in one container ────────────────────────────
mapfile -t kargs < <(jq -r '.kargs[]?' <<<"$profile")
mapfile -t arches < <(jq -r '.architectures[]?' <<<"$profile")
dtb="$(jq -r '.devicetree.dtb // ""' <<<"$profile")"
drivers="$(jq -r '((.initramfs.add_drivers // []) + (.initramfs.kms_drivers // [])) | unique | join(" ")' <<<"$profile")"
omitted="$(jq -r '(.initramfs.omit_drivers // []) | join(" ")' <<<"$profile")"
dracut_modules="$(jq -r '(.initramfs.dracut_modules // []) | join(" ")' <<<"$profile")"
want_kargs="kargs = [$(printf '"%s", ' "${kargs[@]}" | sed 's/, $//')]"
want_arches="match-architectures = [$(printf '"%s", ' "${arches[@]}" | sed 's/, $//')]"

inner="$(
	cat <<'EOF'
set -uo pipefail
kver="$(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V | tail -n1)"
mod="/usr/lib/modules/${kver}"
echo "INFO kernel ${kver}"

report="/usr/share/tunaos/hardware-${ID}.txt"
if [[ ! -s "$report" ]]; then echo "FAIL inventory: ${report} missing"
elif grep -q '^MISSING ' "$report"; then echo "FAIL inventory: $(grep '^MISSING ' "$report" | paste -sd';' -)"
else echo "PASS inventory: ${report}, $(grep -c '^PRESENT\|^MODULE\|^BUILTIN\|^CONFIG_' "$report") present lines"; fi

kfile="/usr/lib/bootc/kargs.d/10-${ID}.toml"
if [[ -z "$WANT_KARGS_LIST" ]]; then echo "PASS kargs: profile has none"
elif [[ "$(grep '^kargs' "$kfile" 2>/dev/null)" == "$WANT_KARGS" && "$(grep '^match-architectures' "$kfile" 2>/dev/null)" == "$WANT_ARCHES" ]]; then
	echo "PASS kargs: ${kfile}: ${WANT_KARGS}"
else echo "FAIL kargs: ${kfile}: $(tr '\n' ' ' <"$kfile" 2>&1)"; fi

if [[ -n "$DTB" ]]; then
	if cmp -s "${mod}/dtb/${DTB}" "${mod}/devicetree"; then echo "PASS devicetree: ${mod}/devicetree is ${DTB}"
	else echo "FAIL devicetree: ${mod}/devicetree is not ${mod}/dtb/${DTB}"; fi
	hook=/usr/lib/kernel/install.d/04-tunaos-devicetree.install
	if [[ -x "$hook" && -x /usr/libexec/tunaos/hardware-devicetree ]]; then echo "PASS devicetree-hook: ${hook}"
	else echo "FAIL devicetree-hook: ${hook} or /usr/libexec/tunaos/hardware-devicetree missing"; fi
fi

listing="$(lsinitrd "${mod}/initramfs.img" 2>/dev/null)"
if [[ -z "$listing" ]]; then echo "FAIL initramfs: lsinitrd read nothing from ${mod}/initramfs.img"; else
	missing=() present=0
	for d in $DRIVERS; do
		modinfo -k "$kver" -F filename "$d" 2>/dev/null | grep -q '\.ko' || continue
		if grep -qE "/${d//[-_]/[-_]}\.ko" <<<"$listing"; then present=$((present + 1)); else missing+=("$d"); fi
	done
	modules="$(sed -n '/^dracut modules:/,/^=\{10,\}/p' <<<"$listing")"
	for m in $DRACUT_MODULES; do grep -qx "$m" <<<"$modules" || missing+=("dracut:$m"); done
	leaked=()
	for d in $OMITTED; do grep -qE "/${d//[-_]/[-_]}\.ko" <<<"$listing" && leaked+=("$d"); done
	if ((${#missing[@]} + ${#leaked[@]})); then echo "FAIL initramfs: missing ${missing[*]:-none}; omitted but present ${leaked[*]:-none}"
	else echo "PASS initramfs: ${present} profile modules and dracut modules ${DRACUT_MODULES:-none}; ${OMITTED:-no} drivers omitted, $(stat -c %s "${mod}/initramfs.img") bytes"; fi
fi
EOF
)"
results="$("$PODMAN" run --rm --platform "$PLATFORM" --entrypoint /bin/bash \
	-e ID="$id" -e DTB="$dtb" -e DRIVERS="$drivers" -e OMITTED="$omitted" \
	-e DRACUT_MODULES="$dracut_modules" -e WANT_KARGS="$want_kargs" -e WANT_ARCHES="$want_arches" \
	-e WANT_KARGS_LIST="${kargs[*]}" "$image" -c "$inner")"
printf '%s\n' "$results"
grep -q '^FAIL ' <<<"$results" && failed=1

# ── packages: the image is the parent plus the profile ───────────────────────
if [[ -n "$parent" ]]; then
	"$PODMAN" pull -q --platform "$PLATFORM" "$parent" >/dev/null
	query="rpm -qa --qf '%{NAME}\n' | sort -u"
	added="$(comm -13 <(in_image "$parent" "$query") <(in_image "$image" "$query") | paste -sd' ' -)"
	removed="$(comm -23 <(in_image "$parent" "$query") <(in_image "$image" "$query") | paste -sd' ' -)"
	want="$(jq -r '(.packages.dnf // []) | sort | join(" ")' <<<"$profile")"
	if [[ "$added" == "$want" && -z "$removed" ]]; then
		pass packages "parent + ${want:-nothing}"
	else
		fail packages "added '${added}' (profile: '${want}'), removed '${removed}'"
	fi
fi

exit "$failed"
