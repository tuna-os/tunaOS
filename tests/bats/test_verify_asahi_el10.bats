#!/usr/bin/env bats
# test_verify_asahi_el10.bats — tests for verify-asahi-image.sh EL10 detection and soft check behavior.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
VERIFY_SH="${REPO_ROOT}/scripts/verify-asahi-image.sh"

@test "verify-asahi-image.sh contains EL10 family detection" {
  run grep -F 'is_el10=true' "$VERIFY_SH"
  [ "$status" -eq 0 ]
}

@test "verify-asahi-image.sh accepts soft parameter for check_file and check_any" {
  run grep -F 'check_file /usr/bin/tiny-dfr "$is_el10"' "$VERIFY_SH"
  [ "$status" -eq 0 ]
  run grep -F 'check_any "update-m1n1 kernel hook" "$is_el10"' "$VERIFY_SH"
  [ "$status" -eq 0 ]
}

@test "verify-asahi-image.sh treats apple-isp.ko missing as warn under EL10" {
  run grep -F 'note "$mod not in modules.dep (known EL10 packaging gap)"' "$VERIFY_SH"
  [ "$status" -eq 0 ]
}
