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

# Per-DE desktop scripts a single Containerfile invokes, comments blanked.
# Not install-desktop.sh (manifest-driven, handles every package manager) and
# not configure-desktop-runtime.sh (post-install wiring, no package install).
per_de_scripts() {
  sed 's/^[[:space:]]*#.*//' "$1" |
    grep -ohE '/run/context/build_scripts/desktop/[A-Za-z0-9_-]+\.sh' |
    sed 's|.*/||' |
    grep -vE '^(install-desktop|configure-desktop-runtime)\.sh$' |
    sort -u
}

# An apt-based Containerfile must not invoke a per-DE script that has no apt
# branch. desktop/cosmic.sh goes straight to `dnf -y copr enable`, so
# Containerfile.ubuntu's cosmic stage died at
#
#   /run/context/build_scripts/desktop/cosmic.sh: line 41: dnf: command not found
#   Error: building at STEP "RUN ...": while running runtime: exit status 127
#
# on every grouper:cosmic build (LUKS run 31134394662). It now uses
# install-desktop.sh, which is what every other Containerfile already did for
# cosmic and the only path that handles the `condition: ubuntu` PPA the Ubuntu
# package list needs.
#
# test_declared_flavors_installable.bats could not catch this: cosmic.yaml's
# apt section is present and non-empty, so the flavour looks installable — the
# gap was the Containerfile reaching for a script that never consults it. This
# is the structural half of that invariant, on the other side.
@test "apt Containerfiles only invoke per-DE scripts that have an apt branch" {
  local cf script base fail=0
  for cf in "${REPO_ROOT}/Containerfile.ubuntu" "${REPO_ROOT}/Containerfile.debian"; do
    while read -r script; do
      [ -n "$script" ] || continue
      base="${REPO_ROOT}/build_scripts/desktop/${script}"
      [ -f "$base" ] || continue # covered by the missing-file test above
      if ! grep -qE 'PKG_MGR.*[!=]=[[:space:]]*"apt"' "$base"; then
        echo "FAIL: $(basename "$cf") runs desktop/${script}, which has no apt" >&2
        echo "      branch. On an apt base it falls through to its dnf/pacman" >&2
        echo "      path and the build dies with 'dnf: command not found'." >&2
        echo "      Use install-desktop.sh (manifest-driven) instead, or give" >&2
        echo "      the script a \$PKG_MGR == apt branch." >&2
        fail=1
      fi
    done < <(per_de_scripts "$cf")
  done
  [ "$fail" -eq 0 ]
}

