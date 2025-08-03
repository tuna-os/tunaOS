export repo_organization := env("GITHUB_REPOSITORY_OWNER", "ublue-os")
export image_name := env("IMAGE_NAME", "albacore")
export centos_version := env("CENTOS_VERSION", "10")
export default_tag := env("DEFAULT_TAG", "a10-server")
export bib_image := env("BIB_IMAGE", "quay.io/centos-bootc/bootc-image-builder:latest")

# Base image configuration - supports multiple bootc-compatible images

export base_image := env("BASE_IMAGE", "quay.io/almalinuxorg/almalinux-bootc")
export base_image_tag := env("BASE_IMAGE_TAG", "10")

alias build-vm := build-qcow2
alias run-vm := run-vm-qcow2

[private]
default:
    @just --list

# Check Just Syntax
check:
    #!/usr/bin/env bash
    find . -type f -name "*.just" | while read -r file; do
    	echo "Checking syntax: $file"
    	just --unstable --fmt --check -f $file
    done
    echo "Checking syntax: Justfile"
    just --unstable --fmt --check -f Justfile

# Fix Just Syntax
fix:
    #!/usr/bin/env bash
    find . -type f -name "*.just" | while read -r file; do
    	echo "Checking syntax: $file"
    	just --unstable --fmt -f $file
    done
    echo "Checking syntax: Justfile"
    just --unstable --fmt -f Justfile || { exit 1; }

# Clean Repo
clean:
    #!/usr/bin/env bash
    set -eoux pipefail
    touch _build
    find *_build* -exec rm -rf {} \;
    rm -f previous.manifest.json
    rm -f changelog.md
    rm -f output.env

# Sudo Clean Repo
[private]
sudo-clean:
    sudo just clean

# sudoif bash function
[private]
sudoif command *args:
    #!/usr/bin/env bash
    function sudoif(){
        if [[ "${UID}" -eq 0 ]]; then
            "$@"
        elif [[ "$(command -v sudo)" && -n "${SSH_ASKPASS:-}" ]] && [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
            /usr/bin/sudo --askpass "$@" || exit 1
        elif [[ "$(command -v sudo)" ]]; then
            /usr/bin/sudo "$@" || exit 1
        else
            exit 1
        fi
    }
    sudo {{ command }} {{ args }}

# This Justfile recipe builds a container image using Podman.
#
# Arguments:
#   $target_image - The tag you want to apply to the image (default: albacore).
#   $tag - The tag for the image (default: lts).
#   $dx - Enable DX (default: "0").
#   $gdx - Enable GDX (default: "0").
#
# DX:
#   Developer Experience (DX) is a feature that allows you to install the latest developer tools for your system.
#   Packages include VScode, Docker, Distrobox, and more.
# GDX: https://docs.projectalbacore.io/gdx/
#   GPU Developer Experience (GDX) creates a base as an AI and Graphics platform.
#   Installs Nvidia drivers, CUDA, and other tools.
#
# The script constructs the version string using the tag and the current date.
# If the git working directory is clean, it also includes the short SHA of the current HEAD.
#
# just build $target_image $tag $dx $gdx
#
# Example usage:
#   just build albacore lts 1 0
#
# This will build an image 'albacore:a10-server' with DX and GDX enabled.
#
# Build the image using the specified parameters
# Supports multiple base images through variants:
# - yellowfin: AlmaLinux Kitten 10 (development)
# - albacore: AlmaLinux 10 (stable)
# - skipjack: CentOS Stream bootc
# - bonito: Fedora bootc

# - custom: Use BASE_IMAGE and BASE_IMAGE_TAG environment variables
build $target_image=image_name $tag=default_tag $dx="0" $gdx="0" $platform="linux/amd64" $variant="albacore":
    #!/usr/bin/env bash

    # Get Version
    ver="${tag}-${centos_version}.$(date +%Y%m%d)"

    # Set base image based on variant
    case "${variant}" in
        "yellowfin")
            BASE_IMG="quay.io/almalinuxorg/almalinux-bootc"
            BASE_TAG="10-kitten"
            ;;
        "albacore")
            BASE_IMG="quay.io/almalinuxorg/almalinux-bootc"
            BASE_TAG="10"
            ;;
        "skipjack")
            BASE_IMG="quay.io/centos-bootc/centos-bootc"
            BASE_TAG="stream10"
            ;;
        "bonito")
            BASE_IMG="quay.io/fedora/fedora-bootc"
            BASE_TAG="42"
            ;;
        "bonito-rawhide")
            BASE_IMG="quay.io/fedora/fedora-bootc"
            BASE_TAG="rawhide"
            ;;
        "custom"|*)
            # Use environment variables for custom base images
            BASE_IMG="{{ base_image }}"
            BASE_TAG="{{ base_image_tag }}"
            ;;
    esac

    BUILD_ARGS=()
    BUILD_ARGS+=("--build-arg" "MAJOR_VERSION=${centos_version}")
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME=${image_name}")
    BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR=${repo_organization}")
    BUILD_ARGS+=("--build-arg" "ENABLE_DX=${dx}")
    BUILD_ARGS+=("--build-arg" "ENABLE_GDX=${gdx}")
    BUILD_ARGS+=("--build-arg" "BASE_IMAGE=${BASE_IMG}")
    BUILD_ARGS+=("--build-arg" "BASE_IMAGE_TAG=${BASE_TAG}")
    if [[ -z "$(git status -s)" ]]; then
        BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=$(git rev-parse --short HEAD)")
    fi

    podman build \
        --platform "${platform:-linux/amd64}" \
        "${BUILD_ARGS[@]}" \
        --pull=newer \
        --tag "${target_image}:${tag}" \
        .

