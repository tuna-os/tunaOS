#!/usr/bin/env bats
# Each variant's identity: an accent borrowed from its base, a wallpaper scene,
# and the hooks that put both on screen.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
TSV="${REPO_ROOT}/build_scripts/lib/variant-identity.tsv"
CONFIG="${REPO_ROOT}/.github/build-config.yml"
WALLS="${REPO_ROOT}/system_files/usr/share/backgrounds/tunaos"

rows() { grep -v '^#' "$TSV" | grep -v '^$'; }

@test "every build-config variant has an identity row" {
  command -v yq >/dev/null || skip "yq not installed"
  local v
  while read -r v; do
    rows | cut -f1 | grep -qx "$v" || { echo "FAIL: ${v} missing from variant-identity.tsv" >&2; return 1; }
  done < <(yq -r '.variants[].id' "$CONFIG")
}

@test "identity rows are well formed" {
  local id accent gnome base homage
  while IFS=$'\t' read -r id accent gnome base homage; do
    [[ "$accent" =~ ^#[0-9A-Fa-f]{6}$ ]] || { echo "FAIL: ${id} accent '${accent}'" >&2; return 1; }
    [[ " blue teal green yellow orange red pink purple slate " == *" ${gnome} "* ]] ||
      { echo "FAIL: ${id} gnome_accent '${gnome}' is not a GNOME accent name" >&2; return 1; }
    [[ -n "$base" && -n "$homage" ]] || { echo "FAIL: ${id} has no base/homage" >&2; return 1; }
  done < <(rows)
}

@test "every variant has a rendered wallpaper, and there is a generic one" {
  [ -f "${WALLS}/tunaos-default.jpg" ]
  local id
  while IFS=$'\t' read -r id _; do
    [ -f "${WALLS}/${id}.jpg" ] || { echo "FAIL: no ${id}.jpg; run scripts/branding/render-wallpapers.mjs" >&2; return 1; }
  done < <(rows)
}

@test "the old hand-drawn wallpaper is gone" {
  [ ! -e "${WALLS}/tunaos-default.png" ]
  # Comments may still quote the old name when they record a measured image.
  ! grep -rn "tunaos-default.png" "${REPO_ROOT}/system_files" "${REPO_ROOT}/build_scripts/desktop" | grep -v ':[0-9]*:[[:space:]]*#'

}

@test "every variant has a wallpaper scene and an art prompt" {
  command -v node >/dev/null || skip "node not installed"
  run node --input-type=module -e '
    const [scenes, prompts] = await Promise.all([
      import(process.argv[1] + "/scripts/branding/wallpaper.svg.mjs"),
      import(process.argv[1] + "/scripts/branding/art-prompts.mjs"),
    ]);
    const { readFileSync } = await import("node:fs");
    const ids = readFileSync(process.argv[1] + "/build_scripts/lib/variant-identity.tsv", "utf8")
      .split("\n").filter(l => l && !l.startsWith("#")).map(l => l.split("\t")[0]);
    for (const id of ids) {
      if (!scenes.SCENE_IDS.includes(id)) throw new Error("no scene: " + id);
      for (const d of Object.keys(prompts.DESKTOPS)) prompts.prompt(id, d);
    }
  ' "$REPO_ROOT"
  [ "$status" -eq 0 ] || { echo "$output" >&2; return 1; }
}

@test "select-wallpaper prefers per-desktop art, then the variant scene" {
  local root="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${root}/usr/share/backgrounds/tunaos" "${root}/usr/share/tunaos"
  echo "TUNAOS_VARIANT='wahoo'" >"${root}/usr/share/tunaos/identity.env"
  echo scene >"${root}/usr/share/backgrounds/tunaos/wahoo.jpg"
  echo painted >"${root}/usr/share/backgrounds/tunaos/wahoo-gnome.jpg"
  echo generic >"${root}/usr/share/backgrounds/tunaos/tunaos-default.jpg"

  "${REPO_ROOT}/build_scripts/desktop/select-wallpaper.sh" gnome-nvidia "$root"
  [ "$(cat "${root}/usr/share/backgrounds/tunaos/tunaos-default.jpg")" = painted ]

  "${REPO_ROOT}/build_scripts/desktop/select-wallpaper.sh" kde "$root"
  [ "$(cat "${root}/usr/share/backgrounds/tunaos/tunaos-default.jpg")" = scene ]
}

@test "cosmic-set-branding points cosmic-bg at the TunaOS wallpaper" {
  local root="${BATS_TEST_TMPDIR}/root"
  "${REPO_ROOT}/build_scripts/desktop/cosmic-set-branding.sh" "$root"
  local conf="${root}/usr/share/cosmic/com.system76.CosmicBackground/v1/all"
  grep -q 'source: Path("/usr/share/backgrounds/tunaos/tunaos-default.jpg")' "$conf"
  grep -q 'filter_by_theme: false' "$conf"
}

@test "gnome-set-branding writes the accent and a dconf profile that reads local" {
  local root="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${root}/usr/share/tunaos"
  echo "TUNAOS_GNOME_ACCENT='orange'" >"${root}/usr/share/tunaos/identity.env"
  "${REPO_ROOT}/build_scripts/desktop/gnome-set-branding.sh" "$root"
  grep -q "^accent-color='orange'" "${root}/etc/dconf/db/local.d/10-tunaos-branding"
  grep -qx 'system-db:local' "${root}/etc/dconf/profile/user"
}

@test "gnome-set-branding adds system-db:local to a profile that lacks it, once" {
  local root="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${root}/etc/dconf/profile"
  echo 'user-db:user' >"${root}/etc/dconf/profile/user"
  "${REPO_ROOT}/build_scripts/desktop/gnome-set-branding.sh" "$root"
  "${REPO_ROOT}/build_scripts/desktop/gnome-set-branding.sh" "$root"
  [ "$(grep -cx 'system-db:local' "${root}/etc/dconf/profile/user")" -eq 1 ]
}

@test "kde-set-look-and-feel writes the variant accent into [General]" {
  local f="${BATS_TEST_TMPDIR}/kdeglobals" id="${BATS_TEST_TMPDIR}/identity.env"
  printf '[General]\nColorScheme=BreezeDark\n' >"$f"
  echo "TUNAOS_ACCENT_RGB='233,84,32'" >"$id"
  TUNAOS_IDENTITY="$id" "${REPO_ROOT}/build_scripts/desktop/kde-set-look-and-feel.sh" "$f"
  TUNAOS_IDENTITY="$id" "${REPO_ROOT}/build_scripts/desktop/kde-set-look-and-feel.sh" "$f"
  [ "$(grep -c '^AccentColor=233,84,32$' "$f")" -eq 1 ]
  grep -q '^ColorScheme=BreezeDark$' "$f"
}

@test "both desktop call sites pick the wallpaper and brand COSMIC" {
  local p
  for p in build_scripts/desktop/install-desktop.sh build_scripts/desktop/configure-desktop-runtime.sh; do
    grep -q "select-wallpaper.sh" "${REPO_ROOT}/${p}" || { echo "${p} never calls select-wallpaper.sh" >&2; return 1; }
    grep -q "cosmic-set-branding.sh" "${REPO_ROOT}/${p}" || { echo "${p} never calls cosmic-set-branding.sh" >&2; return 1; }
  done
}
