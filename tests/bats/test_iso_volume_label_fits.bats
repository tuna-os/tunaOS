#!/usr/bin/env bats
# The ISO 9660 volume ID is capped at 32 characters, and xorriso does not
# truncate — it aborts the entire build:
#
#   xorriso : FAILURE : -volid: Text too long (34 > 32)
#   Error: xorriso: ... -commit: exit status 5
#
# bonito-rawhide hit this the moment its nvidia flavors were built. The
# arithmetic names the casualties exactly (run 35192681250):
#
#   tunaos-bonito-rawhide-cosmic-nvidia   35  failed
#   tunaos-bonito-rawhide-gnome-nvidia    34  failed
#   tunaos-bonito-rawhide-niri-nvidia     33  failed
#   tunaos-bonito-rawhide-xfce-nvidia     33  failed
#   tunaos-bonito-rawhide-kde-nvidia      32  BUILT
#
# kde-nvidia sitting exactly on the limit is the whole proof: this is a
# length bug, not an nvidia bug, and nothing is wrong with those images.
#
# The label is load-bearing — tacklebox puts the same string on the kernel
# cmdline as `root=tbox:CDLABEL=...` — but both sides come from media_name,
# so shortening it moves them together.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  # shellcheck source=/dev/null
  . "${REPO_ROOT}/scripts/lib/common.sh" >/dev/null 2>&1 || true
}

name_for() { tunaos_iso_media_name "$1"; }

@test "the four cells that aborted the build now fit" {
  for cell in bonito-rawhide-cosmic-nvidia \
              bonito-rawhide-gnome-nvidia \
              bonito-rawhide-niri-nvidia \
              bonito-rawhide-xfce-nvidia; do
    out="$(name_for "tunaos-${cell}")"
    [ "${#out}" -le 32 ] || {
      echo "tunaos-${cell} -> '${out}' is ${#out} chars; xorriso aborts above 32" >&2
      return 1
    }
  done
}

# The cell that already fit must come through byte-for-byte. Shortening a name
# that was never too long would rename a shipped ISO's volume label, and that
# label is on the kernel cmdline.
@test "a name that already fits is returned unchanged" {
  for n in tunaos-bonito-rawhide-kde-nvidia \
           tunaos-marlin-gnome \
           tunaos-yellowfin-kde; do
    out="$(name_for "$n")"
    [ "$out" = "$n" ] || {
      echo "'$n' (${#n} chars) was rewritten to '$out' despite fitting" >&2
      return 1
    }
  done
}

# 32 exactly is legal. An off-by-one here would rename kde-nvidia, the one
# cell in that group that was building fine.
@test "a name of exactly 32 characters is left alone" {
  n="$(printf 'a%.0s' {1..32})"
  out="$(name_for "$n")"
  [ "$out" = "$n" ]
  [ "${#out}" -eq 32 ]
}

@test "a name of 33 characters is shortened to at most 32" {
  n="tunaos-$(printf 'a%.0s' {1..26})"
  [ "${#n}" -eq 33 ]
  out="$(name_for "$n")"
  [ "${#out}" -le 32 ]
}

# The backstop: a name too long even without the vendor prefix still has to
# come out legal, and two different such names must not collide into one
# label.
@test "an over-long name survives the prefix drop and stays unique" {
  a="tunaos-$(printf 'x%.0s' {1..40})-alpha"
  b="tunaos-$(printf 'x%.0s' {1..40})-beta"
  oa="$(name_for "$a")"
  ob="$(name_for "$b")"
  [ "${#oa}" -le 32 ]
  [ "${#ob}" -le 32 ]
  [ "$oa" != "$ob" ]
}

@test "the result is deterministic" {
  n="tunaos-bonito-rawhide-cosmic-nvidia"
  [ "$(name_for "$n")" = "$(name_for "$n")" ]
}

# Both ISO builders must route through the helper, or one of them grows this
# bug back. Presence of the function is not reach from the script.
@test "both ISO builders call the helper" {
  for s in scripts/build-iso-tacklebox.sh scripts/build-iso-group.sh; do
    run bash -c "grep -qE '^[^#]*tunaos_iso_media_name' '${REPO_ROOT}/${s}'"
    [ "$status" -eq 0 ] || {
      echo "${s} builds a media_name without capping it at 32 chars" >&2
      return 1
    }
  done
}

# The recipe must carry the capped value, not the raw one.
@test "the recipe uses the capped name" {
  run grep -E '"media_name": "\$\{MEDIA_NAME\}"' "${REPO_ROOT}/scripts/build-iso-tacklebox.sh"
  [ "$status" -eq 0 ]
  run grep -E '"media_name": "tunaos-\$\{VARIANT\}' "${REPO_ROOT}/scripts/build-iso-tacklebox.sh"
  [ "$status" -ne 0 ]
}
