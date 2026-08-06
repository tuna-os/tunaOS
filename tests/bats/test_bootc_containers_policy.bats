#!/usr/bin/env bats
# build_scripts/bootc/containers-policy.sh
#
# The fixture is the REAL file, pulled out of ghcr.io/projectbluefin/common's
# layer (tests/fixtures/ublue-common-policy.json). That matters: the first
# version of this script was written against an assumed policy shape — default
# permissive, transports carrying only signature requirements — and deleted
# the transports block. The real file is the other way round. Its default is
# `reject` and transports carries every permit, including the
# containers-storage one bootc install needs, so deleting it produced a policy
# that parsed and refused everything:
#
#   Source image rejected: Running image containers-storage:[...]
#   ghcr.io/tuna-os/gurnard:pantheon@... is rejected by policy.
#
# Hence: assert against the real content, and assert what the policy PERMITS,
# not just that it parses.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/bootc/containers-policy.sh"
REAL_POLICY="${REPO_ROOT}/tests/fixtures/ublue-common-policy.json"

setup() {
  FIXTURE="${BATS_TEST_TMPDIR}/root"
  mkdir -p "$FIXTURE/etc/containers" "${BATS_TEST_TMPDIR}/bin"

  # Stands in for Ubuntu noble's skopeo 1.13.3: understands the singular
  # `keyPath` (containers/image 5.24) but not the plural `keyPaths` (5.28).
  cat >"${BATS_TEST_TMPDIR}/bin/skopeo" <<'EOF'
#!/usr/bin/env bash
[[ "${1:-}" == "--version" ]] && { echo "skopeo version 1.13.3"; exit 0; }
pol="${TUNAOS_SYSROOT:-}/etc/containers/policy.json"
if grep -q '"keyPaths"' "$pol" 2>/dev/null; then
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

use_real_policy() { cp "$REAL_POLICY" "$FIXTURE/etc/containers/policy.json"; }
pol() { cat "$FIXTURE/etc/containers/policy.json"; }

@test "the fixture is the shape the repair has to cope with" {
  # If upstream ever flips these, every assertion below is testing fiction.
  [ "$(jq -r '.default[0].type' "$REAL_POLICY")" = "reject" ]
  [ "$(jq -r '.transports["containers-storage"][""][0].type' "$REAL_POLICY")" = "insecureAcceptAnything" ]
  [ "$(jq '[.. | objects | select(has("keyPaths"))] | length' "$REAL_POLICY")" -eq 1 ]
}

@test "containers-policy.sh: the real policy ends up loadable" {
  use_real_policy
  run_policy
  [ "$status" -eq 0 ]
  ! grep -q '"keyPaths"' <<<"$(pol)"
}

@test "containers-policy.sh: containers-storage stays permitted" {
  # THE regression. bootc install copies containers-storage: -> oci:, and that
  # permit lives in the transports block, not in the default.
  use_real_policy
  run_policy
  [ "$status" -eq 0 ]
  [ "$(jq -r '.transports["containers-storage"][""][0].type' <<<"$(pol)")" = "insecureAcceptAnything" ]
  [ "$(jq -r '.transports["oci"][""][0].type' <<<"$(pol)")" = "insecureAcceptAnything" ]
}

@test "containers-policy.sh: the reject default is never loosened" {
  use_real_policy
  run_policy
  [ "$status" -eq 0 ]
  [ "$(jq -r '.default[0].type' <<<"$(pol)")" = "reject" ]
}

@test "containers-policy.sh: sigstore verification survives as keyPath" {
  # Step 1 keeps the requirement and loses only the backup key. Dropping the
  # requirement outright would silently stop verifying ublue-os images.
  use_real_policy
  run_policy
  [ "$status" -eq 0 ]
  local req
  req="$(jq -c '.transports.docker["ghcr.io/ublue-os"][0]' <<<"$(pol)")"
  [ "$(jq -r '.type' <<<"$req")" = "sigstoreSigned" ]
  [ "$(jq -r '.keyPath' <<<"$req")" = "/usr/lib/pki/containers/ublue-os.pub" ]
}

@test "containers-policy.sh: requirements it never had trouble with are left alone" {
  use_real_policy
  run_policy
  [ "$status" -eq 0 ]
  [ "$(jq -r '.transports.docker["registry.redhat.io"][0].type' <<<"$(pol)")" = "signedBy" ]
  [ "$(jq -r '.transports.docker["quay.io/toolbx-images"][0].keyPath' <<<"$(pol)")" \
      = "/usr/lib/pki/containers/quay.io-toolbx-images.pub" ]
}

@test "containers-policy.sh: writes a default when no policy exists" {
  run_policy
  [ "$status" -eq 0 ]
  grep -q 'insecureAcceptAnything' "$FIXTURE/etc/containers/policy.json"
}

@test "containers-policy.sh: leaves a policy this skopeo accepts alone" {
  printf '{"default":[{"type":"reject"}]}\n' >"$FIXTURE/etc/containers/policy.json"
  run_policy
  [ "$status" -eq 0 ]
  [ "$(jq -r '.default[0].type' <<<"$(pol)")" = "reject" ]
}

@test "containers-policy.sh: fails rather than falling back to accept-everything" {
  # A stub that rejects every policy. The script must not "repair" a
  # reject-by-default file into an accept-everything one to get green.
  cat >"${BATS_TEST_TMPDIR}/bin/skopeo" <<'EOF'
#!/usr/bin/env bash
[[ "${1:-}" == "--version" ]] && { echo "skopeo version 0"; exit 0; }
echo 'level=fatal msg="Error loading trust policy: invalid policy"' >&2
exit 1
EOF
  chmod +x "${BATS_TEST_TMPDIR}/bin/skopeo"
  use_real_policy
  run_policy
  [ "$status" -ne 0 ]
  [ "$(jq -r '.default[0].type' <<<"$(pol)")" = "reject" ]
}

@test "containers-policy.sh: says what it changed" {
  use_real_policy
  run_policy
  [[ "$output" == *"cannot be parsed"* ]]
  [[ "$output" == *"keyPath"* ]]
}

@test "containers-policy.sh: passes shellcheck" {
  if ! command -v shellcheck &>/dev/null; then skip "shellcheck not installed"; fi
  run shellcheck --severity=error --exclude=SC1091 "$SCRIPT"
  [ "$status" -eq 0 ]
}

@test "every Containerfile that COPYs the common tree validates its policy" {
  local f
  for f in Containerfile.ubuntu Containerfile.debian Containerfile.opensuse; do
    grep -q 'bootc/containers-policy.sh' "${REPO_ROOT}/$f"
  done
  for f in Containerfile.ubuntu Containerfile.debian Containerfile.opensuse; do
    run grep -c '^[[:space:]]*printf.*insecureAcceptAnything' "${REPO_ROOT}/$f"
    [ "$output" -eq 0 ]
  done
}
