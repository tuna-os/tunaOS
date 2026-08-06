#!/usr/bin/env bats
# The libostree the apt bases link bootc against.
#
# bootc comes from the sid toolchain tarball and is linked against
# LIBOSTREE_2025.2 / LIBOSTREE_2025.3. Whether the distro archive's libostree
# provides those symbols is a per-release accident:
#
#   ubuntu noble    (24.04, gurnard)   ostree 2024.5-1build2   too old
#   ubuntu resolute (26.04, grouper)   ostree 2025.7-3build1   fine
#   debian trixie                      2025.2                  too old
#   debian sid                         >= 2025.3               fine
#
# apt-installing the archive package when it is too old overwrites the
# toolchain's source library, and bootc cannot start:
#
#   bootc: /lib/x86_64-linux-gnu/libostree-1.so.1: version `LIBOSTREE_2025.2'
#     not found (required by bootc)
#
# Containerfile.debian solved this with an equivs dummy. Containerfile.ubuntu,
# which serves two releases straddling the boundary, did not — gurnard:pantheon
# died there after the PPA, sudo and trust-policy fixes had cleared everything
# ahead of it.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

strip_comments() { grep -v '^[[:space:]]*#' || true; }

@test "both apt Containerfiles keep the toolchain's libostree when the archive is too old" {
  local f code
  for f in Containerfile.ubuntu Containerfile.debian; do
    code="$(strip_comments <"${REPO_ROOT}/$f")"
    grep -qF 'equivs' <<<"$code" || {
      echo "FAIL: ${f} has no equivs fallback for an old archive libostree" >&2
      return 1
    }
    grep -qF 'apt-mark hold libostree-1-1' <<<"$code" || {
      echo "FAIL: ${f} does not hold the dummy, so a later apt run replaces it" >&2
      return 1
    }
    grep -qF 'ldconfig' <<<"$code" || {
      echo "FAIL: ${f} does not ldconfig after installing the dummy" >&2
      return 1
    }
  done
}

@test "ubuntu decides by version, not by codename" {
  # This file serves noble and resolute and the boundary runs between them, so
  # a codename match is one release bump away from silently selecting the wrong
  # branch. debian's own version of this keys on *sid* and gets away with it
  # because sid is a rolling name, not a release.
  local code
  code="$(strip_comments <"${REPO_ROOT}/Containerfile.ubuntu")"
  grep -qF 'dpkg --compare-versions' <<<"$code"
  grep -qE 'dpkg --compare-versions .* ge 2025\.3' <<<"$code"
  # And it must not be picking the branch off the release name.
  run grep -cE 'case .*BASE_IMAGE.*in.*(noble|resolute)' <<<"$code"
  [ "$output" -eq 0 ]
}

@test "ubuntu does not apt-install libostree unconditionally" {
  # The regression: naming libostree-1-1 (or ostree, which depends on it) in
  # the main package list pulls the archive version in regardless of what the
  # version check decided a few lines earlier.
  #
  # Asserted by enumerating the places the name may legitimately appear rather
  # than by trying to carve the right RUN block out with awk — the first
  # version of this test did that, and it passed with the offending line put
  # straight back, which is worse than having no test at all.
  local code line stray=0
  code="$(strip_comments <"${REPO_ROOT}/Containerfile.ubuntu")"
  while IFS= read -r line; do
    case "$line" in
      *"apt-cache policy libostree-1-1"*) ;;   # the version probe
      *"echo \"archive libostree-1-1"*) ;;     # logging what the probe found
      *"libostree-1-1 ostree;"*) ;;            # the guarded install
      *"apt-mark hold libostree-1-1"*) ;;      # pinning the dummy
      *"Package: libostree-1-1"*) ;;           # the equivs control file
      *"dpkg -i libostree-1-1_"*) ;;           # installing the dummy
      *)
        echo "FAIL: unguarded libostree reference: ${line}" >&2
        stray=1
        ;;
    esac
  done < <(grep -F 'libostree-1-1' <<<"$code" || true)
  [ "$stray" -eq 0 ]

  # And `ostree` as a bare package argument on its own continuation line —
  # it depends on libostree-1-1, so installing it drags the archive lib in.
  run grep -cE '^[[:space:]]+ostree([[:space:]]|\\|$)' <<<"$code"
  [ "$output" -eq 0 ]
}

@test "the decision is verified before the image ships" {
  # A wrong branch must fail the build here, not twenty minutes into a QEMU
  # guest as "bootc install to-filesystem (via container): exit status 1".
  local code
  code="$(strip_comments <"${REPO_ROOT}/Containerfile.ubuntu")"
  grep -qE 'bootc --version' <<<"$code"
}
