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
  # shellcheck source=../../scripts/lib/common.sh
  . "${REPO_ROOT}/scripts/lib/common.sh"
}

# ── Title mapping ───────────────────────────────────────────────────────────

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

@test "config: iso_groups defines flagship, community" {
  json="$(yq -o=json '.' "$CONFIG")"
  suffixes="$(echo "$json" | jq -r '[.iso_groups[].suffix // ""] | sort | join(",")')"
  [ "$suffixes" = ",community" ]
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

@test "select: yellowfin flagship includes gnome-nvidia + hwe" {
  [ "$(_select '' yellowfin)" = "gnome-nvidia gnome-nvidia-hwe" ]
}

@test "select: bonito flagship shrinks (no gnome-nvidia-hwe on Fedora)" {
  [ "$(_select '' bonito)" = "gnome-nvidia" ]
}

@test "select: bonito community resolves to nvidia desktops" {
  [ "$(_select community bonito)" = "kde-nvidia cosmic-nvidia niri-nvidia xfce-nvidia" ]
}

@test "select: grand total is 8 grouped ISOs across 4 variants" {
  local count=0
  for g in '' community; do
    for v in yellowfin albacore skipjack bonito; do
      [ -n "$(_select "$g" "$v")" ] && count=$((count + 1))
    done
  done
  [ "$count" -eq 8 ]
}

# ── Recipe JSON ─────────────────────────────────────────────────────────────

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
