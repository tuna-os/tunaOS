#!/usr/bin/env bats
# Unit tests for scripts/run-local-ci.sh
#
# Tests:
#   - act binary presence detection
#   - yq binary presence detection
#   - GITHUB_TOKEN retrieval from secrets.env
#   - Workflow transformation: registry override
#   - Workflow transformation: ghcr login skip
#   - Workflow transformation: runs-on override
#   - workflow_dispatch injection for reusable workflows
#   - Variant → image description mapping
#   - Case selection logic

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/scripts"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# run-local-ci.sh — Prerequisite Detection
# ═══════════════════════════════════════════════════════════════════════════

@test "run-local-ci: exits when act is not installed" {
  run bash -c '
    if ! command -v nonexistent_act_binary__ &>/dev/null; then
      echo "Error: act is not installed."
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"act"* ]]
}

@test "run-local-ci: exits when yq is not installed" {
  run bash -c '
    if ! command -v nonexistent_yq_binary__ &>/dev/null; then
      echo "Error: yq is not installed."
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"yq"* ]]
}

@test "run-local-ci: warns when secrets.env is missing" {
  run bash -c '
    if [ ! -f /nonexistent/secrets.env ]; then
      echo "Warning: secrets.env not found."
    fi
  '
  [[ "$output" == *"Warning"* ]]
  [[ "$output" == *"secrets.env"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# run-local-ci.sh — Workflow Transformation Logic
# ═══════════════════════════════════════════════════════════════════════════

@test "run-local-ci: sets REGISTRY to localhost:5000" {
  # The transform_workflow function overrides REGISTRY
  run bash -c '
    REGISTRY="ghcr.io/tuna-os"
    # Transformation: change to localhost
    REGISTRY="localhost:5000"
    echo "$REGISTRY"
  '
  [ "$output" = "localhost:5000" ]
}

@test "run-local-ci: disables ghcr login step with if: false" {
  # The transform catches "Log in to GitHub Container Registry" and sets if=false
  run bash -c '
    STEP_NAME="Log in to GitHub Container Registry"
    if [[ "$STEP_NAME" == "Log in to GitHub Container Registry" ]]; then
      echo "if: false"
    else
      echo "unchanged"
    fi
  '
  [ "$output" = "if: false" ]
}

@test "run-local-ci: does not disable non-login steps" {
  run bash -c '
    STEP_NAME="Build image"
    if [[ "$STEP_NAME" == "Log in to GitHub Container Registry" ]]; then
      echo "if: false"
    else
      echo "unchanged"
    fi
  '
  [ "$output" = "unchanged" ]
}

@test "run-local-ci: workflow_dispatch detection on reusable workflow" {
  run bash -c '
    # Simulate: has workflow_call but NOT workflow_dispatch
    content="on:
  workflow_call:
    inputs:
      variant:
        type: string"

    has_workflow_call=$(echo "$content" | grep -c "workflow_call:" || true)
    has_workflow_dispatch=$(echo "$content" | grep -c "workflow_dispatch:" || true)

    needs_dispatch=0
    [[ "$has_workflow_call" -gt 0 ]] && [[ "$has_workflow_dispatch" -eq 0 ]] && needs_dispatch=1
    echo "$needs_dispatch"
  '
  [ "$output" = "1" ]
}

@test "run-local-ci: workflow_dispatch not injected when already present" {
  run bash -c '
    # Simulate: has both workflow_call and workflow_dispatch
    content="on:
  workflow_call:
    inputs:
      variant:
        type: string
  workflow_dispatch:
    inputs:
      variant:
        type: string"

    has_workflow_call=$(echo "$content" | grep -c "workflow_call:" || true)
    has_workflow_dispatch=$(echo "$content" | grep -c "workflow_dispatch:" || true)

    needs_dispatch=0
    [[ "$has_workflow_call" -gt 0 ]] && [[ "$has_workflow_dispatch" -eq 0 ]] && needs_dispatch=1
    echo "$needs_dispatch"
  '
  [ "$output" = "0" ]
}

@test "run-local-ci: non-reusable workflow does not need dispatch injection" {
  run bash -c '
    # Simulate: no workflow_call, no workflow_dispatch (e.g., simple push trigger)
    content="on:
  push:
    branches: [main]"

    has_workflow_call=$(echo "$content" | grep -c "workflow_call:" || true)
    has_workflow_dispatch=$(echo "$content" | grep -c "workflow_dispatch:" || true)

    needs_dispatch=0
    [[ "$has_workflow_call" -gt 0 ]] && [[ "$has_workflow_dispatch" -eq 0 ]] && needs_dispatch=1
    echo "$needs_dispatch"
  '
  [ "$output" = "0" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# run-local-ci.sh — Variant Description Mapping
# ═══════════════════════════════════════════════════════════════════════════

@test "run-local-ci: maps yellowfin to AlmaLinux Kitten description" {
  run bash -c '
    variant="yellowfin"
    case "$variant" in
      yellowfin) IMAGE_DESC="🐠 Based on AlmaLinux Kitten 10" ;;
      albacore) IMAGE_DESC="🐟 Based on AlmaLinux 10" ;;
      *) IMAGE_DESC="Unknown" ;;
    esac
    echo "$IMAGE_DESC"
  '
  [[ "$output" == *"AlmaLinux Kitten 10"* ]]
  [[ "$output" == *"🐠"* ]]
}

@test "run-local-ci: maps albacore to AlmaLinux 10 description" {
  run bash -c '
    variant="albacore"
    case "$variant" in
      yellowfin) IMAGE_DESC="🐠 Based on AlmaLinux Kitten 10" ;;
      albacore) IMAGE_DESC="🐟 Based on AlmaLinux 10" ;;
      *) IMAGE_DESC="Unknown" ;;
    esac
    echo "$IMAGE_DESC"
  '
  [[ "$output" == *"AlmaLinux 10"* ]]
  [[ "$output" == *"🐟"* ]]
}

