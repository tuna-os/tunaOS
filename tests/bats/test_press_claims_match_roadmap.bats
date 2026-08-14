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

# Every external-facing doc that publishes a variant table, not just the
# DistroWatch one. Four more were in flight when this was written — PRESSKIT.md
# (#1653), TECH-PRESS-PITCHES.md (#1544), YOUTUBER-REVIEW-KIT.md (#1545) — and
# a guard that only covers the document that happened to be checked first is
# how the next one ships wrong. Files are matched if present; a doc that does
# not exist yet simply is not scanned, and starts being scanned the day it
# lands.
press_docs() {
  local f
  for f in "${REPO_ROOT}"/docs/DISTROWATCH-SUBMISSION.md \
           "${REPO_ROOT}"/docs/PRESSKIT.md \
           "${REPO_ROOT}"/docs/TECH-PRESS-PITCHES.md \
           "${REPO_ROOT}"/docs/YOUTUBER-REVIEW-KIT.md \
           "${REPO_ROOT}"/docs/FEDORA-MAGAZINE-PITCH.md; do
    [ -f "$f" ] && grep -qE '^\| *[A-Z][A-Za-z]+ *\|' "$f" && echo "$f"
  done
}

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
  # Compound names appear on BOTH sides and are not written identically:
  # ROADMAP says "Flounder / Flounder Sid", a press kit reasonably writes
  # "Flounder / Sid". Split both and match on any shared part, so the guard
  # flags variants that do not exist rather than variants spelled shorter. (It
  # flagged Flounder before this — a false positive is how a guard gets
  # deleted, so it matters more than the true positives.)
  variant_rows "$ROADMAP" | awk -F'\t' -v want="$1" '
    {
      if ($1 == want) { print $2; exit }
      nc = split($1, cparts, / *\/ */)
      nw = split(want, wparts, / *\/ */)
      for (i = 1; i <= nc; i++)
        for (j = 1; j <= nw; j++)
          if (cparts[i] == wparts[j]) { print $2; exit }
    }'
}

@test "there is at least one press doc with a variant table to check" {
  # Without this, renaming a press doc turns every check below into a pass that
  # inspected nothing.
  run bash -c "$(declare -f press_docs); REPO_ROOT='$REPO_ROOT'; press_docs | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "the canonical table is parseable and non-trivial" {
  # Without this, a table-format change would make every check below pass by
  # comparing two empty sets.
  run bash -c "$(declare -f variant_rows); variant_rows '$ROADMAP' | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -ge 10 ]
}

@test "every variant any press doc lists exists in ROADMAP's canonical table" {
  # Catches three things an editor would check and we would not: desktop
  # flavors (COSMIC, Niri, XFCE) presented as distributions, other repos
  # (Tromsø, XFCE Linux) presented as variants, and — the expensive one —
  # variants that are goals rather than builds. PRESSKIT.md's draft listed
  # "Redfin | RHEL 10" in a table headed "Variant matrix (as of 2026-08-14)";
  # `redfin` appears zero times in build-config.yml, and ROADMAP tracks it as a
  # Q3 goal with "zero movement since 08-08". RHEL support is exactly what an
  # enterprise outlet asks about first.
  local missing=0 name status doc
  while read -r doc; do
    while IFS=$'\t' read -r name status; do
      [ -n "$name" ] || continue
      if [ -z "$(canon_status_for "$name")" ]; then
        echo "NOT A VARIANT: $(basename "$doc") lists '$name', absent from ROADMAP's canonical table" >&2
        missing=$((missing + 1))
      fi
    done < <(variant_rows "$doc")
  done < <(press_docs)
  [ "$missing" -eq 0 ]
}

@test "press docs report each variant's canonical status" {
  # Only applies to tables whose 4th column IS a status. A press kit whose
  # columns are Base/Desktop/Arch has no status to drift, and canon_status_for
  # returning empty for a non-status string keeps this from firing on it.
  local drift=0 name status canon doc
  while read -r doc; do
    while IFS=$'\t' read -r name status; do
      [ -n "$name" ] || continue
      canon="$(canon_status_for "$name")"
      [ -n "$canon" ] || continue
      case "$status" in
        Stable|Beta|Alpha|Experimental*|New*|GA) ;;
        *) continue ;;   # not a status column
      esac
      if [ "$status" != "$canon" ]; then
        echo "STATUS DRIFT: '$name' is '$status' in $(basename "$doc"), '$canon' in ROADMAP" >&2
        drift=$((drift + 1))
      fi
    done < <(variant_rows "$doc")
  done < <(press_docs)
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
