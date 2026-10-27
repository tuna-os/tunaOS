#!/usr/bin/env bats
# Unit tests for scripts/build-iso-group.sh and its helpers (issue #455).
#
# Exercises the pure-logic paths without root/podman/qemu:
#   - tunaos_flavor_title / tunaos_flavor_desktop mappings
#   - iso_groups config is well-formed and covers the documented suffixes
#   - group ∩ variant flavor intersection (incl. shrink for missing flavors)
#   - combined recipe JSON shape (dedup + multi-environment)

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  cd "${REPO_ROOT}" || exit 1
  CONFIG=".github/build-config.yml"
  # shellcheck source=../../scripts/lib/flavor.sh
  . "${REPO_ROOT}/scripts/lib/flavor.sh"
  # Recipe tests below also exercise the image-reference compatibility facade.
  # shellcheck source=../../scripts/lib/common.sh
  . "${REPO_ROOT}/scripts/lib/common.sh"
}

# ── Title mapping ───────────────────────────────────────────────────────────

@test "flavor library has no source-time working-directory side effect" {
  run bash -c 'before=$PWD; source "$1"; [[ "$PWD" == "$before" ]]' \
    _ "${REPO_ROOT}/scripts/lib/flavor.sh"
  [ "$status" -eq 0 ]
}

@test "title: gnome -> GNOME" {
  [ "$(tunaos_flavor_title gnome)" = "GNOME" ]
}

@test "title: gnome-hwe -> GNOME (HWE)" {
  [ "$(tunaos_flavor_title gnome-hwe)" = "GNOME (HWE)" ]
}

@test "title: kde -> KDE Plasma" {
  [ "$(tunaos_flavor_title kde)" = "KDE Plasma" ]
}

@test "title: gnome-nvidia -> GNOME (NVIDIA)" {
  [ "$(tunaos_flavor_title gnome-nvidia)" = "GNOME (NVIDIA)" ]
}

@test "title: gnome-nvidia-hwe -> GNOME (NVIDIA, HWE)" {
  [ "$(tunaos_flavor_title gnome-nvidia-hwe)" = "GNOME (NVIDIA, HWE)" ]
}

# ── Desktop mapping ─────────────────────────────────────────────────────────

@test "desktop: kde-hwe -> kde" {
  [ "$(tunaos_flavor_desktop kde-hwe)" = "kde" ]
}

@test "desktop: niri-nvidia -> niri" {
  [ "$(tunaos_flavor_desktop niri-nvidia)" = "niri" ]
}

@test "desktop: gnome-nvidia-hwe -> gnome" {
  [ "$(tunaos_flavor_desktop gnome-nvidia-hwe)" = "gnome" ]
}

@test "desktop: unknown flavor falls back to gnome" {
  [ "$(tunaos_flavor_desktop lxqt)" = "gnome" ]
}

@test "published refs fold Rawhide into bonito tag suffix" {
  run tunaos_image_ref bonito-rawhide gnome ghcr gnome
  [ "$status" -eq 0 ]
  [ "$output" = "ghcr.io/tuna-os/bonito:gnome-rawhide" ]
}

@test "published refs fold Sid into flounder tag suffix" {
  run tunaos_image_ref flounder-sid kde ghcr kde
  [ "$status" -eq 0 ]
  [ "$output" = "ghcr.io/tuna-os/flounder:kde-sid" ]
}

# ── Config shape ────────────────────────────────────────────────────────────

# One group per desktop, each embedding its own NVIDIA and HWE flavors.
# Previously two groups: the gnome flagship plus a `community` group that
# packed KDE, COSMIC, Niri and XFCE into ONE unpublished ISO.
@test "config: iso_groups defines one group per desktop" {
  json="$(yq -o=json '.' "$CONFIG")"
  suffixes="$(echo "$json" | jq -r '[.iso_groups[].suffix // ""] | sort | join(",")')"
  [ "$suffixes" = ",cosmic,kde,niri,xfce" ]
}