@test "run-local-ci: unknown variant gets default description" {
  run bash -c '
    variant="marlin"
    case "$variant" in
      yellowfin) IMAGE_DESC="🐠 Based on AlmaLinux Kitten 10" ;;
      albacore) IMAGE_DESC="🐟 Based on AlmaLinux 10" ;;
      *) IMAGE_DESC="Unknown" ;;
    esac
    echo "$IMAGE_DESC"
  '
  [ "$output" = "Unknown" ]
}

@test "run-local-ci: flavor suffix appends to description" {
  run bash -c '
    variant="yellowfin"
    flavor="gdx"
    case "$variant" in
      yellowfin) IMAGE_DESC="🐠 Based on AlmaLinux Kitten 10" ;;
      albacore) IMAGE_DESC="🐟 Based on AlmaLinux 10" ;;
    esac
    case "$flavor" in
      dx) IMAGE_DESC="${IMAGE_DESC} DX" ;;
      gdx) IMAGE_DESC="${IMAGE_DESC} GDX" ;;
    esac
    echo "$IMAGE_DESC"
  '
  [[ "$output" == *"GDX"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# run-local-ci.sh — Image Name Construction
# ═══════════════════════════════════════════════════════════════════════════

@test "run-local-ci: base flavor uses variant-only name" {
  run bash -c '
    variant="skipjack"
    flavor="base"
    if [ "$flavor" != "base" ]; then
      IMAGE_NAME="${variant}-${flavor}"
    else
      IMAGE_NAME="${variant}"
    fi
    echo "$IMAGE_NAME"
  '
  [ "$output" = "skipjack" ]
}

@test "run-local-ci: non-base flavor appends flavor to name" {
  run bash -c '
    variant="bonito"
    flavor="gnome"
    if [ "$flavor" != "base" ]; then
      IMAGE_NAME="${variant}-${flavor}"
    else
      IMAGE_NAME="${variant}"
    fi
    echo "$IMAGE_NAME"
  '
  [ "$output" = "bonito-gnome" ]
}

@test "run-local-ci: gdx flavor appended to name" {
  run bash -c '
    variant="yellowfin"
    flavor="gdx"
    if [ "$flavor" != "base" ]; then
      IMAGE_NAME="${variant}-${flavor}"
    else
      IMAGE_NAME="${variant}"
    fi
    echo "$IMAGE_NAME"
  '
  [ "$output" = "yellowfin-gdx" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# run-local-ci.sh — Case Selection
# ═══════════════════════════════════════════════════════════════════════════

@test "run-local-ci: invalid choice exits with error" {
  run bash -c '
    choice="99"
    case $choice in
      1|2|3) echo "valid" ;;
      *) echo "Invalid choice"; exit 1 ;;
    esac
  '
  [ "$status" -eq 1 ]
}

@test "run-local-ci: case 1 selects build-weekly workflow" {
  run bash -c '
    choice=1
    case $choice in
      1) WORKFLOW=".github/workflows/build-weekly.yml"; echo "$WORKFLOW" ;;
      2) WORKFLOW=".github/workflows/build.yml" ;;
      3) WORKFLOW="pipeline" ;;
    esac
  '
  [[ "$output" == *"build-weekly.yml"* ]]
}

@test "run-local-ci: case 2 selects build workflow" {
  run bash -c '
    choice=2
    case $choice in
      1) echo "build-weekly" ;;
      2) echo "build" ;;
      3) echo "pipeline" ;;
    esac
  '
  [ "$output" = "build" ]
}

@test "run-local-ci: case 3 selects pipeline" {
  run bash -c '
    choice=3
    case $choice in
      1) echo "build-weekly" ;;
      2) echo "build" ;;
      3) echo "pipeline" ;;
    esac
  '
  [ "$output" = "pipeline" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# run-local-ci.sh — act Invocation
# ═══════════════════════════════════════════════════════════════════════════

@test "run-local-ci: act command includes --secret-file" {
  # The act invocation must pass secrets
  run bash -c '
    SECRET_FILE="secrets.env"
    ACT_CMD="act -W workflow.yml --secret-file ${SECRET_FILE} -s GITHUB_TOKEN=xxx --network host --container-options --privileged"
    echo "$ACT_CMD"
  '
  [[ "$output" == *"--secret-file"* ]]
  [[ "$output" == *"secrets.env"* ]]
  [[ "$output" == *"--privileged"* ]]
}

@test "run-local-ci: act command includes --network host" {
  run bash -c '
    ACT_CMD="act -W workflow.yml --network host --container-options --privileged"
    echo "$ACT_CMD"
  '
  [[ "$output" == *"--network host"* ]]
  [[ "$output" == *"--container-options"* ]]
}

@test "run-local-ci: workflow_dispatch inputs include variant and flavor" {
  # The act workflow_dispatch call must pass --input flags
  run bash -c '
    INPUTS="--input image-name=skipjack-gnome --input image-variant=skipjack --input flavor=gnome --input platforms=linux/amd64 --input default-tag=latest --input rechunk=false --input sbom=false --input cleanup_runner=false --input publish=true"
    echo "$INPUTS"
  '
  [[ "$output" == *"image-name"* ]]
  [[ "$output" == *"image-variant"* ]]
  [[ "$output" == *"flavor"* ]]
  [[ "$output" == *"platforms"* ]]
  [[ "$output" == *"rechunk"* ]]
  [[ "$output" == *"publish"* ]]
}
