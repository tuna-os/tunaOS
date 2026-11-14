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

@test "only fish-branded variants fall back to the generic fish" {
  command -v yq >/dev/null || skip "yq not installed"
  local v
  while read -r v; do
    [[ "$v" == albacore || "$v" == stingray ]] && continue
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

@test "openSUSE installs plymouth for its initramfs and verifies the result" {
  local cf="${REPO_ROOT}/Containerfile.opensuse"
  for pkg in plymouth plymouth-dracut plymouth-plugin-script plymouth-plugin-label-ft fontconfig; do
    grep -Eq "[[:space:]]${pkg}[[:space:]]" "$cf" || { echo "missing ${pkg}" >&2; return 1; }
  done
  awk '/dracut --force/ { seen = 1 } /verify-plymouth-initramfs.sh/ && seen { found = 1 } END { exit !found }' "$cf"
}

@test "openSUSE gets the splash karg its GRUB defaults would have carried" {
  local root block
  root="$(mktemp -d)"
  # The karg decision, run against a fake os-release instead of /usr/lib/os-release.
  block="$(sed -n '/^splash_karg=/,/^fi$/p' "$SET" | sed "s|/usr/lib/os-release|${root}/os-release|")"
  [[ "$block" == *ID_LIKE* ]]
  printf 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n' >"${root}/os-release"
  run bash -c "alternatives_done=false; ${block}; echo \"\$splash_karg\""
  [ "$output" = true ]
  printf 'ID=fedora\n' >"${root}/os-release"
  run bash -c "alternatives_done=false; ${block}; echo \"\$splash_karg\""
  rm -rf "$root"
  [ "$output" = false ]
}

@test "Arch and CachyOS get the splash karg no Arch installer carries over to bootc" {
  local root block
  root="$(mktemp -d)"
  # Every decision from `splash_karg=` up to the line that acts on it.
  block="$(sed -n '/^splash_karg=/,/^if \$splash_karg; then/p' "$SET" | sed '$d' | sed "s|/usr/lib/os-release|${root}/os-release|")"
  printf 'ID=arch\n' >"${root}/os-release"
  run bash -c "alternatives_done=false; ${block}; echo \"\$splash_karg\""
  [ "$output" = true ]
  printf 'ID=cachyos\nID_LIKE=arch\n' >"${root}/os-release"
  run bash -c "alternatives_done=false; ${block}; echo \"\$splash_karg\""
  [ "$output" = true ]
  printf 'ID=fedora\n' >"${root}/os-release"
  run bash -c "alternatives_done=false; ${block}; echo \"\$splash_karg\""
  rm -rf "$root"
  # Falsification: without the Arch test this prints false for ID=arch.
  [ "$output" = false ]
}