# Build yellowfin variant (AlmaLinux Kitten 10)
build-yellowfin $tag="latest" $dx="0" $gdx="0" $platform="linux/amd64":
    just build yellowfin {{ tag }} {{ dx }} {{ gdx }} {{ platform }} yellowfin

# Build albacore variant (AlmaLinux 10.0)
build-albacore $tag="latest" $dx="0" $gdx="0" $platform="linux/amd64":
    just build albacore {{ tag }} {{ dx }} {{ gdx }} {{ platform }} albacore

# Build CentOS Stream variant
build-skipjack $tag="latest" $dx="0" $gdx="0" $platform="linux/amd64":
    just build skipjack {{ tag }} {{ dx }} {{ gdx }} {{ platform }} skipjack

# Build Fedora variant
build-bonito $tag="latest" $dx="0" $gdx="0" $platform="linux/amd64":
    just build bonito {{ tag }} {{ dx }} {{ gdx }} {{ platform }} bonito

# Build with custom base image (uses BASE_IMAGE and BASE_IMAGE_TAG env vars)
build-custom $tag="latest" $dx="0" $gdx="0" $platform="linux/amd64":
    just build custom-{{ tag }} {{ tag }} {{ dx }} {{ gdx }} {{ platform }} custom

# Build all available variants including additional distributions
build-all:
    just build-yellowfin &
    just build-albacore &
    just build-centos &
    just build-fedora &
    wait

# Build a bootc bootable image using Bootc Image Builder (BIB)
# Converts a container image to a bootable image
# Parameters:
#   target_image: The name of the image to build (ex. localhost/fedora)
#   tag: The tag of the image to build (ex. latest)
#   type: The type of image to build (ex. qcow2, raw, iso)
#   config: The configuration file to use for the build (default: image.toml)

