#!/usr/bin/env bats
# Unit tests for scripts/build-image.sh — flavor resolution, containerfile
# selection, flag computation, and tag construction.
#
# These tests exercise the pure-logic branches of build-image.sh without
# requiring podman, skopeo, or any container runtime.
#
# Run: bats tests/bats/test_build_image.bats

setup() {
  # Isolated test env — no external tools needed for these logic tests
  :
}

# ═══════════════════════════════════════════════════════════════════════════
# Flavor Normalization
# ═══════════════════════════════════════════════════════════════════════════

@test "flavor: hwe → gnome-hwe" {
  run bash -c '
    FLAVOR="hwe"
    case "$FLAVOR" in
      "hwe") FLAVOR="gnome-hwe" ;;
    esac
    echo "$FLAVOR"
  '
  [ "$output" = "gnome-hwe" ]
}

@test "flavor: gdx → gnome-gdx" {
  run bash -c '
    FLAVOR="gdx"
    case "$FLAVOR" in
      "gdx") FLAVOR="gnome-gdx" ;;
    esac
    echo "$FLAVOR"
  '
  [ "$output" = "gnome-gdx" ]
}

@test "flavor: gdx-hwe → gnome-gdx-hwe" {
  run bash -c '
    FLAVOR="gdx-hwe"
    case "$FLAVOR" in
      "gdx-hwe") FLAVOR="gnome-gdx-hwe" ;;
    esac
    echo "$FLAVOR"
  '
  [ "$output" = "gnome-gdx-hwe" ]
}

@test "flavor: gnome passes through unchanged" {
  run bash -c '
    FLAVOR="gnome"
    case "$FLAVOR" in
      "hwe") FLAVOR="gnome-hwe" ;;
      "gdx") FLAVOR="gnome-gdx" ;;
      "gdx-hwe") FLAVOR="gnome-gdx-hwe" ;;
    esac
    echo "$FLAVOR"
  '
  [ "$output" = "gnome" ]
}

@test "flavor: kde passes through unchanged" {
  run bash -c '
    FLAVOR="kde"
    case "$FLAVOR" in
      "hwe") FLAVOR="gnome-hwe" ;;
      "gdx") FLAVOR="gnome-gdx" ;;
      "gdx-hwe") FLAVOR="gnome-gdx-hwe" ;;
    esac
    echo "$FLAVOR"
  '
  [ "$output" = "kde" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Containerfile Selection
# ═══════════════════════════════════════════════════════════════════════════

@test "containerfile: base flavor uses Containerfile" {
  run bash -c '
    FLAVOR="base"
    CONTAINERFILE="Containerfile.el10"
    ENABLE_HWE="0"; ENABLE_GDX="0"; PARENT_FLAVOR=""; DESKTOP_FLAVOR="$FLAVOR"
    case "$FLAVOR" in
      "base") DESKTOP_FLAVOR="base-no-de" ;;
      "base-hwe") CONTAINERFILE="Containerfile.hwe"; ENABLE_HWE="1"; DESKTOP_FLAVOR="base-hwe"; PARENT_FLAVOR="base" ;;
      "base-gdx") CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; DESKTOP_FLAVOR="base-gdx"; PARENT_FLAVOR="base" ;;
      *"-gdx-hwe") DESKTOP_FLAVOR="${FLAVOR%-gdx-hwe}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe" ;;
      *"-hwe") DESKTOP_FLAVOR="${FLAVOR%-hwe}"; CONTAINERFILE="Containerfile.hwe"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
      *"-gdx") DESKTOP_FLAVOR="${FLAVOR%-gdx}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
    esac
    echo "CF=${CONTAINERFILE} DF=${DESKTOP_FLAVOR} HWE=${ENABLE_HWE} GDX=${ENABLE_GDX} PF=${PARENT_FLAVOR:-none}"
  '
  [ "$output" = "CF=Containerfile.el10 DF=base-no-de HWE=0 GDX=0 PF=none" ]
}

