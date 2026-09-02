#!/usr/bin/env bats
# Callers and reusable workflows agree about inputs (tunaOS#1378).
#
# A `with:` key the callee does not declare is dropped silently — GitHub does
# not error, the reusable workflow just runs with its default. So a caller can
# thread a value through a matrix, pass it, and have it evaporate, with every
# job green and the feature simply absent.
#
# That is the shape #1378 is about. `build-variant.yml` selects artifact rows on
# `build_iso == true or build_qcow2 == true` and carries `build_qcow2` in every
# row, but `reusable-build-artifacts.yml` declares only `build-iso` — so no
# QCOW2 artifact has ever been built, on any architecture, and nothing failed to
# say so. The arm64 half of that issue is a second instance: expanding the
# matrix means passing `platform`/`safeplatform`, and if the callee does not
# declare them the arm64 rows quietly build amd64 again.
#
# Checks every `uses: ./.github/workflows/*.yml` call site in the repo, not just
# the artifact ones — the failure mode is a property of reusable workflows, not
# of this feature.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WF="${REPO_ROOT}/.github/workflows"

setup() {
  command -v yq >/dev/null 2>&1 || skip "yq unavailable"
}

# caller <TAB> job <TAB> uses <TAB> comma-joined `with:` keys
call_sites() {
  local f
  for f in "$WF"/*.yml; do
    yq -r '.jobs // {} | to_entries[]
           | select((.value.uses // "") | test("^\./\.github/workflows/"))
           | [.key, (.value.uses), ((.value.with // {}) | keys | join(","))] | @tsv' "$f" 2>/dev/null \
      | sed "s|^|$f\t|"
  done
}

declared_inputs() {
  yq -r '.on.workflow_call.inputs // {} | keys | join(",")' "$1"
}

@test "the repo actually has reusable-workflow call sites to check" {
  # Guards against a yq/selector change silently reducing every test below to
  # a no-op that passes because it inspected nothing.
  run bash -c "$(declare -f call_sites); WF='$WF'; call_sites | awk -F'\t' 'NF>=3 && \$3 != \"\"' | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -gt 10 ]
}

@test "every input a caller passes is declared by the workflow it calls" {
  local violations=0 caller job uses passed target declared p
  while IFS=$'\t' read -r caller job uses passed; do
    [ -n "${uses:-}" ] || continue
    target="${WF}/$(basename "$uses")"
    if [ ! -f "$target" ]; then
      echo "MISSING TARGET: $caller job=$job -> $uses" >&2
      violations=$((violations + 1)); continue
    fi
    declared="$(declared_inputs "$target")"
    IFS=',' read -ra keys <<< "${passed:-}"
    for p in "${keys[@]}"; do
      [ -n "$p" ] || continue
      case ",$declared," in
        *",$p,"*) ;;
        *) echo "UNDECLARED: $caller job=$job passes '$p', $(basename "$target") does not declare it" >&2
           violations=$((violations + 1)) ;;
      esac
    done
  done < <(call_sites)
  [ "$violations" -eq 0 ]
}

@test "every required input of a called workflow is supplied" {
  # The opposite failure: this one DOES fail at runtime, but only when the job
  # runs, which for artifact jobs is after a full image build.
  local violations=0 caller job uses passed target r
  while IFS=$'\t' read -r caller job uses passed; do
    [ -n "${uses:-}" ] || continue
    target="${WF}/$(basename "$uses")"
    [ -f "$target" ] || continue
    for r in $(yq -r '.on.workflow_call.inputs // {} | to_entries[]
                      | select(.value.required == true) | .key' "$target"); do
      case ",${passed:-}," in
        *",$r,"*) ;;
        *) echo "MISSING REQUIRED: $caller job=$job omits '$r' required by $(basename "$target")" >&2
           violations=$((violations + 1)) ;;
      esac
    done
  done < <(call_sites)
  [ "$violations" -eq 0 ]
}

@test "build-variant.yml's artifact rows only carry fields the artifact workflow can use" {
  # Narrower, and the one that names #1378's dead thread directly. Every field
  # the artifact matrix emits should either be consumed by build-variant.yml
  # itself (to build the `with:` block or the job name) or be declared by
  # reusable-build-artifacts.yml. `build_qcow2` is currently neither used to
  # gate anything nor accepted by the callee, which is why "QCOW2s are never
  # built" reads as an arm64 bug when it is not one.
  #
  # Asserted as a KNOWN state rather than a clean contract: flipping this test
  # is what implementing QCOW2 artifacts looks like.
  local artifacts="${WF}/reusable-build-artifacts.yml"
  run bash -c "yq -r '.on.workflow_call.inputs // {} | keys[]' '$artifacts'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"build-iso"* ]]
  # If this starts failing, a qcow2 input was added — delete this assertion and
  # the comment above it, because the gap it documents is closed.
  [[ "$output" != *"qcow2"* ]]
}
