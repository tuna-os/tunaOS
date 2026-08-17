#!/usr/bin/env bash
# package-parity.sh — diff the installed package sets of two TunaOS editions.
#
#   scripts/package-parity.sh yellowfin:gnome albacore:gnome
#   scripts/package-parity.sh marlin:base marlin:kde
#   scripts/package-parity.sh --audit gnome        # every variant, one desktop
#
# Answers "is this edition missing packages, or is it just built differently?"
# — which image size cannot. A size audit of all 37 editions
# (tuna-os/tunaos-packages#133) flagged 24 as suspect and was wrong about the
# EL-family XFCE rows: those ship a lean XFCE *Wayland* stack (xfwl4 +
# greetd), legitimately much smaller than Fedora's X11 XFCE. The same audit
# was right about marlin:kde — 338 packages against its base's 480, and zero
# KDE packages. Only a package list separates those two cases.
#
# Reads the .packages OCI artifact published beside each image by
# reusable-build-image.yml. Falls back to querying the image directly when an
# edition predates that (or the publish step was skipped), which costs a pull.
set -euo pipefail

REGISTRY="${TUNA_REGISTRY:-ghcr.io/tuna-os}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/tuna-parity"
mkdir -p "$CACHE"

die() {
	echo "package-parity: $*" >&2
	exit 1
}

# NAME<TAB>VERSION, sorted. Artifact first; image query only if we must.
fetch() {
	local ref="$1" out="$CACHE/${ref//[:\/]/_}.txt"
	if [[ -s "$out" && -z "${TUNA_PARITY_REFRESH:-}" ]]; then
		echo "$out"
		return
	fi
	local repo="${ref%%:*}" tag="${ref##*:}"
	if command -v oras >/dev/null &&
		oras pull "${REGISTRY}/${repo}:${tag}-linux-amd64.packages" -o "$CACHE/pull" >/dev/null 2>&1; then
		mv "$CACHE"/pull/packages-*.txt "$out" 2>/dev/null || true
	fi
	if [[ ! -s "$out" ]]; then
		echo "  (no published manifest for $ref — querying the image)" >&2
		command -v podman >/dev/null || die "podman needed to query $ref"
		podman run --rm --entrypoint sh "${REGISTRY}/${repo}:${tag}" -c '
			if [ -s /usr/share/tunaos/packages.json ]; then
				if command -v jq >/dev/null 2>&1; then
					jq -r ".packages[] | \(.name)\t\(.version)" /usr/share/tunaos/packages.json
				elif command -v python3 >/dev/null 2>&1; then
					python3 -c "import json; [print(f\"{p[\"name\"]}\t{p.get(\"version\", \"\")}\") for p in json.load(open(\"/usr/share/tunaos/packages.json\")).get(\"packages\", [])]"
				fi
			elif command -v rpm        >/dev/null 2>&1; then rpm -qa --qf "%{NAME}\t%{VERSION}-%{RELEASE}\n"
			elif command -v dpkg-query >/dev/null 2>&1; then dpkg-query -W -f "${Package}\t${Version}\n"
			elif command -v pacman     >/dev/null 2>&1; then pacman -Q | tr " " "\t"
			elif command -v qlist      >/dev/null 2>&1; then qlist -ICv
			fi' 2>/dev/null | LC_ALL=C sort -u >"$out"
	fi
	[[ -s "$out" ]] || die "could not obtain a package list for $ref"
	echo "$out"
}

names() { cut -f1 "$1" | LC_ALL=C sort -u; }

# One desktop across every variant: the shape that exposes a build applying
# no desktop at all, which is what marlin's kde/cosmic/niri/xfce do.
if [[ "${1:-}" == "--audit" ]]; then
	de="${2:?usage: --audit <desktop>}"
	# The variant roster comes from build-config when available, so the audit
	# cannot silently omit a variant the factory declares (bonito-rawhide,
	# flounder-sid and gurnard were missing from the old hardcoded list —
	# exactly the absence-of-evidence hole this repo keeps refusing to dig).
	variants=(yellowfin bonito sailfin flounder grouper marlin skipjack albacore guppy)
	if command -v yq >/dev/null && [[ -f .github/build-config.yml ]]; then
		mapfile -t variants < <(yq -r '.variants[].id' .github/build-config.yml)
	fi
	# PARITY_JSON: append one JSON object per audited cell — the machine
	# output the scheduled workflow collates for the scoreboard (W6).
	emit_json() {
		[[ -n "${PARITY_JSON:-}" ]] || return 0
		jq -nc --arg cell "$1" --arg verdict "$2" --argjson delta "$3" \
			'{cell:$cell,verdict:$verdict,delta:$delta}' >>"$PARITY_JSON"
	}
	printf '%-12s %8s %8s %9s   %s\n' variant base "$de" delta verdict
	printf -- '-%.0s' {1..72}
	echo
	for v in "${variants[@]}"; do
		b=$(fetch "$v:base" 2>/dev/null) || {
			printf '%-12s   (no base)\n' "$v"
			emit_json "$v:$de" "unmeasured: no base manifest" 0
			continue
		}
		d=$(fetch "$v:$de" 2>/dev/null) || {
			emit_json "$v:$de" "unmeasured: no $de manifest" 0
			continue
		}
		nb=$(names "$b" | wc -l)
		nd=$(names "$d" | wc -l)
		delta=$((nd - nb))
		verdict="ok"
		((delta <= 0)) && verdict="BROKEN: no more packages than base"
		((delta > 0 && delta < 25)) && verdict="suspect: only $delta added"
		printf '%-12s %8d %8d %+9d   %s\n' "$v" "$nb" "$nd" "$delta" "$verdict"
		emit_json "$v:$de" "$verdict" "$delta"
	done
	exit 0
fi

A="${1:?usage: package-parity.sh <edition-a> <edition-b>}"
B="${2:?usage: package-parity.sh <edition-a> <edition-b>}"

fa=$(fetch "$A")
fb=$(fetch "$B")
na=$(names "$fa")
nb=$(names "$fb")

echo "=== $A: $(echo "$na" | wc -l) packages | $B: $(echo "$nb" | wc -l) packages"
echo
echo "--- only in $A ---"
comm -23 <(echo "$na") <(echo "$nb") | head -60
echo
echo "--- only in $B ---"
comm -13 <(echo "$na") <(echo "$nb") | head -60
echo
# Version skew matters for parity too, but is noise next to a missing set —
# summarise rather than dump.
common=$(comm -12 <(echo "$na") <(echo "$nb") | wc -l)
echo "--- $common packages in common ---"