# Example: just _rebuild-bib localhost/fedora latest qcow2 image.toml
_build-bib $target_image $tag $type $config:
    #!/usr/bin/env bash
    set -euo pipefail

    mkdir -p "output"

    echo "Cleaning up previous build"
    if [[ $type == iso ]]; then
      sudo rm -rf "output/bootiso" || true
    else
      sudo rm -rf "output/${type}" || true
    fi

    args="--type ${type} "
    args+="--use-librepo=False"

    if [[ $target_image == localhost/* ]]; then
      args+=" --local"
    fi

    sudo podman run \
      --rm \
      -it \
      --privileged \
      --pull=newer \
      --net=host \
      --security-opt label=type:unconfined_t \
      -v $(pwd)/${config}:/config.toml:ro \
      -v $(pwd)/output:/output \
      -v /var/lib/containers/storage:/var/lib/containers/storage \
      "${bib_image}" \
      ${args} \
      "${target_image}:${tag}"

    sudo chown -R $USER:$USER output

# Podman build's the image from the Containerfile and creates a bootable image
# Parameters:
#   target_image: The name of the image to build (ex. localhost/fedora)
#   tag: The tag of the image to build (ex. latest)
#   type: The type of image to build (ex. qcow2, raw, iso)
#   config: The configuration file to use for the build (deafult: image.toml)

# Build a QCOW2 virtual machine image

build-qcow2 $target_image=("localhost/" + image_name) $tag=default_tag: && (_build-bib target_image tag "qcow2" "image.toml")

# Build a RAW virtual machine image

build-raw $target_image=("localhost/" + image_name) $tag=default_tag: && (_build-bib target_image tag "raw" "image.toml")

# Build an ISO virtual machine image

build-iso $target_image=("localhost/" + image_name) $tag=default_tag: && (_build-bib target_image tag "iso" "iso.toml")

# Run a virtual machine with the specified image type and configuration
_run-vm $target_image $tag $type $config:
    #!/usr/bin/env bash
    set -eoux pipefail

    # Determine the image file based on the type
    image_file="output/${type}/disk.${type}"
    if [[ $type == iso ]]; then
        image_file="output/bootiso/install.iso"
    fi

    # Build the image if it does not exist
    if [[ ! -f "${image_file}" ]]; then
        just "build-${type}" "$target_image" "$tag"
    fi

    # Determine an available port to use
    port=8006
    while grep -q :${port} <<< $(ss -tunalp); do
        port=$(( port + 1 ))
    done
    echo "Using Port: ${port}"
    echo "Connect to http://localhost:${port}"

    # Set up the arguments for running the VM
    run_args=()
    run_args+=(--rm --privileged)
    run_args+=(--pull=newer)
    run_args+=(--publish "127.0.0.1:${port}:8006")
    run_args+=(--env "CPU_CORES=4")
    run_args+=(--env "RAM_SIZE=3G")
    run_args+=(--env "DISK_SIZE=64G")
    run_args+=(--env "TPM=Y")
    run_args+=(--env "GPU=Y")
    run_args+=(--device=/dev/kvm)
    run_args+=(--volume "${PWD}/${image_file}":"/boot.${type}")
    run_args+=(docker.io/qemux/qemu)

    # Run the VM and open the browser to connect
    podman run "${run_args[@]}" &
    xdg-open http://localhost:${port}
    fg "%podman"

# Run a virtual machine from a QCOW2 image

run-vm-qcow2 $target_image=("localhost/" + image_name) $tag=default_tag: && (_run-vm target_image tag "qcow2" "image.toml")

# Run a virtual machine from a RAW image

run-vm-raw $target_image=("localhost/" + image_name) $tag=default_tag: && (_run-vm target_image tag "raw" "image.toml")

# Run a virtual machine from an ISO

run-vm-iso $target_image=("localhost/" + image_name) $tag=default_tag: && (_run-vm target_image tag "iso" "iso.toml")


# Runs shell check on all Bash scripts
lint:
    /usr/bin/find . -iname "*.sh" -type f -exec shellcheck "{}" ';'

# Runs shfmt on all Bash scripts
format:
    /usr/bin/find . -iname "*.sh" -type f -exec shfmt --write "{}" ';'
