#!/usr/bin/env bats
# Every tour slide in recipe.json names an image by absolute path, and the
# GTK frontend has no fallback: a path that does not resolve renders as a
# broken slide, four times over. recipe.json has referenced
# /run/host/usr/share/bootc-installer/images/tunaos-install.png since the
# tour was added and NOTHING installed it — the file existed in no build.
#
# The failure is invisible from outside: the installer starts, the tour
# advances, and only the picture shows the missing art. So assert the
# files statically, from the recipe itself, rather than trusting a list
# maintained by hand.

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
RECIPE="${REPO_ROOT}/system_files/etc/bootc-installer/recipe.json"

# The installer runs as a flatpak, so it reads the host filesystem through
# /run/host. Strip that prefix to get the path the image must occupy in the
# built image, which system_files/ mirrors one-to-one.
recipe_image_paths() {
  jq -r '.tour | to_entries[] | .value.image' "$RECIPE" \
    | sed 's,^/run/host,,' | sort -u
}

@test "recipe.json parses and declares tour slides" {
  [ -f "$RECIPE" ]
  run jq -e '.tour | length > 0' "$RECIPE"
  [ "$status" -eq 0 ]
}

@test "every tour image referenced by recipe.json is shipped in system_files" {
  local missing=0 p
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    if [ ! -f "${REPO_ROOT}/system_files${p}" ]; then
      echo "recipe.json tour references ${p} but system_files${p} does not exist" >&2
      missing=1
    fi
  done < <(recipe_image_paths)
  [ "$missing" -eq 0 ]
}

@test "every tour image is a real image file, not a placeholder" {
  local p
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    local f="${REPO_ROOT}/system_files${p}"
    [ -s "$f" ]
    run file -b "$f"
    [[ "$output" == *"image data"* ]]
  done < <(recipe_image_paths)
}

@test "the credits file recipe.json names is shipped too" {
  # Same class of defect, same blindness — a missing credits.json shows an
  # empty dialog rather than an error.
  local c
  c="$(jq -r '.credits_data // empty' "$RECIPE" | sed 's,^/run/host,,')"
  if [ -n "$c" ]; then
    [ -f "${REPO_ROOT}/system_files${c}" ]
  fi
}