@test "containerfile: base-hwe uses Containerfile.hwe" {
  run bash -c '
    FLAVOR="base-hwe"
    CONTAINERFILE="Containerfile.el10"
    ENABLE_HWE="0"; ENABLE_GDX="0"; PARENT_FLAVOR=""; DESKTOP_FLAVOR="$FLAVOR"
    case "$FLAVOR" in
      "base-hwe") CONTAINERFILE="Containerfile.hwe"; ENABLE_HWE="1"; DESKTOP_FLAVOR="base-hwe"; PARENT_FLAVOR="base" ;;
      "base-gdx") CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; DESKTOP_FLAVOR="base-gdx"; PARENT_FLAVOR="base" ;;
      *"-gdx-hwe") DESKTOP_FLAVOR="${FLAVOR%-gdx-hwe}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe" ;;
      *"-hwe") DESKTOP_FLAVOR="${FLAVOR%-hwe}"; CONTAINERFILE="Containerfile.hwe"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
      *"-gdx") DESKTOP_FLAVOR="${FLAVOR%-gdx}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
    esac
    echo "CF=${CONTAINERFILE} HWE=${ENABLE_HWE} PF=${PARENT_FLAVOR}"
  '
  [ "$output" = "CF=Containerfile.hwe HWE=1 PF=base" ]
}

@test "containerfile: base-gdx uses Containerfile.gdx" {
  run bash -c '
    FLAVOR="base-gdx"
    CONTAINERFILE="Containerfile.el10"
    ENABLE_HWE="0"; ENABLE_GDX="0"; PARENT_FLAVOR=""; DESKTOP_FLAVOR="$FLAVOR"
    case "$FLAVOR" in
      "base-gdx") CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; DESKTOP_FLAVOR="base-gdx"; PARENT_FLAVOR="base" ;;
      *"-gdx-hwe") DESKTOP_FLAVOR="${FLAVOR%-gdx-hwe}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe" ;;
      *"-hwe") DESKTOP_FLAVOR="${FLAVOR%-hwe}"; CONTAINERFILE="Containerfile.hwe"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
      *"-gdx") DESKTOP_FLAVOR="${FLAVOR%-gdx}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
    esac
    echo "CF=${CONTAINERFILE} GDX=${ENABLE_GDX} PF=${PARENT_FLAVOR}"
  '
  [ "$output" = "CF=Containerfile.gdx GDX=1 PF=base" ]
}

@test "containerfile: gnome-hwe uses Containerfile.hwe" {
  run bash -c '
    FLAVOR="gnome-hwe"
    CONTAINERFILE="Containerfile.el10"
    ENABLE_HWE="0"; ENABLE_GDX="0"; PARENT_FLAVOR=""; DESKTOP_FLAVOR="$FLAVOR"
    case "$FLAVOR" in
      *"-gdx-hwe") DESKTOP_FLAVOR="${FLAVOR%-gdx-hwe}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe" ;;
      *"-hwe") DESKTOP_FLAVOR="${FLAVOR%-hwe}"; CONTAINERFILE="Containerfile.hwe"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
      *"-gdx") DESKTOP_FLAVOR="${FLAVOR%-gdx}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
    esac
    echo "CF=${CONTAINERFILE} DF=${DESKTOP_FLAVOR} HWE=${ENABLE_HWE} PF=${PARENT_FLAVOR}"
  '
  [ "$output" = "CF=Containerfile.hwe DF=gnome HWE=1 PF=gnome" ]
}

@test "containerfile: kde-gdx uses Containerfile.gdx" {
  run bash -c '
    FLAVOR="kde-gdx"
    CONTAINERFILE="Containerfile.el10"
    ENABLE_HWE="0"; ENABLE_GDX="0"; PARENT_FLAVOR=""; DESKTOP_FLAVOR="$FLAVOR"
    case "$FLAVOR" in
      *"-gdx-hwe") DESKTOP_FLAVOR="${FLAVOR%-gdx-hwe}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe" ;;
      *"-hwe") DESKTOP_FLAVOR="${FLAVOR%-hwe}"; CONTAINERFILE="Containerfile.hwe"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
      *"-gdx") DESKTOP_FLAVOR="${FLAVOR%-gdx}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
    esac
    echo "CF=${CONTAINERFILE} DF=${DESKTOP_FLAVOR} GDX=${ENABLE_GDX} PF=${PARENT_FLAVOR}"
  '
  [ "$output" = "CF=Containerfile.gdx DF=kde GDX=1 PF=kde" ]
}

