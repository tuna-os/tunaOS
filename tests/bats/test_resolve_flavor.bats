#!/usr/bin/env bats
# Test resolve-flavor.sh — the routing brain for all build flavors.

SCRIPT="./scripts/resolve-flavor.sh"

# Helper: run resolve-flavor and extract a specific variable
get_var() {
    local var="$1"; shift
    eval "$("$SCRIPT" "$@")"
    eval "echo \"\$$var\""
}

# ─── Base flavors ─────────────────────────────────────────────────────────────

@test "base → Containerfile, base-no-de target, no parent" {
    eval "$("$SCRIPT" yellowfin base)"
    [[ "$CONTAINERFILE" == "Containerfile.el10" ]]
    [[ "$DESKTOP_FLAVOR" == "base-no-de" ]]
    [[ "$PARENT_FLAVOR" == "" ]]
    [[ "$ENABLE_HWE" == "0" ]]
    [[ "$ENABLE_NVIDIA" == "0" ]]
}

@test "base on grouper → Containerfile.ubuntu, base target" {
    eval "$("$SCRIPT" grouper base)"
    [[ "$CONTAINERFILE" == "Containerfile.ubuntu" ]]
    [[ "$DESKTOP_FLAVOR" == "base" ]]
}

# ─── Plain desktop flavors ────────────────────────────────────────────────────

@test "gnome → Containerfile, gnome target, no parent" {
    eval "$("$SCRIPT" albacore gnome)"
    [[ "$CONTAINERFILE" == "Containerfile.el10" ]]
    [[ "$DESKTOP_FLAVOR" == "gnome" ]]
    [[ "$PARENT_FLAVOR" == "" ]]
}

@test "kde → Containerfile, kde target" {
    eval "$("$SCRIPT" skipjack kde)"
    [[ "$DESKTOP_FLAVOR" == "kde" ]]
    [[ "$CONTAINERFILE" == "Containerfile.el10" ]]
}

@test "niri → Containerfile, niri target" {
    eval "$("$SCRIPT" yellowfin niri)"
    [[ "$DESKTOP_FLAVOR" == "niri" ]]
}

@test "cosmic → Containerfile, cosmic target" {
    eval "$("$SCRIPT" bonito cosmic)"
    [[ "$DESKTOP_FLAVOR" == "cosmic" ]]
}

# ─── HWE flavors ─────────────────────────────────────────────────────────────

@test "base-hwe → overlay, hwe type, parent=base" {
    eval "$("$SCRIPT" yellowfin base-hwe)"
    [[ "$CONTAINERFILE" == "Containerfile.overlay" ]]
    [[ "$OVERLAY_TYPE" == "hwe" ]]
    [[ "$ENABLE_HWE" == "1" ]]
    [[ "$ENABLE_NVIDIA" == "0" ]]
    [[ "$DESKTOP_FLAVOR" == "desktop" ]]
    [[ "$PARENT_FLAVOR" == "base" ]]
}

@test "gnome-hwe → overlay, hwe type, parent=gnome" {
    eval "$("$SCRIPT" albacore gnome-hwe)"
    [[ "$CONTAINERFILE" == "Containerfile.overlay" ]]
    [[ "$OVERLAY_TYPE" == "hwe" ]]
    [[ "$ENABLE_HWE" == "1" ]]
    [[ "$PARENT_FLAVOR" == "gnome" ]]
    [[ "$DESKTOP_FLAVOR" == "desktop" ]]
}

@test "kde-hwe → overlay, parent=kde" {
    eval "$("$SCRIPT" yellowfin kde-hwe)"
    [[ "$PARENT_FLAVOR" == "kde" ]]
    [[ "$OVERLAY_TYPE" == "hwe" ]]
}

# ─── NVIDIA flavors ──────────────────────────────────────────────────────────

@test "base-nvidia → overlay, nvidia type, parent=base" {
    eval "$("$SCRIPT" albacore base-nvidia)"
    [[ "$CONTAINERFILE" == "Containerfile.overlay" ]]
    [[ "$OVERLAY_TYPE" == "nvidia" ]]
    [[ "$ENABLE_NVIDIA" == "1" ]]
    [[ "$ENABLE_HWE" == "0" ]]
    [[ "$PARENT_FLAVOR" == "base" ]]
}

@test "gnome-nvidia → overlay, nvidia type, parent=gnome" {
    eval "$("$SCRIPT" yellowfin gnome-nvidia)"
    [[ "$OVERLAY_TYPE" == "nvidia" ]]
    [[ "$ENABLE_NVIDIA" == "1" ]]
    [[ "$PARENT_FLAVOR" == "gnome" ]]
}

@test "kde-nvidia → overlay, parent=kde" {
    eval "$("$SCRIPT" skipjack kde-nvidia)"
    [[ "$PARENT_FLAVOR" == "kde" ]]
    [[ "$OVERLAY_TYPE" == "nvidia" ]]
}

# ─── Combined nvidia-hwe ─────────────────────────────────────────────────────

@test "gnome-nvidia-hwe → overlay, nvidia type, hwe=1, parent=gnome-hwe" {
    eval "$("$SCRIPT" yellowfin gnome-nvidia-hwe)"
    [[ "$CONTAINERFILE" == "Containerfile.overlay" ]]
    [[ "$OVERLAY_TYPE" == "nvidia" ]]
    [[ "$ENABLE_NVIDIA" == "1" ]]
    [[ "$ENABLE_HWE" == "1" ]]
    [[ "$PARENT_FLAVOR" == "gnome-hwe" ]]
    [[ "$DESKTOP_FLAVOR" == "desktop" ]]
}

# ─── Legacy shorthand normalization ──────────────────────────────────────────

@test "shorthand 'hwe' normalizes to gnome-hwe" {
    eval "$("$SCRIPT" yellowfin hwe)"
    [[ "$FLAVOR" == "gnome-hwe" ]]
    [[ "$PARENT_FLAVOR" == "gnome" ]]
}

@test "shorthand 'nvidia' normalizes to gnome-nvidia" {
    eval "$("$SCRIPT" yellowfin nvidia)"
    [[ "$FLAVOR" == "gnome-nvidia" ]]
    [[ "$PARENT_FLAVOR" == "gnome" ]]
}

@test "shorthand 'gdx-hwe' normalizes to gnome-nvidia-hwe" {
    eval "$("$SCRIPT" yellowfin gdx-hwe)"
    [[ "$FLAVOR" == "gnome-nvidia-hwe" ]]
    [[ "$PARENT_FLAVOR" == "gnome-hwe" ]]
}

# ─── Grouper special cases ───────────────────────────────────────────────────

@test "grouper gnome → Containerfile.ubuntu, gnome target (no overlay)" {
    eval "$("$SCRIPT" grouper gnome)"
    [[ "$CONTAINERFILE" == "Containerfile.ubuntu" ]]
    [[ "$DESKTOP_FLAVOR" == "gnome" ]]
    [[ "$OVERLAY_TYPE" == "" ]]
}

@test "grouper kde-hwe does NOT route to overlay (ubuntu has no HWE layer)" {
    # On grouper, -hwe suffix is treated as a plain flavor name
    eval "$("$SCRIPT" grouper kde-hwe)"
    [[ "$CONTAINERFILE" == "Containerfile.ubuntu" ]]
    [[ "$DESKTOP_FLAVOR" == "kde-hwe" ]]
}
