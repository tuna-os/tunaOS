#!/usr/bin/env bats

# Arm64 Asahi images cannot use the x86 QEMU promotion gate. They therefore
# need their own mandatory verification before the testing tag is copied to a
# user-facing tag; otherwise an incomplete EL10 boot stack can be promoted
# merely because its build completed.

WORKFLOW="${BATS_TEST_DIRNAME}/../../.github/workflows/reusable-build-image.yml"

@test "Asahi promotion calls the golden manifest gate" {
  grep -q '^  verify_asahi:' "$WORKFLOW"
  grep -q 'endsWith(inputs.flavor, '\''-asahi'\'')' "$WORKFLOW"
  grep -q 'uses: ./\.github/workflows/verify-asahi-one.yml' "$WORKFLOW"
  grep -q 'image: .*default-tag.*-testing' "$WORKFLOW"
}

@test "promotion waits for the Asahi gate" {
  # The brackets used to be unescaped, so grep read them as a character class
  # and `needs: manifest` on another job satisfied this line -- the assertion
  # passed without ever looking at Promote. Read Promote's own `needs:` and
  # check for the gate this file owns; the full gate list grows over time
  # (verify_desktop, #2263) and is enforced by scripts/check-ci-contract.py.
  local promote_needs
  promote_needs="$(awk '/^  tag-image:/{f=1} f && /^    needs:/{print; exit}' "$WORKFLOW")"
  [ -n "$promote_needs" ]
  [[ "$promote_needs" == *"verify_asahi"* ]]
  grep -q 'needs.verify_asahi.result == '\''success'\''' "$WORKFLOW"
  grep -q 'needs.verify_asahi.result == '\''skipped'\''' "$WORKFLOW"
}
