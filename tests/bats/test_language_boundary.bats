#!/usr/bin/env bats
# The one mechanical part of ADR 0008 (tunaOS#1651).
#
# The ADR is mostly judgement — "is this parsing or orchestration?" is a review
# question, and a test that tried to answer it would be wrong more often than a
# reviewer. What IS mechanical: don't shell out to `python3 -c` to pull a field
# out of a YAML file when `yq` is already a hard dependency.
#
# That is not style. `just/custom-overlay.just` did it four times, and the regex
# was wrong in two ways at once:
#
#   $ printf '# set tag: WRONG-VALUE here\ntag: correct-tag\n' > t.yaml
#   re.search(r'tag:\s*(\S+)')  → WRONG-VALUE      (matched inside a comment)
#   yq -r '.tag'                → correct-tag
#
# and `.group(1)` on a None raised AttributeError into `2>/dev/null || echo
# <default>`, so a missing field silently produced the default image tag. A
# wrong image built without complaint is worse than a failed build.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "there are just modules to check (guards a vacuous pass)" {
  run bash -c "ls '${REPO_ROOT}'/just/*.just | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -ge 3 ]
}

@test "no just module parses YAML with an inline python regex" {
  local bad=0 f
  for f in "${REPO_ROOT}"/just/*.just "${REPO_ROOT}/Justfile"; do
    [ -f "$f" ] || continue
    # `python3 -c` whose body mentions both `re` and a YAML file.
    if grep -nE "python3 -c.*(import re|re\.search)" "$f" | grep -qiE "yaml|yml"; then
      grep -nE "python3 -c.*(import re|re\.search)" "$f" | grep -iE "yaml|yml" >&2
      echo "  ^ $(basename "$f"): use yq (already required by _ensure-deps) — ADR 0008" >&2
      bad=$((bad + 1))
    fi
  done
  [ "$bad" -eq 0 ]
}

@test "custom-overlay reads image.yaml with yq" {
  # The positive form: asserting the right tool is present catches a rewrite
  # into some third approach, which a blacklist would not.
  run grep -c "yq }} -r '\.\(base\|tag\)" "${REPO_ROOT}/just/custom-overlay.just"
  [ "$status" -eq 0 ]
  [ "$output" -ge 4 ]
}

@test "yq is a hard dependency, so relying on it is safe" {
  # If _ensure-deps stopped checking for yq, the recipes above would fail at a
  # worse moment than dependency-check time.
  run grep -A6 '^_ensure-deps:' "${REPO_ROOT}/Justfile"
  [ "$status" -eq 0 ]
  [[ "$output" == *"yq"* ]]
}

@test "the ADR exists and is numbered in sequence" {
  local adr="${REPO_ROOT}/docs/adr/0008-shell-python-boundary.md"
  [ -f "$adr" ]
  # No duplicate 0008 — ADR numbers are referenced from issues and PRs.
  run bash -c "ls '${REPO_ROOT}'/docs/adr/0008-*.md | wc -l"
  [ "$output" -eq 1 ]
}

@test "the ADR records what it declined, not just what it decided" {
  # #1651 recommended merging the test harnesses. That would mean running shell
  # tests through pytest or Python tests through bats. The reasoning has to
  # survive in the ADR, or the next architect re-proposes it.
  local adr="${REPO_ROOT}/docs/adr/0008-shell-python-boundary.md"
  run grep -Fi 'Deliberately not done' "$adr"
  [ "$status" -eq 0 ]
  run grep -Fi 'single harness' "$adr"
  [ "$status" -eq 0 ]
}