@test "config: no iso_group packs more than one desktop" {
  json="$(yq -o=json '.' "$CONFIG")"
  # The flagship group's suffix is "" and it is the gnome one.
  while read -r line; do
    [ -z "$line" ] && continue
    suffix="${line%%|*}"
    flavor="${line#*|}"
    desktop="${suffix:-gnome}"
    [ "${flavor%%-*}" = "$desktop" ] || {
      echo "group '$desktop' names '$flavor' from another desktop" >&2
      return 1
    }
  done < <(echo "$json" | jq -r '.iso_groups[] | (.suffix // "") as $s
             | (.flavors[], .offline_flavors[]) | "\($s)|\(.)"')
}

@test "config: every iso_group flavor exists on at least one variant" {
  json="$(yq -o=json '.' "$CONFIG")"
  all_flavors="$(echo "$json" | jq -r '[.variants[].flavors[].id] | unique | join("\n")')"
  while read -r f; do
    [ -z "$f" ] && continue
    echo "$all_flavors" | grep -qx "$f" || {
      echo "iso_group references unknown flavor: $f" >&2
      return 1
    }
  done < <(echo "$json" | jq -r '.iso_groups[].flavors[]')
}

# ── Intersection ────────────────────────────────────────────────────────────

# Replicates the group ∩ variant logic from build-iso-group.sh.
_select() {
  local group="$1" variant="$2" json f v
  json="$(yq -o=json '.' "$CONFIG")"
  local -a GF VF SEL=()
  mapfile -t GF < <(echo "$json" | jq -r --arg s "$group" '.iso_groups[]|select((.suffix//"")==$s)|.flavors[]')
  mapfile -t VF < <(echo "$json" | jq -r --arg v "$variant" '.variants[]|select(.id==$v)|.flavors[]|select(.build_image==true)|.id')
  for f in "${GF[@]}"; do
    for v in "${VF[@]}"; do
      [[ "$f" == "$v" ]] && { SEL+=("$f"); break; }
    done
  done
  echo "${SEL[*]}"
}

# The flagship group names gnome-nvidia AND gnome-nvidia-hwe, and the EL10
# family used to supply both. It no longer builds gnome-nvidia-hwe: that image
# boots to an emergency shell on "unknown filesystem type 'xfs'", because -hwe
# pulls Fedora 43's kernel under an EL10 dracut (tunaOS#2518). So the group
# resolves to gnome-nvidia alone, and the intersection in build-iso-group.sh is
# what drops it — no group needed editing.
#
# This is the same shape bonito has always had, which is why the two cases
# below now assert the same thing for different reasons.
@test "select: yellowfin flagship resolves to gnome-nvidia alone" {
  [ "$(_select '' yellowfin)" = "gnome-nvidia" ]
}

@test "select: albacore and skipjack flagships resolve the same way" {
  [ "$(_select '' albacore)" = "gnome-nvidia" ]
  [ "$(_select '' skipjack)" = "gnome-nvidia" ]
}

@test "select: bonito flagship shrinks (no gnome-nvidia-hwe on Fedora)" {
  [ "$(_select '' bonito)" = "gnome-nvidia" ]
}

@test "select: each desktop group resolves to its own nvidia flavor" {
  [ "$(_select kde bonito)" = "kde-nvidia" ]
  [ "$(_select cosmic bonito)" = "cosmic-nvidia" ]
  [ "$(_select niri bonito)" = "niri-nvidia" ]
  [ "$(_select xfce bonito)" = "xfce-nvidia" ]
}

# skipjack has no xfce-nvidia, so its xfce group must resolve to nothing and
# be skipped rather than build something broken. A group naming a flavor a
# variant lacks is the normal case now, not an edge one.
@test "select: a variant missing a desktop's nvidia flavor drops that group" {
  [ -z "$(_select xfce skipjack)" ]
}

@test "select: grand total is 19 grouped ISOs across 4 variants" {
  local count=0
  for g in '' kde cosmic niri xfce; do
    for v in yellowfin albacore skipjack bonito; do
      [ -n "$(_select "$g" "$v")" ] && count=$((count + 1))
    done
  done
  # 4 variants x 5 desktops = 20, minus exactly one: skipjack has no
  # xfce-nvidia. Asserted as a number, counted rather than estimated, so a
  # config edit that silently drops a variant's ISOs is caught.
  [ "$count" -eq 19 ]
}

# ── Recipe JSON & Live-Customize Wrappers ───────────────────────────────────

_run_inert_group() {
  local variant="$1" group="$2" repo="${3:-ghcr}"
  local tmp_dir="${BATS_TEST_TMPDIR}/group-${variant}-${group:-default}-${repo}"
  mkdir -p "${tmp_dir}/bin" "${tmp_dir}/out"
  cat >"${tmp_dir}/bin/podman" <<'EOF'
#!/bin/sh
if [ "$1" = "image" ] && [ "$2" = "exists" ]; then exit 0; fi
if [ "$1" = "pull" ]; then exit 0; fi
case "$*" in
  *"build"*"--iso"*)
    for arg in "$@"; do
      if [ "$prev" = "--iso" ]; then
        mkdir -p "$(dirname "$arg")"
        touch "$arg"
      fi
      prev="$arg"
    done
    exit 0
    ;;
  *"VERSION_ID"*) echo "10.0"; exit 0 ;;
  *"uname -m"*) echo "x86_64"; exit 0 ;;
