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
# installing the old library. That works ONLY because its toolchain is built
# with BUILD_OSTREE=1 and ships a source libostree for exactly this case.
#
# Copying the dummy into a file whose toolchain is built with BUILD_OSTREE=0
# does not fix anything — it replaces "wrong version" with nothing at all:
#
#   bootc: error while loading shared libraries: libostree-1.so.1:
#     cannot open shared object file: No such file or directory
#
# which is what gurnard:pantheon did when this was tried. So the invariant is
# not "use a dummy" but "a dummy requires a toolchain that carries the library".

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/build-toolchain.yml"

strip_comments() { grep -v '^[[:space:]]*#' || true; }

# Does the toolchain matrix build this base with libostree?
toolchain_ships_ostree() {
  awk -v base="$1" '
    $0 ~ ("- base: " base "$") {found=1; next}
    found && /build_ostree:/ {gsub(/[^01]/, "", $2); print $2; exit}
    found && /- base:/ {exit}
  ' "$WORKFLOW"
}

@test "the toolchain matrix is the shape these tests assume" {
  # If these flip, every assertion below is reasoning about a world that no
  # longer exists.
  [ "$(toolchain_ships_ostree trixie)" = "1" ]
  [ "$(toolchain_ships_ostree sid)" = "0" ]
}

@test "an equivs libostree dummy only appears where the toolchain ships one" {
  local f code
  for f in Containerfile.ubuntu Containerfile.debian; do
    code="$(strip_comments <"${REPO_ROOT}/$f")"
    grep -qF 'Package: libostree-1-1' <<<"$code" || continue

    # It has a dummy. Every toolchain it can pull must carry a libostree.
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
        echo "      and ships no libostree — the dummy leaves the image with none." >&2
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

@test "ubuntu proves bootc can start before the image ships" {
  # noble cannot be fixed from Containerfile.ubuntu — it needs a noble entry in
  # the toolchain matrix. Until then the failure must at least be a three-minute
  # build error naming the cause, not a linker error twenty minutes into a QEMU
  # guest reported as "bootc install to-filesystem (via container): exit 1".
  local code guard
  code="$(strip_comments <"${REPO_ROOT}/Containerfile.ubuntu")"
  grep -qF 'bootc --version' <<<"$code"
  guard="$(sed -n '/if ! bootc --version/,/fi$/p' "${REPO_ROOT}/Containerfile.ubuntu")"
  [ -n "$guard" ]
  grep -qF 'exit 1' <<<"$guard"
  # The message has to name the actual fix, since the obvious one is wrong.
  grep -qF 'build_ostree' <<<"$guard"
}
