#!/usr/bin/env bats
# build_scripts/bootc/containers-policy.sh
#
# Two failure modes, one file:
#   openSUSE  — no /etc/containers/policy.json at all; bootc install fails with
#               "no policy.json file found".
#   gurnard   — a policy.json that exists but this image's skopeo rejects
#               ("Unknown key \"keyPaths\""), which fails EVERY skopeo call,
#               including the one bootc install uses.
#
# Both are exercised here with a stub skopeo, because the real one only
# disagrees with the policy on specific base images.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/bootc/containers-policy.sh"

POLICY_WITH_KEYPATHS='{"default":[{"type":"insecureAcceptAnything"}],
 "transports":{"docker":{"ghcr.io/ublue-os":[{"type":"sigstoreSigned","keyPaths":["/usr/etc/pki/a.pub"]}]}}}'

setup() {
  FIXTURE="${BATS_TEST_TMPDIR}/root"
  mkdir -p "$FIXTURE/etc/containers" "${BATS_TEST_TMPDIR}/bin"

  # Stands in for Ubuntu noble's skopeo 1.13.3: rejects any policy naming
  # keyPaths, and otherwise fails on the probe's nonexistent paths like the
  # real one does.
  cat >"${BATS_TEST_TMPDIR}/bin/skopeo" <<'EOF'
#!/usr/bin/env bash
[[ "${1:-}" == "--version" ]] && { echo "skopeo version 1.13.3"; exit 0; }
pol="${TUNAOS_SYSROOT:-}/etc/containers/policy.json"
if grep -q 'keyPaths' "$pol" 2>/dev/null; then
  echo 'level=fatal msg="Error loading trust policy: invalid policy: Unknown key \"keyPaths\""' >&2
  exit 1
fi
echo "FATA[0000] initializing source: no such file or directory" >&2
exit 1
EOF
  chmod +x "${BATS_TEST_TMPDIR}/bin/skopeo"
}

run_policy() {
  PATH="${BATS_TEST_TMPDIR}/bin:${PATH}" TUNAOS_SYSROOT="$FIXTURE" run bash "$SCRIPT"
}

@test "containers-policy.sh: writes a default when no policy exists" {
  run_policy
  [ "$status" -eq 0 ]
  [ -s "$FIXTURE/etc/containers/policy.json" ]
  grep -q 'insecureAcceptAnything' "$FIXTURE/etc/containers/policy.json"
}

@test "containers-policy.sh: leaves a policy this skopeo accepts alone" {
  printf '{"default":[{"type":"reject"}]}\n' >"$FIXTURE/etc/containers/policy.json"
  run_policy
  [ "$status" -eq 0 ]
  # Untouched — including a stricter default than we would have written.
  grep -q 'reject' "$FIXTURE/etc/containers/policy.json"
}

@test "containers-policy.sh: drops the transports block skopeo cannot parse" {
  echo "$POLICY_WITH_KEYPATHS" >"$FIXTURE/etc/containers/policy.json"
  run_policy
  [ "$status" -eq 0 ]
  ! grep -q 'keyPaths' "$FIXTURE/etc/containers/policy.json"
  # `default` must survive: it is the requirement that was actually working.
  grep -q 'insecureAcceptAnything' "$FIXTURE/etc/containers/policy.json"
}

@test "containers-policy.sh: says what it removed" {
  # A trust policy quietly losing its transports is exactly the kind of change
  # that must be visible in the build log.
  echo "$POLICY_WITH_KEYPATHS" >"$FIXTURE/etc/containers/policy.json"
  run_policy
  [[ "$output" == *"cannot be parsed"* ]]
  [[ "$output" == *"docker"* ]]
}

@test "containers-policy.sh: is a no-op when the image has no skopeo" {
  rm -f "${BATS_TEST_TMPDIR}/bin/skopeo"
  printf '{"default":[{"type":"reject"}]}\n' >"$FIXTURE/etc/containers/policy.json"
  PATH="${BATS_TEST_TMPDIR}/bin:/usr/bin:/bin" TUNAOS_SYSROOT="$FIXTURE" \
    TUNAOS_SKOPEO=skopeo-does-not-exist run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q 'reject' "$FIXTURE/etc/containers/policy.json"
}

@test "containers-policy.sh: fails the build if the policy still will not load" {
  # A stub that rejects everything: the script must not report success on a
  # policy no skopeo call can use.
  cat >"${BATS_TEST_TMPDIR}/bin/skopeo" <<'EOF'
#!/usr/bin/env bash
[[ "${1:-}" == "--version" ]] && { echo "skopeo version 0"; exit 0; }
echo 'level=fatal msg="Error loading trust policy: invalid policy"' >&2
exit 1
EOF
  chmod +x "${BATS_TEST_TMPDIR}/bin/skopeo"
  echo "$POLICY_WITH_KEYPATHS" >"$FIXTURE/etc/containers/policy.json"
  run_policy
  [ "$status" -ne 0 ]
}

@test "containers-policy.sh: passes shellcheck" {
  if ! command -v shellcheck &>/dev/null; then skip "shellcheck not installed"; fi
  run shellcheck --severity=error --exclude=SC1091 "$SCRIPT"
  [ "$status" -eq 0 ]
}

@test "every Containerfile that COPYs the common tree validates its policy" {
  # projectbluefin/common's shared tree is where the keyPaths policy comes
  # from. openSUSE is here for the other half — it ships no policy at all.
  local f
  for f in Containerfile.ubuntu Containerfile.debian Containerfile.opensuse; do
    grep -q 'bootc/containers-policy.sh' "${REPO_ROOT}/$f"
  done
  # And no Containerfile may still hand-write the default inline.
  for f in Containerfile.ubuntu Containerfile.debian Containerfile.opensuse; do
    run grep -c '^[[:space:]]*printf.*insecureAcceptAnything' "${REPO_ROOT}/$f"
    [ "$output" -eq 0 ]
  done
}
