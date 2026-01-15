#!/bin/bash
set -e

if ! command -v act &> /dev/null; then
    echo "Error: 'act' is not installed."
    exit 1
fi

if ! command -v yq &> /dev/null; then
    echo "Error: 'yq' is not installed."
    echo "Install with: brew install yq (macOS) or snap install yq (Linux)"
    exit 1
fi

if [ ! -f secrets.env ]; then
    echo "Warning: secrets.env not found. Copy secrets.env.example to secrets.env and fill it in."
    echo "Running without secrets..."
fi

# Try to get GITHUB_TOKEN from gh cli if not set
if [ -z "$GITHUB_TOKEN" ] && command -v gh &> /dev/null; then
    echo "Fetching GITHUB_TOKEN from gh CLI..."
    GITHUB_TOKEN=$(gh auth token)
    export GITHUB_TOKEN
fi

if [ -z "$GITHUB_TOKEN" ] && ! grep -q "GITHUB_TOKEN" secrets.env 2>/dev/null; then
    echo "Warning: GITHUB_TOKEN not found in environment or secrets.env."
    echo "act may fail to clone actions. Please set GITHUB_TOKEN."
fi

# Function to create local-friendly workflow
transform_workflow() {
    local workflow=$1
    local output=$2
    
    echo "Transforming $workflow for local testing..."
    
    # Use yq to modify the workflow for local testing
    yq eval '
        # Change registry to localhost:5000
        .env.REGISTRY = "localhost:5000" |
        # Remove ghcr.io login steps (add if: false)
        (.jobs.*.steps[] | select(.name == "Log in to GitHub Container Registry") | .if) = "false" |
        # Change runs-on from self-hosted to ubuntu-latest for act
        (.jobs.*.runs-on | select(type == "!!seq")) = "catthehacker/ubuntu:full-latest"
    ' "$workflow" > "$output"
}

# Function to add workflow_dispatch to reusable workflows for act compatibility
add_workflow_dispatch() {
    local workflow_file=$1
    
    # Check if this is a reusable workflow (has workflow_call but no workflow_dispatch)
    if grep -q "workflow_call:" "$workflow_file" && ! grep -q "workflow_dispatch:" "$workflow_file"; then
        echo "Adding workflow_dispatch trigger for act compatibility..."
        
        # Use yq to duplicate workflow_call inputs as workflow_dispatch inputs
        yq eval -i '
            .on.workflow_dispatch.inputs = .on.workflow_call.inputs
        ' "$workflow_file"
    fi
}


if [ -n "$1" ]; then
    choice=$1
else
    echo "Available workflows:"
    echo "1. Build Weekly Images (build-next.yml)"
    echo "2. Build PR/Main (build.yml)"
    echo "3. Run Full Build Pipeline (build all variants)"
    read -r -p "Select workflow to run (1-3): " choice
fi

# Create temp directory for transformed workflows
TMP_DIR=$(mktemp -d)
trap 'rm -rf $TMP_DIR' EXIT

case $choice in
    1)
        echo "Running Build Weekly Images..."
        transform_workflow ".github/workflows/build-next.yml" "$TMP_DIR/build-next.yml"
        act -W "$TMP_DIR/build-next.yml" \
            --secret-file secrets.env \
            -s GITHUB_TOKEN="$GITHUB_TOKEN" \
            --network host \
            --container-options "--privileged"
        ;;
    2)
        echo "Running Build PR/Main..."
        transform_workflow ".github/workflows/build.yml" "$TMP_DIR/build.yml"
        act -W "$TMP_DIR/build.yml" \
            --secret-file secrets.env \
            -s GITHUB_TOKEN="$GITHUB_TOKEN" \
            --network host \
            --container-options "--privileged"
        ;;
    3)
        echo "Running Full Build Pipeline..."
        echo "This will build all image variants and flavors"
        echo ""
        
        # Accept variant and flavor as arguments, or prompt if not provided
        if [ -n "$2" ]; then
            variant=$2
        else
            read -r -p "Enter image variant (yellowfin/albacore): " variant
        fi
        
        if [ -n "$3" ]; then
            flavor=$3
        else
            read -r -p "Enter flavor (base/dx/gdx): " flavor
        fi
        
        # Determine image name
        if [ "$flavor" != "base" ]; then
            IMAGE_NAME="${variant}-${flavor}"
        else
            IMAGE_NAME="${variant}"
        fi
        
        echo ""
        echo "=== Pipeline Configuration ==="
        echo "Variant: $variant"
        echo "Flavor: $flavor"
        echo "Image: $IMAGE_NAME"
        echo "Registry: localhost:5000"
        echo "============================="
        echo ""
        
        # Build the image
        echo "Building image..."
        transform_workflow ".github/workflows/reusable-build-image.yml" "$TMP_DIR/reusable-build-image.yml"
        
        # Add workflow_dispatch trigger for act (keeps production YAML pristine)
        add_workflow_dispatch "$TMP_DIR/reusable-build-image.yml"
        
        # Determine image description based on variant
        case "$variant" in
            yellowfin)
                IMAGE_DESC="🐠 Based on AlmaLinux Kitten 10"
                ;;
            albacore)
                IMAGE_DESC="🐟 Based on AlmaLinux 10"
                ;;
        esac
        
        # Add flavor to description
        case "$flavor" in
            dx) IMAGE_DESC="${IMAGE_DESC} DX" ;;
            gdx) IMAGE_DESC="${IMAGE_DESC} GDX" ;;
        esac
        
        echo "Building: image=$IMAGE_NAME, variant=$variant, flavor=$flavor"
        echo "Registry: localhost:5000, Tag: latest"
        echo ""
        
        # Call the reusable workflow directly - same code path as production!
        act workflow_dispatch \
            -W "$TMP_DIR/reusable-build-image.yml" \
            --secret-file secrets.env \
            -s GITHUB_TOKEN="$GITHUB_TOKEN" \
            --network host \
            --container-options "--privileged" \
            --input image-name="$IMAGE_NAME" \
            --input image-desc="$IMAGE_DESC" \
            --input image-variant="$variant" \
            --input flavor="$flavor" \
            --input platforms="linux/amd64" \
            --input default-tag="latest" \
            --input rechunk="false" \
            --input sbom="false" \
            --input cleanup_runner="false" \
            --input publish="true" || { echo "Build failed!"; exit 1; }
        
        echo ""
        echo "============================="
        echo "✅ Build completed successfully!"
        echo "============================="
        echo ""
        echo "Image created:"
        echo "  localhost:5000/${IMAGE_NAME}:latest"
        echo ""
        echo "Verify with: podman images | grep ${IMAGE_NAME}"
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac
