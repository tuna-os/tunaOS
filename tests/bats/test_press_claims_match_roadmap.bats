#!/usr/bin/env bats
# External-facing copy tracks the canonical variant table (tunaOS#1534).
#
# ROADMAP.md states the rule itself: its variant table "is the canonical
# per-variant status; tunaos.org wiki and blog copy must track it." Nothing
# enforced that, and the press materials drifted — DISTROWATCH-SUBMISSION.md
# listed Skipjack as Stable (canonical: Beta), Marlin as Alpha (Beta), Gurnard
# as a headline new variant (Experimental, #1341), omitted five variants, and
# listed COSMIC/Niri/XFCE as separate variants when they are desktop flavors
# available across variants.
#
# These documents are sent to DistroWatch and to magazine editors, so a wrong
# status is not an internal inconsistency — it is a public claim about what the
# project ships, made to people whose job is to check.
#
# This is a status check, not a prose check. Wording is left alone on purpose:
# pinning sentences would fail on every edit and teach people to delete the
# test.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
ROADMAP="${REPO_ROOT}/ROADMAP.md"
DISTROWATCH="${REPO_ROOT}/docs/DISTROWATCH-SUBMISSION.md"

# "| Name | Base | Desktops | Status |" rows from a markdown variant table.
variant_rows() {
  awk -F'|' '/^\| *[A-Z][A-Za-z]/ && NF==6 {
      name=$2; status=$5
      gsub(/^ +| +$/, "", name); gsub(/^ +| +$/, "", status)
      if (name == "Variant") next
      print name "\t" status
    }' "$1"
}

# ROADMAP names some rows for a pair — "Bonito / Bonito Rawhide", "Flounder /
# Flounder Sid". A listing reasonably says just "Bonito", so match either half
# rather than forcing press copy to use the compound name.
canon_status_for() {
  variant_rows "$ROADMAP" | awk -F'\t' -v want="$1" '
    {
      if ($1 == want) { print $2; exit }
      n = split($1, parts, / *\/ */)
      for (i = 1; i <= n; i++) if (parts[i] == want) { print $2; exit }
    }'
}

@test "the canonical table is parseable and non-trivial" {
  # Without this, a table-format change would make every check below pass by
  # comparing two empty sets.
  run bash -c "$(declare -f variant_rows); variant_rows '$ROADMAP' | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -ge 10 ]
}

@test "every variant the DistroWatch draft lists exists in ROADMAP's canonical table" {
  # Catches desktop flavors (COSMIC, Niri, XFCE) and other repos (Tromsø)
  # being presented to an editor as distributions.
  local missing=0 name status
  while IFS=$'\t' read -r name status; do
    [ -n "$name" ] || continue
    if [ -z "$(canon_status_for "$name")" ]; then
      echo "NOT A VARIANT: DistroWatch draft lists '$name', absent from ROADMAP's canonical table" >&2
      missing=$((missing + 1))
    fi
  done < <(variant_rows "$DISTROWATCH")
  [ "$missing" -eq 0 ]
}

@test "the DistroWatch draft reports each variant's canonical status" {
  local drift=0 name status canon
  while IFS=$'\t' read -r name status; do
    [ -n "$name" ] || continue
    canon="$(canon_status_for "$name")"
    [ -n "$canon" ] || continue  # absence is the previous test's job
    if [ "$status" != "$canon" ]; then
      echo "STATUS DRIFT: '$name' is '$status' in the DistroWatch draft, '$canon' in ROADMAP" >&2
      drift=$((drift + 1))
    fi
  done < <(variant_rows "$DISTROWATCH")
  [ "$drift" -eq 0 ]
}

@test "press copy does not promise aarch64 ISO downloads" {
  # The artifact matrix that builds ISOs is amd64-only (#1378), so an aarch64
  # ISO is a download that does not exist. Images ARE multi-arch, which is why
  # this is easy to state wrongly.
  run grep -nE '^\| \*\*Architectures\*\*.*\|' "$DISTROWATCH"
  [ "$status" -eq 0 ]
  # Either it scopes the arch claim to images, or it names the gap.
  [[ "$output" == *"Images:"* || "$output" == *"1378"* ]]
}