esac
exit 0
EOF
  chmod +x "${tmp_dir}/bin/podman"
  local out_iso="${tmp_dir}/test.iso"

  PATH="${tmp_dir}/bin:${PATH}" \
  TUNAOS_ISO_OUT_BASE="${tmp_dir}/out" \
  TUNAOS_ALLOW_UNPRIVILEGED=1 \
  TUNAOS_FINAL_ISO="${out_iso}" \
  "${REPO_ROOT}/scripts/build-iso-group.sh" "$variant" "$group" "$repo"
}

@test "recipe: combined recipe is valid dedup JSON with one env per flavor" {
  local envs="[]" ref
  for flavor in gnome-nvidia gnome-nvidia-hwe; do
    ref="$(tunaos_image_ref yellowfin "$flavor" ghcr "$flavor")"
    envs="$(jq -c --arg id "yellowfin-$flavor" --arg image "$ref" \
      --arg title "$(tunaos_flavor_title "$flavor")" \
      --arg desktop "$(tunaos_flavor_desktop "$flavor")" \
      '. + [{id:$id,image:$image,title:$title,desktop:$desktop,modes:["live"]}]' <<<"$envs")"
  done
  recipe="$(jq -n --arg m "TunaOS Yellowfin" --argjson e "$envs" \
    '{media_name:$m, shared_store:{dedup:true,compression:"release",prune_source_images:true}, bootable_environments:$e}')"
  [ "$(echo "$recipe" | jq -r '.shared_store.dedup')" = "true" ]
  [ "$(echo "$recipe" | jq -r '.shared_store.prune_source_images')" = "true" ]
  [ "$(echo "$recipe" | jq -r '.bootable_environments | length')" = "2" ]
  [ "$(echo "$recipe" | jq -r '.bootable_environments[0].title')" = "GNOME (NVIDIA)" ]
  [ "$(echo "$recipe" | jq -r '.bootable_environments[1].image')" = "ghcr.io/tuna-os/yellowfin:gnome-nvidia-hwe" ]
}

@test "grouped packaging builds dedup recipe with live_customize wrappers and matching store refs (ghcr)" {
  run _run_inert_group yellowfin default ghcr
  [ "$status" -eq 0 ]
  local recipe="${BATS_TEST_TMPDIR}/group-yellowfin-default-ghcr/out/yellowfin/recipe.json"
  [ -f "$recipe" ]
  [ "$(jq -r '.shared_store.dedup' "$recipe")" = "true" ]
  [ "$(jq -r '.shared_store.prune_source_images' "$recipe")" = "true" ]

  local env_count
  env_count="$(jq '.bootable_environments | length' "$recipe")"
  [ "$env_count" -ge 1 ]

  for ((i = 0; i < env_count; i++)); do
    local img wrapper
    img="$(jq -r ".bootable_environments[$i].image" "$recipe")"
    wrapper="$(jq -r ".bootable_environments[$i].live_customize[0]" "$recipe")"

    [ -f "$wrapper" ]
    [ -x "$wrapper" ]
    grep -qF "echo 'export TUNA_SESSION_ROOT=/'" "${REPO_ROOT}/scripts/build-iso-group.sh"
    grep -q "export TUNA_SESSION_ROOT=/" "$wrapper"
    grep -q "export TUNA_LIVE_PAYLOAD_REF=${img}" "$wrapper"
    grep -q "customize-live-real.sh" "$wrapper"

    # Assert store correspondence: the wrapper payload ref exists in offline_payloads
    run jq -e --arg img "$img" '.offline_payloads | index($img) != null' "$recipe"
    [ "$status" -eq 0 ]
  done
}