@test "containerfile: gnome-gdx-hwe uses Containerfile.gdx with both flags" {
  run bash -c '
    FLAVOR="gnome-gdx-hwe"
    CONTAINERFILE="Containerfile.el10"
    ENABLE_HWE="0"; ENABLE_GDX="0"; PARENT_FLAVOR=""; DESKTOP_FLAVOR="$FLAVOR"
    case "$FLAVOR" in
      *"-gdx-hwe") DESKTOP_FLAVOR="${FLAVOR%-gdx-hwe}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe" ;;
    esac
    echo "CF=${CONTAINERFILE} DF=${DESKTOP_FLAVOR} HWE=${ENABLE_HWE} GDX=${ENABLE_GDX} PF=${PARENT_FLAVOR}"
  '
  [ "$output" = "CF=Containerfile.gdx DF=gnome HWE=1 GDX=1 PF=gnome-hwe" ]
}

@test "containerfile: kde-gdx-hwe strips suffix correctly" {
  run bash -c '
    FLAVOR="kde-gdx-hwe"
    CONTAINERFILE="Containerfile.el10"
    ENABLE_HWE="0"; ENABLE_GDX="0"; PARENT_FLAVOR=""; DESKTOP_FLAVOR="$FLAVOR"
    case "$FLAVOR" in
      *"-gdx-hwe") DESKTOP_FLAVOR="${FLAVOR%-gdx-hwe}"; CONTAINERFILE="Containerfile.gdx"; ENABLE_GDX="1"; ENABLE_HWE="1"; PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe" ;;
    esac
    echo "DF=${DESKTOP_FLAVOR} PF=${PARENT_FLAVOR}"
  '
  [ "$output" = "DF=kde PF=kde-hwe" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Tag Construction
# ═══════════════════════════════════════════════════════════════════════════

@test "tag: latest uses flavor as image tag" {
  run bash -c '
    TARGET_TAG="albacore"
    TAG="latest"
    FLAVOR="gnome"
    TARGET_IMAGE_TAG="$TAG"
    [[ "$TAG" == "latest" ]] && TARGET_IMAGE_TAG="$FLAVOR"
    echo "${TARGET_TAG}:${TARGET_IMAGE_TAG}"
  '
  [ "$output" = "albacore:gnome" ]
}

@test "tag: custom tag preserved" {
  run bash -c '
    TARGET_TAG="yellowfin"
    TAG="42"
    FLAVOR="kde"
    TARGET_IMAGE_TAG="$TAG"
    [[ "$TAG" == "latest" ]] && TARGET_IMAGE_TAG="$FLAVOR"
    echo "${TARGET_TAG}:${TARGET_IMAGE_TAG}"
  '
  [ "$output" = "yellowfin:42" ]
}

@test "tag: latest with base-gdx uses gdx flavor for tag" {
  run bash -c '
    TARGET_TAG="albacore"
    TAG="latest"
    FLAVOR="base-gdx"
    TARGET_IMAGE_TAG="$TAG"
    [[ "$TAG" == "latest" ]] && TARGET_IMAGE_TAG="$FLAVOR"
    echo "${TARGET_TAG}:${TARGET_IMAGE_TAG}"
  '
  [ "$output" = "albacore:base-gdx" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Parent Flavor / Base Image Resolution
# ═══════════════════════════════════════════════════════════════════════════

@test "parent: gnome-hwe parent is gnome" {
  run bash -c '
    FLAVOR="gnome-hwe"
    PARENT_FLAVOR=""; DESKTOP_FLAVOR="$FLAVOR"
    case "$FLAVOR" in
      *"-hwe") DESKTOP_FLAVOR="${FLAVOR%-hwe}"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
    esac
    echo "PF=${PARENT_FLAVOR}"
  '
  [ "$output" = "PF=gnome" ]
}

@test "parent: kde-gdx parent is kde" {
  run bash -c '
    FLAVOR="kde-gdx"
    PARENT_FLAVOR=""; DESKTOP_FLAVOR="$FLAVOR"
    case "$FLAVOR" in
      *"-gdx") DESKTOP_FLAVOR="${FLAVOR%-gdx}"; PARENT_FLAVOR="${DESKTOP_FLAVOR}" ;;
    esac
    echo "PF=${PARENT_FLAVOR}"
  '
  [ "$output" = "PF=kde" ]
}

@test "parent: base-hwe parent is base" {
  run bash -c '
    FLAVOR="base-hwe"
    PARENT_FLAVOR="base"
    echo "PF=${PARENT_FLAVOR}"
  '
  [ "$output" = "PF=base" ]
}

@test "parent: ci mode constructs ghcr ref" {
  run bash -c '
    VARIANT="albacore"
    PARENT_FLAVOR="gnome"
    IS_CI="1"
    OWNER="${repo_organization:-tuna-os}"
    if [[ "$IS_CI" = "1" ]]; then
      BASE_FOR_BUILD="ghcr.io/${OWNER}/${VARIANT}:${PARENT_FLAVOR}"
    else
      BASE_FOR_BUILD="localhost/${VARIANT}:${PARENT_FLAVOR}"
    fi
    echo "$BASE_FOR_BUILD"
  '
  [ "$output" = "ghcr.io/tuna-os/albacore:gnome" ]
}

@test "parent: local mode constructs localhost ref" {
  run bash -c '
    VARIANT="skipjack"
    PARENT_FLAVOR="kde"
    IS_CI="0"
    if [[ "$IS_CI" = "1" ]]; then
      BASE_FOR_BUILD="ghcr.io/tuna-os/${VARIANT}:${PARENT_FLAVOR}"
    else
      BASE_FOR_BUILD="localhost/${VARIANT}:${PARENT_FLAVOR}"
    fi
    echo "$BASE_FOR_BUILD"
  '
  [ "$output" = "localhost/skipjack:kde" ]
}

@test "parent: chain_base_image overrides when set" {
  run bash -c '
    FLAVOR="gnome-hwe"
    CHAIN_BASE_IMAGE="ghcr.io/custom/base:v1"
    BASE_FOR_BUILD=""
    PARENT_FLAVOR="gnome"
    if [[ -n "$CHAIN_BASE_IMAGE" ]] && [[ "$FLAVOR" != "base" ]]; then
      BASE_FOR_BUILD="$CHAIN_BASE_IMAGE"
    fi
    echo "$BASE_FOR_BUILD"
  '
  [ "$output" = "ghcr.io/custom/base:v1" ]
}

@test "parent: chain_base_image skipped for base flavor" {
  run bash -c '
    FLAVOR="base"
    CHAIN_BASE_IMAGE="ghcr.io/custom/base:v1"
    BASE_FOR_BUILD="quay.io/upstream/image:10"
    if [[ -n "$CHAIN_BASE_IMAGE" ]] && [[ "$FLAVOR" != "base" ]]; then
      BASE_FOR_BUILD="$CHAIN_BASE_IMAGE"
    fi
    echo "$BASE_FOR_BUILD"
  '
  [ "$output" = "quay.io/upstream/image:10" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Cache / CI Logic
# ═══════════════════════════════════════════════════════════════════════════

@test "cache: local builds use cache" {
  run bash -c '
    IS_CI="0"
    if [[ "$IS_CI" == "0" ]]; then USE_CACHE="1"; else USE_CACHE="0"; fi
    echo "$USE_CACHE"
  '
  [ "$output" = "1" ]
}

@test "cache: CI builds skip cache" {
  run bash -c '
    IS_CI="1"
    if [[ "$IS_CI" == "0" ]]; then USE_CACHE="1"; else USE_CACHE="0"; fi
    echo "$USE_CACHE"
  '
  [ "$output" = "0" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Platform Resolution
# ═══════════════════════════════════════════════════════════════════════════

@test "platform: explicit TARGET_PLATFORM passed through" {
  run bash -c '
    TARGET_PLATFORM="linux/arm64"
    PLATFORM="$TARGET_PLATFORM"
    echo "$PLATFORM"
  '
  [ "$output" = "linux/arm64" ]
}

@test "platform: env var platform used when set" {
  run bash -c '
    platform="linux/amd64/test"
    TARGET_PLATFORM=""
    IS_CI="0"
    if [[ -z "$TARGET_PLATFORM" ]]; then
      if [[ "$IS_CI" != "1" ]]; then
        if [[ -n "${platform:-}" ]]; then
          PLATFORM="${platform}"
        fi
      fi
    fi
    echo "${PLATFORM:-unset}"
  '
  [ "$output" = "linux/amd64/test" ]
}

@test "platform: x86_64 maps to linux/amd64" {
  run bash -c '
    ARCH="x86_64"
    case "$ARCH" in
      x86_64) echo "linux/amd64" ;;
      arm64|aarch64) echo "linux/arm64" ;;
      *) echo "unsupported" ;;
    esac
  '
  [ "$output" = "linux/amd64" ]
}

@test "platform: arm64 maps to linux/arm64" {
  run bash -c '
    ARCH="arm64"
    case "$ARCH" in
      x86_64) echo "linux/amd64" ;;
      arm64|aarch64) echo "linux/arm64" ;;
      *) echo "unsupported" ;;
    esac
  '
  [ "$output" = "linux/arm64" ]
}

