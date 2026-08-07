#!/usr/bin/env bats
# The `FROM scratch AS context` stage, which every Containerfile defines and
# no Containerfile can share.
#
# A Dockerfile has no include, so this stage is copy-pasted six times. That is
# the exact shape of every bug on this branch — a fix or an entry landing in
# one of N near-identical places — and here it has already happened twice in
# the same file: Containerfile.ubuntu was missing `manifests` (gurnard died
# with "No manifest found", #1014) and then `system_files_overrides`.
#
# Duplication that cannot be factored out has to be asserted instead. These
# tests are the substitute for the include that does not exist.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# Every Containerfile that builds a bootable variant. Containerfile.overlay
# has its own context stage for the hwe/nvidia layers and is checked with them;
# .final and .custom define no context stage.
CONTAINERFILES=(
  Containerfile.el10
  Containerfile.arch
  Containerfile.debian
  Containerfile.ubuntu
  Containerfile.opensuse
  Containerfile.gentoo
)

# The stage body, from `FROM scratch AS context` to the next FROM. Case is not
# consistent in the tree (el10 writes `as`), so match it insensitively rather
# than silently skipping that file and reporting a pass.
context_stage() {
  # tolower(), not IGNORECASE: that is a gawk extension and this tree's awk is
  # mawk, where it is silently ignored. With IGNORECASE the pattern matched
  # el10's lowercase `as` and missed everyone else's `AS` — a test that reads
  # as passing on five files it never looked at.
  awk 'tolower($0) ~ /^from[ \t]+scratch[ \t]+as[ \t]+context/ {inside=1; next}
       inside && tolower($0) ~ /^from[ \t]/ {exit}
       inside {print}' "$1"
}

# grep -v exits 1 on empty input, which under bats' set -e aborts the test with
# no message. Strip comments without that trap.
strip_comments() { grep -v '^[[:space:]]*#' || true; }

@test "every variant Containerfile defines a context stage" {
  local f body
  for f in "${CONTAINERFILES[@]}"; do
    body="$(context_stage "${REPO_ROOT}/$f")"
    [ -n "$body" ] || {
      echo "FAIL: no 'FROM scratch AS context' stage in $f" >&2
      return 1
    }
  done
}

@test "every context stage carries the four the build scripts always read" {
  # system_files      -> COPY --from=context /files /
  # system_files_overrides -> copy_systemfiles_for() / run_buildscripts_for()
  # build_scripts     -> every RUN that bind-mounts the context
  # manifests         -> install-desktop.sh, on every manifest-driven desktop
  local f body missing fail=0
  for f in "${CONTAINERFILES[@]}"; do
    body="$(context_stage "${REPO_ROOT}/$f" | strip_comments)"
    missing=""
    grep -q 'COPY[[:space:]]\+system_files[[:space:]]' <<<"$body" || missing+=" system_files"
    grep -q 'COPY[[:space:]]\+system_files_overrides[[:space:]]' <<<"$body" || missing+=" system_files_overrides"
    grep -q 'COPY[[:space:]]\+build_scripts[[:space:]]' <<<"$body" || missing+=" build_scripts"
    grep -q 'COPY[[:space:]]\+manifests[[:space:]]' <<<"$body" || missing+=" manifests"
    if [ -n "$missing" ]; then
      echo "FAIL: ${f} context stage is missing:${missing}" >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}

@test "the four land on the paths the build scripts look for" {
  # A COPY with the right source and the wrong destination is worse than a
  # missing one: the file is there and every consumer still fails.
  local f body fail=0
  for f in "${CONTAINERFILES[@]}"; do
    body="$(context_stage "${REPO_ROOT}/$f" | strip_comments)"
    grep -qE 'COPY[[:space:]]+system_files[[:space:]]+/files$' <<<"$body" || {
      echo "FAIL: ${f} does not COPY system_files to /files" >&2; fail=1; }
    grep -qE 'COPY[[:space:]]+system_files_overrides[[:space:]]+/overrides$' <<<"$body" || {
      echo "FAIL: ${f} does not COPY system_files_overrides to /overrides" >&2; fail=1; }
    grep -qE 'COPY[[:space:]]+build_scripts[[:space:]]+/build_scripts$' <<<"$body" || {
      echo "FAIL: ${f} does not COPY build_scripts to /build_scripts" >&2; fail=1; }
    grep -qE 'COPY[[:space:]]+manifests[[:space:]]+/manifests$' <<<"$body" || {
      echo "FAIL: ${f} does not COPY manifests to /manifests" >&2; fail=1; }
  done
  [ "$fail" -eq 0 ]
}

@test "image-versions.yaml is carried exactly where a build script reads it" {
  # This one is deliberately NOT uniform. 10-base-packages.sh reads
  # /run/context/image-versions.yaml unguarded, and runs on el10, debian and
  # ubuntu only. kcm-ublue.sh reads it too but returns early without dnf, so
  # the pacman/zypper/emerge files never reach it. Asserted as an exact set so
  # that adding the read to another script, or the file to another context,
  # has to be a deliberate change to this list.
  local f body has needs
  for f in "${CONTAINERFILES[@]}"; do
    body="$(context_stage "${REPO_ROOT}/$f" | strip_comments)"
    has=0
    grep -q 'COPY[[:space:]]\+image-versions.yaml' <<<"$body" && has=1
    # Strip comments, same as `has` above: Containerfile.gentoo's podman
    # comment NAMES 10-base-packages.sh in prose ("the rpm and apt ones from
    # build_scripts/10-base-packages.sh") and the unstripped grep read that
    # as the script being run, failing every PR after #1038 merged.
    needs=0
    strip_comments <"${REPO_ROOT}/$f" | grep -q '10-base-packages.sh' && needs=1
    if [ "$has" -ne "$needs" ]; then
      echo "FAIL: ${f} carries image-versions.yaml=${has} but runs 10-base-packages.sh=${needs}" >&2
      return 1
    fi
  done
}

@test "10-base-packages.sh really does read it unguarded" {
  # The premise of the test above. If someone guards the read, the asymmetry
  # stops being justified and this should be revisited rather than silently
  # keeping a rule whose reason has gone.
  grep -q 'image-versions.yaml' "${REPO_ROOT}/build_scripts/10-base-packages.sh"
  # And kcm-ublue.sh must still bail before its read on an RPM-less distro.
  local head
  head="$(sed -n '1,25p' "${REPO_ROOT}/build_scripts/desktop/kcm-ublue.sh")"
  grep -q 'command -v dnf' <<<"$head"
}
