#!/usr/bin/env bats
# Every variant boots into its own emoji animation, and that theme is complete.
#
# Until plymouth-set-theme.sh, only the EL10 path selected a theme; marlin,
# grouper, flounder, sailfin and guppy booted with the distro splash although
# the themes were in the image.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SET="${REPO_ROOT}/build_scripts/plymouth-set-theme.sh"
THEMES="${REPO_ROOT}/system_files/usr/share/plymouth/themes"
CONFIG="${REPO_ROOT}/.github/build-config.yml"

@test "every build-config variant maps to a theme that exists" {
  command -v yq >/dev/null || skip "yq not installed"
  local v t
  while read -r v; do
    t="$("$SET" --print "$v")"
    [ -f "${THEMES}/${t}/${t}.plymouth" ] || { echo "FAIL: ${v} -> ${t}, which has no theme" >&2; return 1; }
  done < <(yq -r '.variants[].id' "$CONFIG")
}

@test "only albacore falls back to the generic fish" {
  command -v yq >/dev/null || skip "yq not installed"
  local v
  while read -r v; do
    [[ "$v" == albacore ]] && continue
    [ "$("$SET" --print "$v")" != tunaos ] || { echo "FAIL: ${v} boots the generic fish" >&2; return 1; }
  done < <(yq -r '.variants[].id' "$CONFIG")
}

@test "each theme ships the frames its script loads" {
  local d t n i
  for d in "${THEMES}"/*/; do
    t="$(basename "$d")"
    [ -f "${d}${t}.script" ] || { echo "FAIL: ${t} has no script" >&2; return 1; }
    n="$(sed -n 's/^FRAME_COUNT = \([0-9]*\);.*/\1/p' "${d}${t}.script")"
    for ((i = 1; i <= n; i++)); do
      compgen -G "${d}*-$(printf '%04d' "$i").png" >/dev/null ||
        { echo "FAIL: ${t} script wants ${n} frames, frame ${i} is missing" >&2; return 1; }
    done
  done
}

@test "every non-EL10 base selects the theme before dracut" {
  grep -q 'plymouth-set-theme.sh' "${REPO_ROOT}/build_scripts/bootc/dracut-config.sh"
  grep -q 'plymouth-set-theme.sh' "${REPO_ROOT}/build_scripts/bootc/finalize.sh"
  grep -q 'plymouth-set-theme.sh' "${REPO_ROOT}/build_scripts/26-packages-post.sh"
  # openSUSE calls dracut itself: the selection must come first in that RUN.
  awk '/plymouth-set-theme.sh/ { seen = 1 } /dracut --force/ && !seen { exit 1 }' "${REPO_ROOT}/Containerfile.opensuse"
}