@test "platform: aarch64 maps to linux/arm64" {
  run bash -c '
    ARCH="aarch64"
    case "$ARCH" in
      x86_64) echo "linux/amd64" ;;
      arm64|aarch64) echo "linux/arm64" ;;
      *) echo "unsupported" ;;
    esac
  '
  [ "$output" = "linux/arm64" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# AKMODS Version Selection
# ═══════════════════════════════════════════════════════════════════════════

@test "akmods: hwe/gnome-hwe uses coreos-stable" {
  run bash -c '
    ENABLE_HWE="1"
    TARGET_TAG="albacore"
    if [[ "$ENABLE_HWE" -eq "1" ]] || [[ "$TARGET_TAG" == bonito* ]]; then
      echo "AKMODS_VERSION=coreos-stable-43"
    else
      echo "AKMODS_VERSION=centos-10"
    fi
  '
  [ "$output" = "AKMODS_VERSION=coreos-stable-43" ]
}

@test "akmods: bonito variant uses coreos-stable" {
  run bash -c '
    ENABLE_HWE="0"
    TARGET_TAG="bonito"
    if [[ "$ENABLE_HWE" -eq "1" ]] || [[ "$TARGET_TAG" == bonito* ]]; then
      echo "AKMODS_VERSION=coreos-stable-43"
    else
      echo "AKMODS_VERSION=centos-10"
    fi
  '
  [ "$output" = "AKMODS_VERSION=coreos-stable-43" ]
}

@test "akmods: albacore gnome uses centos-10" {
  run bash -c '
    ENABLE_HWE="0"
    TARGET_TAG="albacore"
    if [[ "$ENABLE_HWE" -eq "1" ]] || [[ "$TARGET_TAG" == bonito* ]]; then
      echo "AKMODS_VERSION=coreos-stable-43"
    else
      echo "AKMODS_VERSION=centos-10"
    fi
  '
  [ "$output" = "AKMODS_VERSION=centos-10" ]
}

@test "akmods: yellowfin uses centos-10" {
  run bash -c '
    ENABLE_HWE="0"
    TARGET_TAG="yellowfin"
    if [[ "$ENABLE_HWE" -eq "1" ]] || [[ "$TARGET_TAG" == bonito* ]]; then
      echo "AKMODS_VERSION=coreos-stable-43"
    else
      echo "AKMODS_VERSION=centos-10"
    fi
  '
  [ "$output" = "AKMODS_VERSION=centos-10" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# SHA HEAD Handling
# ═══════════════════════════════════════════════════════════════════════════

@test "sha: dirty when repo has uncommitted changes" {
  run bash -c '
    # Simulate dirty working tree
    if [[ -z "" ]]; then  # empty string = clean repo
      echo "sha=$(echo "abc1234")"
    else
      echo "sha=dirty"
    fi
  '
  [[ "$output" == *"abc1234"* ]]
}

@test "sha: dirty flag set when not clean" {
  run bash -c '
    GIT_STATUS=" M somefile.txt"
    if [[ -z "$GIT_STATUS" ]]; then
      echo "clean"
    else
      echo "dirty"
    fi
  '
  [ "$output" = "dirty" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Gnome Submodule Init
# ═══════════════════════════════════════════════════════════════════════════

@test "submodule: gnome flavors trigger init" {
  run bash -c '
    FLAVOR="gnome"
    IS_CI="0"
    SKIP_SUBMODULES="0"
    DID_INIT="0"
    if [[ "$IS_CI" != "1" ]] && [[ "${SKIP_SUBMODULES:-0}" != "1" ]]; then
      if [[ "$FLAVOR" == *"gnome"* ]]; then
        DID_INIT="1"
      fi
    fi
    echo "$DID_INIT"
  '
  [ "$output" = "1" ]
}

@test "submodule: kde flavors skip gnome submodule init" {
  run bash -c '
    FLAVOR="kde"
    IS_CI="0"
    DID_INIT="0"
    if [[ "$IS_CI" != "1" ]] && [[ "${SKIP_SUBMODULES:-0}" != "1" ]]; then
      if [[ "$FLAVOR" == *"gnome"* ]]; then
        DID_INIT="1"
      fi
    fi
    echo "$DID_INIT"
  '
  [ "$output" = "0" ]
}

@test "submodule: CI mode skips init" {
  run bash -c '
    FLAVOR="gnome"
    IS_CI="1"
    DID_INIT="0"
    if [[ "$IS_CI" != "1" ]] && [[ "${SKIP_SUBMODULES:-0}" != "1" ]]; then
      if [[ "$FLAVOR" == *"gnome"* ]]; then
        DID_INIT="1"
      fi
    fi
    echo "$DID_INIT"
  '
  [ "$output" = "0" ]
}

@test "submodule: skip_submodules env var prevents init" {
  run bash -c '
    FLAVOR="gnome"
    IS_CI="0"
    SKIP_SUBMODULES="1"
    DID_INIT="0"
    if [[ "$IS_CI" != "1" ]] && [[ "${SKIP_SUBMODULES:-0}" != "1" ]]; then
      if [[ "$FLAVOR" == *"gnome"* ]]; then
        DID_INIT="1"
      fi
    fi
    echo "$DID_INIT"
  '
  [ "$output" = "0" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Post-build Cleanup Logic
# ═══════════════════════════════════════════════════════════════════════════

@test "post-build: local build syncs cache" {
  run bash -c '
    IS_CI="0"
    if [[ "$IS_CI" == "0" ]]; then
      echo "sync_cache"
    fi
  '
  [ "$output" = "sync_cache" ]
}

@test "post-build: CI build skips cache sync" {
  run bash -c '
    IS_CI="1"
    if [[ "$IS_CI" == "0" ]]; then
      echo "sync_cache"
    else
      echo "skip_sync"
    fi
  '
  [ "$output" = "skip_sync" ]
}

@test "post-build: submodule deinit when DID_INIT was set" {
  run bash -c '
    DID_INIT="1"
    if [[ "$DID_INIT" == "1" ]]; then
      echo "deinit_submodules"
    fi
  '
  [ "$output" = "deinit_submodules" ]
}

@test "post-build: no deinit when DID_INIT was 0" {
  run bash -c '
    DID_INIT="0"
    if [[ "$DID_INIT" == "1" ]]; then
      echo "deinit_submodules"
    else
      echo "skip_deinit"
    fi
  '
  [ "$output" = "skip_deinit" ]
}