@test "grouped packaging preserves local source refs across wrapper and recipe (local)" {
  run _run_inert_group yellowfin default local
  [ "$status" -eq 0 ]
  local recipe="${BATS_TEST_TMPDIR}/group-yellowfin-default-local/out/yellowfin/recipe.json"
  [ -f "$recipe" ]

  local env_count
  env_count="$(jq '.bootable_environments | length' "$recipe")"
  [ "$env_count" -ge 1 ]

  for ((i = 0; i < env_count; i++)); do
    local img wrapper
    img="$(jq -r ".bootable_environments[$i].image" "$recipe")"
    wrapper="$(jq -r ".bootable_environments[$i].live_customize[0]" "$recipe")"

    [[ "$img" == localhost/* ]]
    [ -f "$wrapper" ]
    [ -x "$wrapper" ]
    grep -q "export TUNA_LIVE_PAYLOAD_REF=${img}" "$wrapper"

    # Assert store correspondence: local image ref matches offline_payloads exactly
    run jq -e --arg img "$img" '.offline_payloads | index($img) != null' "$recipe"
    [ "$status" -eq 0 ]
  done
}

@test "grouped wrapper executes directly and propagates store identity and environment at invocation boundary" {
  run _run_inert_group yellowfin default ghcr
  [ "$status" -eq 0 ]
  local recipe_dir="${BATS_TEST_TMPDIR}/group-yellowfin-default-ghcr/out/yellowfin"
  local wrapper="${recipe_dir}/live-customize/gnome-nvidia/customize-live.sh"
  local real_script="${recipe_dir}/live-customize/gnome-nvidia/customize-live-real.sh"
  [ -x "$wrapper" ]

  # Instrument the downstream customize-live-real boundary to record invocation state
  local probe_log="${BATS_TEST_TMPDIR}/wrapper-boundary.log"
  local test_recipe="${BATS_TEST_TMPDIR}/test-rewrite-recipe.json"
  printf '{"imgref":"ghcr.io/tuna-os/yellowfin:gnome-nvidia"}\n' >"$test_recipe"

  cat >"$real_script" <<'SPYEOF'
#!/usr/bin/env bash
set -euo pipefail
printf "SESSION_ROOT=%s\nPAYLOAD_REF=%s\nARGS=%s\n" \
  "${TUNA_SESSION_ROOT:-unset}" \
  "${TUNA_LIVE_PAYLOAD_REF:-unset}" \
  "$*" >>"${PROBE_LOG}"
if [[ -n "${TEST_RECIPE:-}" && -f "${TEST_RECIPE}" ]]; then
  python3 - "${TEST_RECIPE}" "${TUNA_LIVE_PAYLOAD_REF}" <<'PYEOF'
import json, sys
path, payload_ref = sys.argv[1:3]
with open(path) as f:
    recipe = json.load(f)
recipe["local_imgref"] = f"containers-storage:{payload_ref}"
with open(path, "w") as f:
    json.dump(recipe, f, indent=2)
PYEOF
fi
exit 0
SPYEOF
  chmod +x "$real_script"

  # Invoke the generated wrapper script itself under the test harness
  run env PROBE_LOG="$probe_log" TEST_RECIPE="$test_recipe" \
    "$wrapper" --install --offline-mode
  [ "$status" -eq 0 ]

  # Assert environment and argument propagation across the wrapper boundary
  run cat "$probe_log"
  [ "$status" -eq 0 ]
  [[ "$output" == *"SESSION_ROOT=/"* ]]
  [[ "$output" == *"PAYLOAD_REF=ghcr.io/tuna-os/yellowfin:gnome-nvidia"* ]]
  [[ "$output" == *"ARGS=--install --offline-mode"* ]]

  # Assert the store identity propagated by the wrapper bound local_imgref in the recipe
  run jq -r '.imgref, .local_imgref' "$test_recipe"
  [ "$output" = $'ghcr.io/tuna-os/yellowfin:gnome-nvidia\ncontainers-storage:ghcr.io/tuna-os/yellowfin:gnome-nvidia' ]
  run jq -e '.local_imgref == "containers-storage:ghcr.io/tuna-os/yellowfin:gnome-nvidia"' "$test_recipe"
  [ "$status" -eq 0 ]
}
