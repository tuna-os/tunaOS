#!/usr/bin/env bash
# verify-manifest-packages.sh — do a desktop manifest's apt package names exist?
#
# manifests/desktops/pantheon.yaml states the rule this automates, and the
# reason for it:
#
#   "Every package name below was verified published for noble via the
#    Launchpad API ... rather than guessed. Names in this ecosystem are not
#    guessable ... Do not add an unverified name here. An unresolvable name is
#    what shipped a desktop-less image in tunaos-packages#132."
#
# That verification was done once, by hand, and nothing re-does it. A name that
# was published when the manifest was written can be dropped from a PPA later,
# and a name added afterwards gets whatever care its author felt like — which
# is how tunaos-packages#132 happened. The failure mode is not a build error:
# apt is invoked with the whole list, so one bad name takes the transaction
# down, or (worse, with --skip-*) the desktop quietly ships incomplete.
#
# Checks each name against the manifest's declared PPA AND the Ubuntu primary
# archive for the target series/arch. A name is fine if EITHER publishes it —
# the manifests deliberately mix the two (Pantheon from elementary's PPA,
# lightdm/gvfs/portals from the archive) and do not mark which is which.
#
# Usage:
#   scripts/verify-manifest-packages.sh manifests/desktops/pantheon.yaml [series] [arch]
#
# Defaults: series noble, arch amd64. Run once per arch the variant declares —
# a PPA can publish for amd64 and not arm64, and gurnard builds both.
#
# Exit: 0 all names resolve · 1 one or more do not · 2 could not run.

set -uo pipefail

MANIFEST="${1:?usage: verify-manifest-packages.sh <manifest.yaml> [series] [arch]}"
SERIES="${2:-noble}"
ARCH="${3:-amd64}"

[[ -r "$MANIFEST" ]] || { echo "ERROR: cannot read ${MANIFEST}" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found" >&2; exit 2; }

DAS="https://api.launchpad.net/1.0/ubuntu/${SERIES}/${ARCH}"

# The manifest's apt package list. Comments are stripped; the list ends at the
# next top-level key.
mapfile -t PKGS < <(
	awk '/^    packages:$/{f=1;next}
	     f && /^    - /{n=$2; sub(/#.*/,"",n); gsub(/[ \t]/,"",n); if (n != "") print n}
	     f && /^[a-z_]+:$/{exit}' "$MANIFEST"
)
[[ "${#PKGS[@]}" -gt 0 ]] || { echo "ERROR: no apt packages parsed from ${MANIFEST}" >&2; exit 2; }

# The PPA it declares, as a Launchpad archive URL. Absent is fine — then every
# name must come from the primary archive.
PPA_URL=""
ppa_spec="$(awk '/repo: *"ppa:/{ if (match($0, /ppa:[^"]+/)) print substr($0, RSTART+4, RLENGTH-4); exit }' "$MANIFEST")"
if [[ -n "$ppa_spec" ]]; then
	owner="${ppa_spec%%/*}"
	name="${ppa_spec#*/}"
	[[ "$name" == "$ppa_spec" ]] && name="ppa"
	PPA_URL="https://api.launchpad.net/1.0/~${owner}/+archive/ubuntu/${name}"
fi

published_in() { # archive_url package -> prints count, "ERR" on a bad response
	curl -sS --max-time 30 -G "$1" \
		--data-urlencode "ws.op=getPublishedBinaries" \
		--data-urlencode "binary_name=$2" \
		--data-urlencode "distro_arch_series=${DAS}" \
		--data "exact_match=true&status=Published" 2>/dev/null |
		python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("total_size", 0))
except Exception: print("ERR")'
}

echo "==> ${MANIFEST}: ${#PKGS[@]} packages against ${SERIES}/${ARCH}"
[[ -n "$PPA_URL" ]] && echo "    PPA: ${ppa_spec}"

missing=0 errored=0
for p in "${PKGS[@]}"; do
	src=""
	if [[ -n "$PPA_URL" ]]; then
		n="$(published_in "$PPA_URL" "$p")"
		[[ "$n" == "ERR" ]] && { errored=$((errored + 1)); echo "  ?? ${p} (PPA query failed)" >&2; continue; }
		[[ "$n" -gt 0 ]] && src="ppa"
	fi
	if [[ -z "$src" ]]; then
		n="$(published_in "https://api.launchpad.net/1.0/ubuntu/+archive/primary" "$p")"
		[[ "$n" == "ERR" ]] && { errored=$((errored + 1)); echo "  ?? ${p} (archive query failed)" >&2; continue; }
		[[ "$n" -gt 0 ]] && src="archive"
	fi
	if [[ -n "$src" ]]; then
		printf '  ok %-32s %s\n' "$p" "$src"
	else
		printf '  MISSING %-28s not published in the PPA or the %s archive for %s/%s\n' \
			"$p" "ubuntu" "$SERIES" "$ARCH" >&2
		missing=$((missing + 1))
	fi
done

if [[ "$errored" -gt 0 ]]; then
	echo "==> ${errored} query/queries failed — result is inconclusive, not a pass." >&2
	exit 2
fi
if [[ "$missing" -gt 0 ]]; then
	echo "==> ${missing} package name(s) resolve nowhere. Fix the manifest before this" >&2
	echo "    reaches a build: apt takes the whole list at once (tunaos-packages#132)." >&2
	exit 1
fi
echo "==> all ${#PKGS[@]} names resolve for ${SERIES}/${ARCH}"
