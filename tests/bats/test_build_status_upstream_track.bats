#!/usr/bin/env bats
# The README matrix must report the release track as its own number
# (tunaOS#1753).
#
# VARIANT-LIFECYCLE.md makes the rolling/release distinction operational: on
# the release/stream track "a red scheduled build is treated as a regression
# rather than expected upstream churn", while rolling and experimental
# variants carry "no next-night promotion or uninterrupted-green promise".
# `.github/build-config.yml`'s `upstream_track` is named there as the
# machine-readable source, and tests/test_variant_upstream_tracks.py pins its
# contents -- but nothing consumed it, so the one artifact people actually
# read published a single mixed ratio ("Built 50/140") in which a rolling
# upstream's expected churn and a release-track regression are the same
# number. #1753's target had to be reconstructed by hand from a nightly's
# job logs for exactly that reason.
#
# These tests pin the split, and they pin it as a *derivation* rather than a
# list: nothing here hardcodes which variants are on which track, because the
# defect being prevented is the two drifting apart.
#
# Harness is tests/bats/test_update_build_status.bats': the real script runs
# with `gh`/`yq` stubbed on PATH, and no GitHub API call is made.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/.github/scripts/update-build-status.sh"

# Two variants, one per side of the split, four flavors each. One flavor is
# promoted, so each variant scores 1/4 and the two subtotals are only
# distinguishable if the script is actually reading the track.
write_yq() {
  cat > "${BIN}/yq" <<STUB
#!/usr/bin/env bash
echo "yq \$*" >> "\${YQ_LOG:-/dev/null}"
for arg in "\$@"; do
  case "\$arg" in
    *excludes_flavor*) exit 0 ;;
    *enforcement*)     printf 'boots\nbuilds\n'; exit 0 ;;
    *flavors*)         printf 'green\nbroken\nskipped\nabsent\n'; exit 0 ;;
    *upstream_track*)  printf '${1}'; exit 0 ;;
  esac
done
exit 0
STUB
  chmod +x "${BIN}/yq"
}

setup() {
  BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$BIN"

  write_yq 'gurnard\t🐟\trelease\nmarlin\t🚀\trolling\n'

  # GH_NO_RUNS names variants whose workflow has no completed run at all, so
  # the "variant never ran" path can be exercised for one variant without
  # blanking the other.
  cat > "${BIN}/gh" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  run)
    for v in ${GH_NO_RUNS:-}; do
      case "$*" in *"build-${v}.yml"*) printf '[]'; exit 0 ;; esac
    done
    printf '%s' "${GH_RUNS}"
    ;;
  api) printf '%s' "${GH_JOBS}" ;;
esac
STUB
  chmod +x "${BIN}/gh"
  export PATH="${BIN}:${PATH}"
  export YQ_LOG="${BATS_TEST_TMPDIR}/yq.log"

  CONFIG="${BATS_TEST_TMPDIR}/config.yml"
  README="${BATS_TEST_TMPDIR}/README.md"
  echo 'variants: []' > "$CONFIG"
  printf '<!-- build-status:start -->\nstale\n<!-- build-status:end -->\n' > "$README"

  export GH_RUNS='[{"databaseId":1,"conclusion":"success","createdAt":"2026-09-14T03:00:00Z","url":"https://example/1"}]'
  export GH_JOBS=$'x / green / Promote\tsuccess\nx / broken / Promote\tfailure\nx / skipped / Promote\tskipped\n'
}

run_generator() {
  run bash "$SCRIPT" "$CONFIG" "$README"
  [ "$status" -eq 0 ]
}

# ── the track reaches the table ──────────────────────────────────────────────

@test "track: the generator asks build-config.yml for upstream_track" {
  # The bash-side default (track=${track:-release}) is deliberate, so a broken
  # yq query would otherwise show up as "everything is release" -- a plausible
  # looking table with a meaningless subtotal. Pin the read itself.
  run_generator
  grep -q 'upstream_track' "$YQ_LOG"
}

@test "track: each variant's row names its track" {
  run_generator
  local release rolling
  release=$(grep '`gurnard`' "$README")
  rolling=$(grep '`marlin`' "$README")
  [[ "$release" == *"| release |"* ]]
  [[ "$rolling" == *"| rolling |"* ]]
}

@test "track: a variant with no upstream_track is rendered as release, never blank" {
  # Absence IS the release/stream default per VARIANT-LIFECYCLE.md; an empty
  # cell would read as "unknown" and invite someone to fill it in by hand.
  write_yq 'gurnard\t🐟\n'
  run_generator
  local row
  row=$(grep '`gurnard`' "$README")
  [[ "$row" == *"| release |"* ]]
  [[ "$row" != *"|  |"* ]]
}

@test "track: the added column does not disturb the failing/not-reached columns" {
  # Those two are the columns tunaOS#1730 is about; a column inserted in the
  # middle is exactly the kind of edit that silently shifts them.
  run_generator
  local row
  row=$(grep '`gurnard`' "$README")
  [[ "$row" == *"| broken | skipped,absent |"* ]]
}

# ── the subtotal ─────────────────────────────────────────────────────────────

@test "subtotal: only release-track cells are counted in the release subtotal" {
  run_generator
  # Both variants score 1/4; only one of them is on the release track.
  grep -q 'Built 2/8' "$README"
  grep -q '\*\*Release track: 1/4 built (25%)\.\*\*' "$README"
}

@test "subtotal: non-release cells are reported as the remainder, not dropped" {
  run_generator
  grep -q 'The other 4 cells track' "$README"
}

@test "subtotal: a rolling variant going green does not move the release number" {
  export GH_JOBS=$'x / green / Promote\tsuccess\nx / broken / Promote\tsuccess\nx / skipped / Promote\tsuccess\nx / absent / Promote\tsuccess\n'
  write_yq 'marlin\t🚀\trolling\n'
  run_generator
  grep -q 'Built 4/4' "$README"
  # No release-track cells at all: the subtotal must say 0/0 rather than
  # divide by zero or inherit the overall percentage.
  grep -q '\*\*Release track: 0/0 built (0%)\.\*\*' "$README"
}

@test "subtotal: a release variant with no completed run keeps its cells in the denominator" {
  # The variant loop `continue`s on this path. If the denominator were
  # accumulated after that point, a workflow going quiet would shrink the
  # target instead of showing up as a gap -- flattering the ratio for the one
  # reason a reader should worry about most.
  export GH_NO_RUNS='gurnard'
  run_generator
  grep -q 'no completed run' "$README"
  grep -q '\*\*Release track: 0/4 built (0%)\.\*\*' "$README"
}

@test "subtotal: the release variant count is reported and is not the variant total" {
  run_generator
  grep -q -- '— 1 variant —' "$README"
  ! grep -q -- '— 2 variants —' "$README"
}

@test "subtotal: the split names both tracking issues so the number has an owner" {
  run_generator
  grep -q 'issues/1753' "$README"
  grep -q 'issues/1754' "$README"
}
