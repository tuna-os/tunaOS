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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/build-config.sh
source "${SCRIPT_DIR}/lib/build-config.sh"
BUILD_CONFIG="$(tunaos_build_config)"

REGISTRY="${TUNA_REGISTRY:-ghcr.io/tuna-os}"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/tuna-parity"
mkdir -p "$CACHE"

die() {
	echo "package-parity: $*" >&2
	exit 1
}

# NAME<TAB>VERSION, sorted. Artifact first; image query only if we must.
fetch() {
	# Two statements on purpose: in `local a="$1" b="...${a}..."` bash expands
	# every word BEFORE the builtin assigns, so under `set -u` the second
	# assignment reads an unbound variable and kills the script.
	local ref="$1" img
	local out="$CACHE/${ref//[:\/]/_}.txt"
	if [[ -s "$out" && -z "${TUNA_PARITY_REFRESH:-}" ]]; then
		echo "$out"
		return
	fi
	if [[ "$ref" == */* ]]; then
		# A full image reference (an upstream anchor like
		# ghcr.io/ublue-os/bluefin:lts). No .packages artifact convention to
		# try — query the image itself.
		img="$ref"
	else
		local repo="${ref%%:*}" tag="${ref##*:}"
		img="${REGISTRY}/${repo}:${tag}"
		if command -v oras >/dev/null &&
			oras pull "${REGISTRY}/${repo}:${tag}-linux-amd64.packages" -o "$CACHE/pull" >/dev/null 2>&1; then
			mv "$CACHE"/pull/packages-*.txt "$out" 2>/dev/null || true
		fi
	fi
	if [[ ! -s "$out" ]]; then
		echo "  (no published manifest for $ref — querying the image)" >&2
		command -v podman >/dev/null || die "podman needed to query $ref"
		podman run --rm --entrypoint sh "$img" -c '
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
	# The variant roster comes from .github/build-config.yml (resolved through
	# lib/build-config.sh, so TUNAOS_BUILD_CONFIG can relocate it) when
	# available, so the audit cannot silently omit a variant the factory
	# declares (bonito-rawhide, flounder-sid and gurnard were missing from the
	# old hardcoded list — exactly the absence-of-evidence hole this repo keeps
	# refusing to dig). The literal list below is only the no-yq fallback.
	variants=(yellowfin bonito sailfin flounder grouper marlin skipjack albacore guppy)
	if command -v yq >/dev/null && [[ -f "$BUILD_CONFIG" ]]; then
		mapfile -t variants < <(yq -r '.variants[].id' "$BUILD_CONFIG")
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

# Second W6 cadence: diff each mapped cell against its UPSTREAM reference
# (Bluefin/Aurora). The map lives in green-criteria.yml under the parity
# criterion — a reviewed declaration, like the boots scope, because only some
# variants have an upstream built from the same package universe. This mode
# MEASURES; it does not judge: the criterion stays advisory until the noise
# floor these numbers establish turns into per-variant thresholds.
if [[ "${1:-}" == "--upstream-audit" ]]; then
	criteria="${CRITERIA:-.github/green-criteria.yml}"
	command -v yq >/dev/null || die "--upstream-audit needs yq"
	[[ -f "$criteria" ]] || die "no criteria file at $criteria"
	mapfile -t pairs < <(yq -r '.criteria[] | select(.id == "parity")
		| .upstream_references // {} | to_entries[] | .key as $de
		| .value | to_entries[] | [$de, .key, .value] | @tsv' "$criteria")
	((${#pairs[@]} > 0)) || die "no upstream_references declared under the parity criterion"
	emit_upstream_json() {
		[[ -n "${PARITY_JSON:-}" ]] || return 0
		jq -nc --arg cell "$1" --arg upstream "$2" --arg verdict "$3" \
			--argjson missing "$4" --argjson extra "$5" \
			'{kind:"upstream",cell:$cell,upstream:$upstream,verdict:$verdict,missing:$missing,extra:$extra}' >>"$PARITY_JSON"
	}
	# Prefetch each unique upstream once and free the image immediately: three
	# variants share bluefin:lts, and a hosted runner cannot hold every
	# multi-GB reference image on disk at once. The package list stays cached.
	mapfile -t uprefs < <(printf '%s\n' "${pairs[@]}" | cut -f3 | LC_ALL=C sort -u)
	for upref in "${uprefs[@]}"; do
		# Subshell: die() inside fetch exits, and a missing upstream must
		# downgrade that cell to unmeasured, not kill the whole sweep.
		(fetch "$upref" >/dev/null) || echo "  (could not fetch upstream $upref)" >&2
		podman rmi -f "$upref" >/dev/null 2>&1 || true
	done
	printf '%-18s %-34s %6s %8s %8s %7s   %s\n' cell upstream ours theirs missing extra verdict
	printf -- '-%.0s' {1..100}
	echo
	for pair in "${pairs[@]}"; do
		IFS=$'\t' read -r de variant upref <<<"$pair"
		cell="$variant:$de"
		ours=$(fetch "$cell" 2>/dev/null) || {
			printf '%-18s %-34s   (no cell manifest)\n' "$cell" "$upref"
			emit_upstream_json "$cell" "$upref" "unmeasured: no cell manifest" 0 0
			continue
		}
		theirs=$(fetch "$upref" 2>/dev/null) || {
			printf '%-18s %-34s   (upstream unfetchable)\n' "$cell" "$upref"
			emit_upstream_json "$cell" "$upref" "unmeasured: upstream unfetchable" 0 0
			continue
		}
		n_ours=$(names "$ours" | wc -l)
		n_theirs=$(names "$theirs" | wc -l)
		missing=$(comm -13 <(names "$ours") <(names "$theirs") | wc -l)
		extra=$(comm -23 <(names "$ours") <(names "$theirs") | wc -l)
		printf '%-18s %-34s %6d %8d %8d %7d   %s\n' \
			"$cell" "$upref" "$n_ours" "$n_theirs" "$missing" "$extra" "measured"
		emit_upstream_json "$cell" "$upref" "measured" "$missing" "$extra"
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
