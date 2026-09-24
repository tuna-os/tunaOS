#!/usr/bin/env bats
# Every variant ships its own Noto Emoji mark, and it is the emoji build-config
# names for that variant.
#
# 90-image-info.sh installs /usr/share/tunaos/logos/<variant>.svg over the
# tunaos icon that GNOME About, GDM and the KDE splash read. A variant with no
# file silently falls back to the generic 🐟 — which is how marlin:gnome ended
# up showing a stock fish instead of its 🚀.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
LOGOS="${REPO_ROOT}/system_files/usr/share/tunaos/logos"
CONFIG="${REPO_ROOT}/.github/build-config.yml"

@test "every build-config variant has a logo" {
  command -v yq >/dev/null || skip "yq not installed"
  local v
  while read -r v; do
    [[ -f "${LOGOS}/${v}.svg" ]] || {
      echo "FAIL: no ${LOGOS}/${v}.svg; ${v} would show the generic fish." >&2
      return 1
    }
  done < <(yq -r '.variants[].id' "$CONFIG")
}

@test "each logo is the Noto glyph for the variant's build-config emoji" {
  command -v yq >/dev/null || skip "yq not installed"
  local v e cp
  while IFS=$'\t' read -r v e; do
    # First codepoint, dropping the U+FE0F presentation selector.
    cp="$(LC_ALL=C.UTF-8 printf '%X' "'${e}")"
    grep -q "U+${cp} from Noto Emoji" "${LOGOS}/${v}.svg" || {
      echo "FAIL: ${v}.svg is not U+${cp} (${e})." >&2
      return 1
    }
  done < <(yq -r '.variants[] | [.id, .emoji] | @tsv' "$CONFIG")
}

@test "90-image-info installs the variant logo over the tunaos icon" {
  grep -q '/usr/share/tunaos/logos/${VARIANT_KEY}.svg' "${REPO_ROOT}/build_scripts/90-image-info.sh"
}
