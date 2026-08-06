#!/usr/bin/env bats
# Every script a Containerfile invokes from the bind-mounted context must exist
# in the tree, and be executable.
#
# This is a whole-file-missing check, not a lint. It exists because that failure
# is silent until a real image build, and expensive in exactly the cases where
# builds are slowest:
#
#   /bin/sh: line 1: /run/context/build_scripts/bootc/ostree-layout.sh: No such
#   file or directory
#   Error: building at STEP "RUN ...": while running runtime: exit status 127
#
# guppy:xfce, LUKS run 31077043961 — 65 minutes into a Gentoo build, after the
# whole desktop had emerged and the branding contract had passed. The call was
# added to Containerfile.gentoo on one branch while the script it names lived
# only on another, so nothing in the tree was wrong on either side alone.
#
# 127 (not found) and 126 (not executable) are the two shapes, hence both
# assertions. A stale reference to a DELETED script lands here too, which is
# the more likely direction as the per-DE scripts are retired onto
# install-desktop.sh.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# Containerfiles with comment lines blanked. The stage comments discuss these
# scripts by path, and a comment naming a script that has legitimately been
# deleted is not a broken build.
containerfile_code() {
  sed 's/^[[:space:]]*#.*//' "${REPO_ROOT}"/Containerfile.*
}

# Every /run/context/... script path a Containerfile names, repo-relative.
context_script_refs() {
  containerfile_code |
    grep -ohE '/run/context/[A-Za-z0-9_./-]+\.sh' |
    sed 's|^/run/context/||' | sort -u
}

# The subset that is EXECUTED rather than sourced. Containerfile.debian and
# .ubuntu both do
#     bash -c "source /run/context/build_scripts/lib.sh && source .../10-base-packages.sh"
# and a sourced file needs no mode bit, so requiring one of lib.sh would fail
# falsely. A path counts as executed if any occurrence lacks a `source`/`.`
# immediately in front of it.
executed_script_refs() {
  containerfile_code |
    grep -ohE '(source[[:space:]]+|\.[[:space:]]+)?/run/context/[A-Za-z0-9_./-]+\.sh' |
    grep -v '^source[[:space:]]' | grep -v '^\.[[:space:]]' |
    sed 's|^/run/context/||' | sort -u
}

@test "every script a Containerfile runs from /run/context exists in the tree" {
  local rel fail=0
  while read -r rel; do
    [ -n "$rel" ] || continue
    if [ ! -f "${REPO_ROOT}/${rel}" ]; then
      echo "FAIL: a Containerfile names /run/context/${rel}, but ${rel} is not" >&2
      echo "      in the tree. The build dies with 'No such file or directory'" >&2
      echo "      and exit 127, and only once that RUN step is reached." >&2
      fail=1
    fi
  done < <(context_script_refs)
  [ "$fail" -eq 0 ]
}

@test "every script a Containerfile executes is executable" {
  local rel fail=0
  while read -r rel; do
    [ -n "$rel" ] || continue
    [ -f "${REPO_ROOT}/${rel}" ] || continue # covered by the test above
    if [ ! -x "${REPO_ROOT}/${rel}" ]; then
      echo "FAIL: a Containerfile executes ${rel}, but it is not executable." >&2
      echo "      chmod +x it, or the build gets exit 126 at that step —" >&2
      echo "      which reads nothing like the 127 of a missing file." >&2
      fail=1
    fi
  done < <(executed_script_refs)
  [ "$fail" -eq 0 ]
}

@test "the checks actually look at something, and tell sourced from executed" {
  # A regex that silently matched nothing would make both tests above pass
  # forever.
  run bash -c "$(declare -f containerfile_code context_script_refs); REPO_ROOT='${REPO_ROOT}'; context_script_refs | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -ge 15 ]

  # lib.sh is only ever sourced, so it must be in the first set and not the
  # second. If this stops holding, the source-detection has broken and the
  # executable test is either vacuous or lying.
  run bash -c "$(declare -f containerfile_code context_script_refs); REPO_ROOT='${REPO_ROOT}'; context_script_refs"
  [[ "$output" == *"build_scripts/lib.sh"* ]]
  run bash -c "$(declare -f containerfile_code executed_script_refs); REPO_ROOT='${REPO_ROOT}'; executed_script_refs"
  [[ "$output" != *"build_scripts/lib.sh"* ]]
}
