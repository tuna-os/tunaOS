#!/usr/bin/env bats
# The libostree the apt bases link bootc against.
#
# bootc is linked against LIBOSTREE_2025.2 / LIBOSTREE_2025.3. Whether a base
# can satisfy that is a per-release accident:
#
#   debian trixie                      ostree 2025.2            too old
#   debian sid                         >= 2025.3                fine
#   ubuntu noble    (24.04, gurnard)   ostree 2024.5-1build2    too old
#   ubuntu resolute (26.04, grouper)   ostree 2025.7-3build1    fine
#
# Containerfile.debian handles trixie with an equivs dummy that stops apt
# installing the old library. The dummy is only half of that pattern, and the
# other half is what makes it work: debian's toolchain is built with
# BUILD_OSTREE=1 and ships a source libostree for exactly this case.
#
# A dummy in a file whose toolchain carries none replaces "wrong version" with
# nothing at all:
#
#   bootc: error while loading shared libraries: libostree-1.so.1:
#     cannot open shared object file: No such file or directory
#
# which is what gurnard:pantheon did when this was tried. So the invariant is
# not "use a dummy" but "a dummy requires a libostree the image actually gets".
# There are two honest ways to get one — a toolchain built with build_ostree=1,
# or a source build in the same file (Containerfile.ubuntu's bootc-builder
# stage runs build_scripts/bootc/build-libostree.sh for noble) — and the tests
# below accept either, because the property is the library's presence, not the
# mechanism that produced it.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/build-toolchain.yml"

strip_comments() { grep -v '^[[:space:]]*#' || true; }

# One logical line per instruction: comments dropped, continuations joined.
# Matching the raw file is not enough — a package name three lines into a RUN's
# continuation is a different instruction from the one that mentions it, and a
# COPY of a script is not a call to it.
instructions() {
  strip_comments <"${REPO_ROOT}/$1" |
    sed -e ':a' -e '/\\$/N; s/\\\n/ /; ta'
}

# Does the toolchain matrix build this base with libostree?
toolchain_ships_ostree() {
  awk -v base="$1" '
    $0 ~ ("- base: " base "$") {found=1; next}
    found && /build_ostree:/ {gsub(/[^01]/, "", $2); print $2; exit}
    found && /- base:/ {exit}
  ' "$WORKFLOW"
}

# Does this file build a libostree from source itself?
builds_own_ostree() {
  grep -qE '^RUN .*build-libostree\.sh' <<<"$(instructions "$1")"
}

@test "the toolchain matrix is the shape these tests assume" {
  # If these flip, every assertion below is reasoning about a world that no
  # longer exists.
  [ "$(toolchain_ships_ostree trixie)" = "1" ]
  [ "$(toolchain_ships_ostree sid)" = "0" ]
}

@test "an equivs libostree dummy only appears where a libostree does" {
  local f code
  for f in Containerfile.ubuntu Containerfile.debian; do
    code="$(strip_comments <"${REPO_ROOT}/$f")"
    grep -qF 'Package: libostree-1-1' <<<"$code" || continue

    # It has a dummy. Either it builds its own libostree, or every toolchain it
    # can pull must carry one.
    builds_own_ostree "$f" && continue

    local tc bad=0
    while read -r tc; do
      [ -n "$tc" ] || continue
      # ${TC} is resolved by a case just above; check both arms.
      if [ "$tc" = '${TC}' ]; then
        [ "$(toolchain_ships_ostree trixie)" = "1" ] || bad=1
        continue
      fi
      [ "$(toolchain_ships_ostree "$tc")" = "1" ] || {
        echo "FAIL: ${f} builds a libostree equivs dummy but pulls" >&2
        echo "      bootc-toolchain-${tc}, which is built with build_ostree=0" >&2
        echo "      and ships no libostree, and it does not build one itself —" >&2
        echo "      the dummy leaves the image with none." >&2
        bad=1
      }
    done < <(grep -oE 'bootc-toolchain-(\$\{[A-Za-z_]+\}|[a-z0-9]+)' <<<"$code" |
      sed 's/bootc-toolchain-//' | sort -u)
    [ "$bad" -eq 0 ]
  done
}

@test "debian still keeps the toolchain's libostree on trixie" {
  # The half that works, and the reason the pattern exists at all.
  local code
  code="$(strip_comments <"${REPO_ROOT}/Containerfile.debian")"
  grep -qF 'equivs' <<<"$code"
  grep -qF 'apt-mark hold libostree-1-1' <<<"$code"
  grep -qF 'ldconfig' <<<"$code"
  # And it must still choose its toolchain per base, or the dummy lands on sid.
  grep -qE 'bootc-toolchain-\$\{TC\}' <<<"$code"
}

@test "ubuntu proves bootc loads before the image ships" {
  # Both halves matter. Without the source build, noble ships a bootc it cannot
  # load; without the assertion, nothing in the build notices — the image
  # builds, lints and boots, and fisherman finds out forty minutes later inside
  # a QEMU guest as "bootc install to-filesystem (via container): exit 1".
  local insns
  insns="$(instructions Containerfile.ubuntu)"
  grep -qE '^RUN .*build-libostree\.sh' <<<"$insns"
  grep -qE '^RUN .*LD_BIND_NOW=1 bootc --version' <<<"$insns"
}

@test "ubuntu never lets the archive libostree back in over the source one" {
  # flatpak Depends on libostree-1-1; an unguarded install of it drops 2024.5
  # onto the same path the source lib occupies and undoes everything above.
  local insns libostree_installs
  insns="$(instructions Containerfile.ubuntu)"
  libostree_installs="$(grep -E '^RUN .*apt-get install[^;]*libostree-1-1' <<<"$insns" || true)"

  # Exactly one instruction may install it, and it must be the one that also
  # holds the dummy — i.e. the guarded either/or, not a plain package list.
  [ "$(grep -c . <<<"$libostree_installs")" -eq 1 ]
  grep -qF 'apt-mark hold libostree-1-1' <<<"$libostree_installs"
  grep -qF 'Package: libostree-1-1' <<<"$libostree_installs"
}