# The test above passes trivially if the extraction finds nothing, and would
# have passed on the broken tree if cosmic.sh had been mis-filtered out.
#
# The controls cannot name gnome.sh, kde.sh or cosmic.sh any more: all three
# moved onto install-desktop.sh and were deleted, which is the direction the
# rule above pushes. niri.sh and xfce.sh are the per-DE scripts still invoked,
# so they are what proves the extraction sees something, and the dnf-only
# rejection is proved against a script written here rather than whichever
# in-tree script happens to still lack an apt branch — a check keyed on a file
# that no longer exists passes for the wrong reason (grep exits 2).
@test "the apt per-DE check sees real scripts, and would reject a dnf-only one" {
  run bash -c "$(declare -f per_de_scripts); per_de_scripts '${REPO_ROOT}/Containerfile.ubuntu'"
  [ "$status" -eq 0 ]
  [[ "$output" == *"niri.sh"* ]]
  [[ "$output" == *"xfce.sh"* ]]

  # Both of those must satisfy the rule, or the test above is red for real.
  local s
  for s in niri xfce; do
    run grep -qE 'PKG_MGR.*[!=]=[[:space:]]*"apt"' "${REPO_ROOT}/build_scripts/desktop/${s}.sh"
    [ "$status" -eq 0 ]
  done

  # And the predicate must still reject a script shaped like cosmic.sh was.
  local dnf_only="${BATS_TEST_TMPDIR}/dnf-only.sh"
  printf '#!/usr/bin/env bash\ndnf -y copr enable yselkowitz/cosmic-epel\n' >"$dnf_only"
  run grep -qE 'PKG_MGR.*[!=]=[[:space:]]*"apt"' "$dnf_only"
  [ "$status" -ne 0 ]
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

# ── Every desktop stage must lead to the flatpak baseline ──────────────────
#
# The baseline (Flathub remote + curated preinstall + preinstall service) has
# exactly two carriers: install-desktop.sh's manifest post_install hooks, and
# configure-desktop-runtime.sh's contract-family block. A desktop stage that
# runs a per-DE session script WITHOUT either carrier ships a desktop whose
# own build contract fails — grouper:xfce did exactly that (run 31192228329:
# "missing required path: /etc/flatpak/remotes.d/flathub.flatpakrepo")
# because Containerfile.ubuntu's xfce stage ran xfce.sh + the contract but
# the baseline only existed in manifest post_install. Stage lists are DERIVED
# from the Containerfiles, not hardcoded, so a new stage cannot dodge this.

# Print "file:stage_start_line" for every stage in $1 that invokes a per-DE
# SESSION script (a desktop id's own .sh) without install-desktop.sh or
# configure-desktop-runtime.sh in the same stage.
stages_missing_baseline() {
  sed 's/^[[:space:]]*#.*//' "$1" | awk -v file="$1" '
    /^FROM /            { if (bad && !ok) print file ":" start; start=NR; bad=0; ok=0 }
    /\/run\/context\/build_scripts\/desktop\/(gnome|kde|cosmic|niri|xfce|pantheon)\.sh/ { bad=1 }
    /install-desktop\.sh|configure-desktop-runtime\.sh/ { ok=1 }
    END                 { if (bad && !ok) print file ":" start }
  '
}

@test "every desktop stage runs install-desktop.sh or configure-desktop-runtime.sh" {
  local fail=0 f
  for f in "${REPO_ROOT}"/Containerfile.*; do
    [[ "$f" == *Containerfile.overlay || "$f" == *Containerfile.final || "$f" == *Containerfile.custom ]] && continue
    while IFS= read -r hit; do
      [ -n "$hit" ] || continue
      echo "FAIL: desktop stage without a baseline/contract carrier at $hit" >&2
      fail=1
    done < <(stages_missing_baseline "$f")
  done
  [ "$fail" -eq 0 ]
}

@test "the script-driven stages actually exist and rely on configure-desktop-runtime" {
  # Sanity for the test above: Containerfile.ubuntu's niri and xfce stages
  # are the known script-driven pair. If they migrate to install-desktop.sh
  # this test documents the change; if they lose configure-desktop-runtime
  # the test above turns red.
  run grep -A1 'desktop/xfce.sh base' "${REPO_ROOT}/Containerfile.ubuntu"
  [[ "$output" == *"configure-desktop-runtime.sh xfce"* ]]
  run grep -A1 'desktop/niri.sh base' "${REPO_ROOT}/Containerfile.ubuntu"
  [[ "$output" == *"configure-desktop-runtime.sh niri"* ]]
}

@test "configure-desktop-runtime lays down the flatpak baseline before verifying it" {
  local script="${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"
  local remote_line preinstall_line verify_line
  remote_line=$(grep -n 'source /run/context/build_scripts/desktop/tuna-flatpak-remote.sh' "$script" | head -1 | cut -d: -f1)
  preinstall_line=$(grep -n 'source /run/context/build_scripts/desktop/flatpak-preinstall.sh' "$script" | head -1 | cut -d: -f1)
  verify_line=$(grep -n '/run/context/build_scripts/checks/verify-desktop-experience.sh "\$desktop"' "$script" | head -1 | cut -d: -f1)
  [ -n "$remote_line" ] && [ -n "$preinstall_line" ] && [ -n "$verify_line" ]
  # Install first, verify second — the contract asserts what was just laid down.
  [ "$remote_line" -lt "$verify_line" ]
  [ "$preinstall_line" -lt "$verify_line" ]
  # DESKTOP_FLAVOR must be exported first: flatpak-preinstall.sh names its
  # preinstall file after it.
  run grep -B10 'source /run/context/build_scripts/desktop/flatpak-preinstall.sh' "$script"
  [[ "$output" == *'export DESKTOP_FLAVOR="$desktop"'* ]]
}
