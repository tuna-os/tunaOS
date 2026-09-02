#!/usr/bin/env bats
# .github/scripts/pr-nudges.sh: advisory reminders that never fail a PR.
#
# The important case is the last one: on a fork PR the comment POST 403s,
# and the script must still exit 0 with the reminder delivered to the job
# summary. Hive's changelog reminder went red on every external contribution
# before it had this test (kubestellar/hive#4440); this one exists so ours
# never does.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/.github/scripts/pr-nudges.sh"

setup() {
  TMP="$(mktemp -d)"
  export GITHUB_STEP_SUMMARY="${TMP}/summary.md"
  : > "${GITHUB_STEP_SUMMARY}"
  export REPO=tuna-os/tunaOS PR=1 GH_TOKEN=x
}

teardown() {
  rm -rf "${TMP}"
}

# A stub `gh` whose behaviour is chosen per test via GH_MODE.
stub_gh() {
  mkdir -p "${TMP}/bin"
  cat > "${TMP}/bin/gh" <<'EOF'
#!/usr/bin/env bash
echo "gh $*" >> "${GH_LOG}"
case "${GH_MODE}" in
  403)
    echo "gh: Resource not accessible by integration (HTTP 403)" >&2
    exit 1 ;;
  already)
    # the dedupe read finds an existing reminder; a POST would be a bug
    if [[ "$*" == *"--jq"* ]]; then echo "<!-- pr-nudges -->"; exit 0; fi
    echo "unexpected POST" >&2; exit 1 ;;
  ok)
    exit 0 ;;
esac
EOF
  chmod +x "${TMP}/bin/gh"
  export PATH="${TMP}/bin:${PATH}" GH_LOG="${TMP}/gh.log"
}

@test "script passes shellcheck" {
  run shellcheck --exclude=SC1091 "${SCRIPT}"
  [ "$status" -eq 0 ]
}

@test "a docs-only change produces no nudge" {
  run bash "${SCRIPT}" <<< "docs/USER-GUIDE.md"
  [ "$status" -eq 0 ]
  [[ "$output" == *"no nudges"* ]]
}

@test "a desktop manifest change asks about the tag docs and the contract" {
  run bash "${SCRIPT}" <<< "manifests/desktops/kde.yaml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Desktop change"* ]]
  [[ "$output" == *"IMAGE-TAGS.md"* ]]
  [[ "$output" == *"reminders, not gates"* ]]
}

@test "a build-config change asks for a green-criteria scope review" {
  run bash "${SCRIPT}" <<< ".github/build-config.yml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Matrix change"* ]]
  [[ "$output" == *"green-criteria.yml"* ]]
}

@test "a workflow change points at the gates block the contract test checks" {
  run bash "${SCRIPT}" <<< ".github/workflows/reusable-build-image.yml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Workflow change"* ]]
  [[ "$output" == *"test_ci_contract.py"* ]]
}

@test "code without docs gets the docs nudge; code with docs does not" {
  run bash "${SCRIPT}" <<< "scripts/build-image-inner.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"**Docs.**"* ]]
  run bash "${SCRIPT}" < <(printf 'scripts/build-image-inner.sh\ndocs/PIPELINE.md\n')
  [ "$status" -eq 0 ]
  [[ "$output" != *"**Docs.**"* ]]
}

@test "deliver on a same-repo PR posts exactly one comment" {
  stub_gh; export GH_MODE=ok IS_FORK=false
  run bash "${SCRIPT}" --deliver <<< "manifests/desktops/kde.yaml"
  [ "$status" -eq 0 ]
  grep -q "Desktop change" "${GITHUB_STEP_SUMMARY}"
  [[ "$output" == *"::notice title=PR reminders::"* ]]
  grep -q "issues/1/comments -F body=@" "${GH_LOG}"
}

@test "deliver does not repeat a reminder that is already on the PR" {
  stub_gh; export GH_MODE=already IS_FORK=false
  run bash "${SCRIPT}" --deliver <<< "manifests/desktops/kde.yaml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"already reminded"* ]]
  ! grep -q -- "-F body=@" "${GH_LOG}"
}

@test "deliver on a fork PR never calls the API for a comment and still exits 0" {
  stub_gh; export GH_MODE=403 IS_FORK=true
  run bash "${SCRIPT}" --deliver <<< "manifests/desktops/kde.yaml"
  [ "$status" -eq 0 ]
  grep -q "Desktop change" "${GITHUB_STEP_SUMMARY}"
  [[ "$output" == *"fork PR"* ]]
  [ ! -s "${GH_LOG}" ]
}

@test "a 403 on the comment POST is tolerated: exit 0, summary still written" {
  # IS_FORK unknown (empty) and every gh call 403s — the shape hive#4440 hit.
  stub_gh; export GH_MODE=403 IS_FORK=
  run bash "${SCRIPT}" --deliver <<< ".github/build-config.yml"
  [ "$status" -eq 0 ]
  grep -q "Matrix change" "${GITHUB_STEP_SUMMARY}"
  [[ "$output" == *"could not post the reminders as a PR comment"* ]]
}
