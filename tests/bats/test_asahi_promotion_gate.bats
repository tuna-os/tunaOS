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
  grep -q 'needs: [manifest, sign, verify_boot, verify_asahi]' "$WORKFLOW"
  grep -q 'needs.verify_asahi.result == '\''success'\''' "$WORKFLOW"
  grep -q 'needs.verify_asahi.result == '\''skipped'\''' "$WORKFLOW"
}
