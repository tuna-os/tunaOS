# --- CI recipes called from workflows: build ---
# Each recipe is a workflow step moved out of YAML so it can be run and tested locally.
# Recipe names are prefixed ci- (just imports share one flat namespace).

# Diff the PR image against the published flavor and write diff_report.md for the PR comment (reads IMAGE_REGISTRY, IMAGE_NAME, DEFAULT_TAG, SAFE_PLATFORM); never fails a green image
ci-pr-diff:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}

    # Only run diff for one platform to avoid spamming comments (e.g., amd64)
    if [[ "${SAFE_PLATFORM}" != *"amd64"* ]]; then
        echo "Skipping diff for non-amd64 platform"
        exit 0
    fi

    # Pull the stable base flavor image (base for comparison)
    # We assume the default tag exists. If not, we might fail or skip.
    # We'll try to pull it, if it fails, we skip diff.
    BASE_IMAGE="${IMAGE_REGISTRY}/${IMAGE_NAME}:${DEFAULT_TAG}"
    TARGET_IMAGE="${IMAGE_REGISTRY}/${IMAGE_NAME}:${DEFAULT_TAG}-${SAFE_PLATFORM}"

    echo "Pulling base image $BASE_IMAGE..."
    if ! sudo podman pull "$BASE_IMAGE"; then
        echo "Failed to pull $BASE_IMAGE. Skipping diff."
        exit 0
    fi

    echo "Running diff..."
    # The diff only feeds an informational PR comment (the post step
    # skips when the report is absent), while a failing container
    # runtime here is runner-state flake, not image quality: the
    # target image already booted and passed every gate above. Never
    # fail a green image over the comment.
    if ./scripts/diff-images.sh "$BASE_IMAGE" "$TARGET_IMAGE" "diff_report.md"; then
        # Add a header to the report
        sed -i '1s/^/## 🔍 Image Diff Report\n\n/' diff_report.md
    else
        echo "::warning::Image diff failed; skipping the PR diff comment."
        rm -f diff_report.md
    fi

# Build the Arch Linux ARM base image (localhost/archlinuxarm:build) from rootfs.tar.gz in the repo root (reads GITHUB_REPOSITORY); removes its buildah working container on exit and registers the image for ci-cleanup
ci-alarm-base-build:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}

    ctr=$(sudo buildah from scratch)
    # The working container (and its mount) is this recipe's own; drop it
    # whether the build succeeds or not. The committed image is unaffected.
    trap 'sudo buildah rm "$ctr" >/dev/null 2>&1 || true' EXIT
    mnt=$(sudo buildah mount "$ctr")
    sudo tar -xpf rootfs.tar.gz -C "$mnt" --numeric-owner
    # The tarball is a device rootfs: drop the board bits a container
    # never uses; alarm/root users stay (standard ALARM accounts).
    sudo rm -rf "$mnt/boot"/* "$mnt/etc/fstab"
    # pacman's Landlock/alpm-user sandbox cannot apply inside a
    # buildah run container ("switching to sandbox user 'alpm'
    # failed") — disable it in the image; consumers building FROM
    # this base need it off for the same reason.
    sudo sed -i '/^\[options\]/a DisableSandbox' "$mnt/etc/pacman.conf"
    sudo grep -q '^DisableSandbox' "$mnt/etc/pacman.conf"
    # Initialize pacman inside the rootfs (native arm64 runner).
    sudo buildah run "$ctr" -- pacman-key --init
    sudo buildah run "$ctr" -- pacman-key --populate archlinuxarm
    sudo buildah run "$ctr" -- pacman -Syu --noconfirm
    sudo buildah run "$ctr" -- pacman -Scc --noconfirm
    sudo buildah config \
        --arch arm64 --os linux \
        --env LANG=C.UTF-8 \
        --cmd /usr/bin/bash \
        --label org.opencontainers.image.title="Arch Linux ARM base" \
        --label org.opencontainers.image.description="Arch Linux ARM aarch64 rootfs as an OCI base image (marlin arm64/asahi prerequisite)" \
        --label org.opencontainers.image.source="https://github.com/${GITHUB_REPOSITORY}" \
        "$ctr"
    sudo buildah commit --format oci "$ctr" archlinuxarm:build

    . {{ justfile_directory() }}/scripts/lib/ci-scope.sh
    ci_own_image localhost/archlinuxarm:build --root
