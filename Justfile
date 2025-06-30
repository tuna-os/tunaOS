export repo_organization := env("GITHUB_REPOSITORY_OWNER", "ublue-os")
export image_name := env("IMAGE_NAME", "albacore")
export centos_version := env("CENTOS_VERSION", "10")
export default_tag := env("DEFAULT_TAG", "a10-server")
export bib_image := env("BIB_IMAGE", "quay.io/centos-bootc/bootc-image-builder:latest")

alias build-vm := build-qcow2
alias rebuild-vm := rebuild-qcow2
alias run-vm := run-vm-qcow2

[private]
default:
    @just --list

# Check Just Syntax
[group('Just')]
check:
    #!/usr/bin/env bash
    find . -type f -name "*.just" | while read -r file; do
    	echo "Checking syntax: $file"
    	just --unstable --fmt --check -f $file
    done
    echo "Checking syntax: Justfile"
    just --unstable --fmt --check -f Justfile

# Fix Just Syntax
[group('Just')]
fix:
    #!/usr/bin/env bash
    find . -type f -name "*.just" | while read -r file; do
    	echo "Checking syntax: $file"
    	just --unstable --fmt -f $file
    done
    echo "Checking syntax: Justfile"
    just --unstable --fmt -f Justfile || { exit 1; }

# Clean Repo
[group('Utility')]
clean:
    #!/usr/bin/env bash
    set -eoux pipefail
    touch _build
    find *_build* -exec rm -rf {} \;
    rm -f previous.manifest.json
    rm -f changelog.md
    rm -f output.env

# Sudo Clean Repo
[group('Utility')]
[private]
sudo-clean:
    just sudoif just clean

# sudoif bash function
[group('Utility')]
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
    just sudoif {{ command }} {{ args }}

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
build $target_image=image_name $tag=default_tag $dx="0" $gdx="0" $platform="linux/amd64":
    #!/usr/bin/env bash

    # Get Version
    ver="${tag}-${centos_version}.$(date +%Y%m%d)"

    BUILD_ARGS=()
    BUILD_ARGS+=("--build-arg" "MAJOR_VERSION=${centos_version}")
    BUILD_ARGS+=("--build-arg" "IMAGE_NAME=${image_name}")
    BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR=${repo_organization}")
    BUILD_ARGS+=("--build-arg" "ENABLE_DX=${dx}")
    BUILD_ARGS+=("--build-arg" "ENABLE_GDX=${gdx}")
    if [[ -z "$(git status -s)" ]]; then
        BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=$(git rev-parse --short HEAD)")
    fi

    podman build \
        --platform "${platform:-linux/amd64}" \
        "${BUILD_ARGS[@]}" \
        --pull=newer \
        --tag "${target_image}:${tag}" \
        .

# Default variables mirroring the GitHub Action inputs
# Override from the command line, e.g., just --set ref 'your/image'

ref := 'localhost/' + image_name + ':' + default_tag
prev_ref := ''
clear_plan := ''
prev_ref_fail := ''
max_layers := ''
skip_compression := ''
labels := ''
description := ''
version := '<date>'
pretty := ''
rechunk_image := 'ghcr.io/hhd-dev/rechunk:latest'
keep_ref := ''
changelog := ''
git_repo := '.'
revision := ''
formatters := ''
meta_file := ''

# Internal variables

workdir := '.'
container_id_file := workdir + '/container.id'
mount_path_file := workdir + '/mount.path'
out_name := file_name(replace(ref, ':', '_'))

# Mounts the initial OCI image using Podman
mount_image:
    #!/usr/bin/env bash
    set -euxo pipefail

    if [[ -z "{{ ref }}" ]]; then
        echo "Error: 'ref' variable must be set."
        exit 1
    fi

    CREF=$(just sudoif podman create {{ ref }} bash)
    MOUNT=$(just sudoif podman mount $CREF)
    echo "$CREF" > {{ container_id_file }}
    echo "$MOUNT" > {{ mount_path_file }}
    echo "Image mounted at: $MOUNT"

# Creates an OSTree commit from the mounted filesystem
create_commit: mount_image
    #!/usr/bin/env bash
    set -euxo pipefail
    MOUNT_PATH=$(cat {{ mount_path_file }})

    echo "Pruning filesystem..."
    just sudoif podman run --rm \
        --privileged \
        --security-opt label=type:unconfined_t \
        -v "${MOUNT_PATH}":/var/tree:Z \
        -e TREE=/var/tree \
        -u 0:0 \
        {{ rechunk_image }} \
        /sources/rechunk/1_prune.sh

    echo "Committing to OSTree..."
    just sudoif podman run --rm \
        --privileged \
        --security-opt label=type:unconfined_t \
        -v "${MOUNT_PATH}":/var/tree:Z \
        -e TREE=/var/tree \
        -v "cache_ostree:/var/ostree" \
        -e REPO=/var/ostree/repo \
        -e RESET_TIMESTAMP=1 \
        -u 0:0 \
        {{ rechunk_image }} \
        /sources/rechunk/2_create.sh

# Rechunks the OSTree commit into a new OCI image
rechunk: create_commit
    #!/usr/bin/env bash
    set -euxo pipefail
    CONTAINER_ID=$(cat {{ container_id_file }})

    echo "Unmounting and removing container..."
    just sudoif podman unmount "$CONTAINER_ID"
    just sudoif podman rm "$CONTAINER_ID"
    if [ -z "{{ keep_ref }}" ]; then
      just sudoif podman rmi --force {{ ref }}
    fi

    if [[ -n "{{ meta_file }}" ]]; then
        cp "{{ meta_file }}" "{{ workdir }}/_meta_in.yml"
    fi

    echo "Rechunking OSTree commit..."
    just sudoif podman run --rm \
        -v "{{ workdir }}:/workspace" \
        -v "{{ git_repo }}:/var/git" \
        -v "cache_ostree:/var/ostree" \
        -e REPO=/var/ostree/repo \
        -e MAX_LAYERS="{{ max_layers }}" \
        -e SKIP_COMPRESSION="{{ skip_compression }}" \
        -e PREV_REF="{{ prev_ref }}" \
        -e OUT_NAME="{{ out_name }}" \
        -e LABELS="{{ labels }}" \
        -e FORMATTERS="{{ formatters }}" \
        -e VERSION="{{ version }}" \
        -e VERSION_FN="/workspace/version.txt" \
        -e PRETTY="{{ pretty }}" \
        -e DESCRIPTION="{{ description }}" \
        -e CHANGELOG="{{ changelog }}" \
        -e OUT_REF="oci:{{ out_name }}" \
        -e GIT_DIR="/var/git" \
        -e CLEAR_PLAN="{{ clear_plan }}" \
        -e REVISION="{{ revision }}" \
        -e PREV_REF_FAIL="{{ prev_ref_fail }}" \
        -u 0:0 \
        {{ rechunk_image }} \
        /sources/rechunk/3_chunk.sh

    just sudoif chown $(id -u):$(id -g) -R "{{ workdir }}/{{ out_name }}"

    echo "--- Just Action Outputs ---"
    echo "version: $(cat {{ workdir }}/version.txt)"
    echo "ref: oci:{{ workdir }}/{{ out_name }}"
    echo "location: {{ workdir }}/{{ out_name }}"
    echo "changelog: {{ workdir }}/{{ out_name }}.changelog.txt"
    echo "manifest: {{ workdir }}/{{ out_name }}.manifest.json"

# Cleans up generated files and volumes
rechunk_cleanup:
    #!/usr/bin/env bash
    set -euxo pipefail
    echo "Removing temporary files and OSTree volume..."
    rm -f {{ container_id_file }} {{ mount_path_file }} {{ workdir }}/_meta_in.yml {{ workdir }}/version.txt
    if [ -d "{{ workdir }}/{{ out_name }}" ]; then
        rm -rf "{{ workdir }}/{{ out_name }}"*
    fi
    just sudoif podman volume rm cache_ostree || echo "Volume 'cache_ostree' not found."

sync_image SID DID=SID reverse='false':
    #!/usr/bin/env bash
    set -eoux pipefail

    if [[ "{{ reverse }}" == 'true' ]]; then
        if [[ -z "${SUDO_USER:-}" ]] || ! podman image exists "{{ SID }}"; then
            exit 0
        fi
        TARGET_UID=$(id -u "${SUDO_USER}")
        SOURCE_EP="root@localhost::{{ SID }}"
        DEST_EP="${TARGET_UID}@localhost::{{ DID }}"
        just sudoif -i -u "${SUDO_USER}" podman image rm "{{ DID }}" >/dev/null 2>&1 || true
        podman image scp "${SOURCE_EP}" "${DEST_EP}"
        podman image rm "{{ SID }}"
    else
        if ! podman image exists "{{ SID }}"; then
            exit 1
        fi
        SOURCE_EP="${UID}@localhost::{{ SID }}"
        DEST_EP="root@localhost::{{ DID }}"

# Build a bootc bootable image using Bootc Image Builder (BIB)
# Converts a container image to a bootable image
# Parameters:
#   target_image: The name of the image to build (ex. localhost/fedora)
#   tag: The tag of the image to build (ex. latest)
#   type: The type of image to build (ex. qcow2, raw, iso)
#   config: The configuration file to use for the build (default: image.toml)

# Example: just _rebuild-bib localhost/fedora latest qcow2 image.toml
_build-bib $target_image $tag $type $config: (sync_image target_image tag)
    #!/usr/bin/env bash
    set -euo pipefail

    mkdir -p "output"

    echo "Cleaning up previous build"
    if [[ $type == iso ]]; then
      just sudoif rm -rf "output/bootiso" || true
    else
      just sudoif rm -rf "output/${type}" || true
    fi

    args="--type ${type} "
    args+="--use-librepo=False"

    if [[ $target_image == localhost/* ]]; then
      args+=" --local"
    fi

    just sudoif podman run \
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

    just sudoif chown -R $USER:$USER output

# Podman build's the image from the Containerfile and creates a bootable image
# Parameters:
#   target_image: The name of the image to build (ex. localhost/fedora)
#   tag: The tag of the image to build (ex. latest)
#   type: The type of image to build (ex. qcow2, raw, iso)
#   config: The configuration file to use for the build (deafult: image.toml)

# Example: just _rebuild-bib localhost/fedora latest qcow2 image.toml
_rebuild-bib $target_image $tag $type $config: (build target_image tag) && (_build-bib target_image tag type config)

# Build a QCOW2 virtual machine image
[group('Build Virtal Machine Image')]
build-qcow2 $target_image=("localhost/" + image_name) $tag=default_tag: && (_build-bib target_image tag "qcow2" "image.toml")

# Build a RAW virtual machine image
[group('Build Virtal Machine Image')]
build-raw $target_image=("localhost/" + image_name) $tag=default_tag: && (_build-bib target_image tag "raw" "image.toml")

# Build an ISO virtual machine image
[group('Build Virtal Machine Image')]
build-iso $target_image=("localhost/" + image_name) $tag=default_tag: && (_build-bib target_image tag "iso" "iso.toml")

# Rebuild a QCOW2 virtual machine image
[group('Build Virtal Machine Image')]
rebuild-qcow2 $target_image=("localhost/" + image_name) $tag=default_tag: && (_rebuild-bib target_image tag "qcow2" "image.toml")

# Rebuild a RAW virtual machine image
[group('Build Virtal Machine Image')]
rebuild-raw $target_image=("localhost/" + image_name) $tag=default_tag: && (_rebuild-bib target_image tag "raw" "image.toml")

# Rebuild an ISO virtual machine image
[group('Build Virtal Machine Image')]
rebuild-iso $target_image=("localhost/" + image_name) $tag=default_tag: && (_rebuild-bib target_image tag "iso" "iso.toml")

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
[group('Run Virtal Machine')]
run-vm-qcow2 $target_image=("localhost/" + image_name) $tag=default_tag: && (_run-vm target_image tag "qcow2" "image.toml")

# Run a virtual machine from a RAW image
[group('Run Virtal Machine')]
run-vm-raw $target_image=("localhost/" + image_name) $tag=default_tag: && (_run-vm target_image tag "raw" "image.toml")

# Run a virtual machine from an ISO
[group('Run Virtal Machine')]
run-vm-iso $target_image=("localhost/" + image_name) $tag=default_tag: && (_run-vm target_image tag "iso" "iso.toml")

# Run a virtual machine using systemd-vmspawn
[group('Run Virtal Machine')]
spawn-vm rebuild="0" type="qcow2" ram="6G":
    #!/usr/bin/env bash

    set -euo pipefail

    [ "{{ rebuild }}" -eq 1 ] && echo "Rebuilding the ISO" && just build-vm {{ rebuild }} {{ type }}

    systemd-vmspawn \
      -M "achillobator" \
      --console=gui \
      --cpus=2 \
      --ram=$(echo {{ ram }}| /usr/bin/numfmt --from=iec) \
      --network-user-mode \
      --vsock=false --pass-ssh-key=false \
      -i ./output/**/*.{{ type }}

##########################
#  'customize-iso-build' #
##########################
# Description:
# Enables the manual customization of the osbuild manifest before running the ISO build
#
# Mount the configuration file and output directory
# Clear the entrypoint to run the custom command

# Run osbuild with the specified parameters
customize-iso-build:
    just sudoif podman run \
    --rm -it \
    --privileged \
    --pull=newer \
    --net=host \
    --security-opt label=type:unconfined_t \
    -v $(pwd)/iso.toml \
    -v $(pwd)/output:/output \
    -v /var/lib/containers/storage:/var/lib/containers/storage \
    --entrypoint "" \
    "${bib_image}" \
    osbuild --store /store --output-directory /output /output/manifest-iso.json --export bootiso

##########################
#  'patch-iso-branding'  #
##########################
# Description:
# creates a custom branded ISO image. As per https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/7/html/anaconda_customization_guide/sect-iso-images#sect-product-img
# Parameters:
#   override: A flag to determine if the final ISO should replace the original ISO (default is 0).
#   iso_path: The path to the original ISO file.
# Runs a Podman container with Fedora image. Installs 'lorax' and 'mkksiso' tools inside the container. Creates a compressed 'product.img'
# from the Brnading images in the 'iso_files' directory. Uses 'mkksiso' to add the 'product.img' to the original ISO and creates 'final.iso'
# in the output directory. If 'override' is not 0, replaces the original ISO with the newly created 'final.iso'.

# applies custom branding to an ISO image.
patch-iso-branding override="0" iso_path="output/bootiso/install.iso":
    #!/usr/bin/env bash
    podman run \
        --rm \
        -it \
        --pull=newer \
        --privileged \
        -v ./output:/output \
        -v ./iso_files:/iso_files \
        quay.io/centos/centos:stream10 \
        bash -c 'dnf install -y lorax && \
    	mkdir /images && cd /iso_files/product && find . | cpio -c -o | gzip -9cv > /images/product.img && cd / \
            && mkksiso --add images --volid albacore-boot /{{ iso_path }} /output/final.iso'

    if [ {{ override }} -ne 0 ] ; then
        mv output/final.iso {{ iso_path }}
    fi

# Runs shell check on all Bash scripts
lint:
    /usr/bin/find . -iname "*.sh" -type f -exec shellcheck "{}" ';'

# Runs shfmt on all Bash scripts
format:
    /usr/bin/find . -iname "*.sh" -type f -exec shfmt --write "{}" ';'

run-bootc-libvirt $target_image=("localhost/" + image_name) $tag=default_tag $image_name=image_name: (sync_image target_image tag)
    #!/usr/bin/env bash
    set -euo pipefail

    mkdir -p "output/"

    # clean up previous builds
    echo "Cleaning up previous build"
    just sudoif if rm -rf "output/${image_name}_${tag}.raw" || true
    mkdir -p "output/"

     # build the disk image
    truncate -s 20G output/${image_name}_${tag}.raw
    # just sudoif if podman run \
    # --rm --privileged \
    # -v /var/lib/containers:/var/lib/containers \
    # quay.io/centos-bootc/centos-bootc:stream10 \
    # /usr/libexec/bootc-base-imagectl rechunk \
    # ${target_image}:${tag} ${target_image}:re${tag}
    just sudoif if podman run \
    --pid=host --network=host --privileged \
    --security-opt label=type:unconfined_t \
    -v $(pwd)/output:/output:Z \
    ${target_image}:${tag} bootc install to-disk --via-loopback --generic-image /output/${image_name}_${tag}.raw
    QEMU_DISK_QCOW2=$(pwd)/output/${image_name}_${tag}.raw
    # Run the VM using QEMU
    echo "Running VM with QEMU using disk: ${QEMU_DISK_QCOW2}"
    # Ensure the disk file exists
    if [[ ! -f "${QEMU_DISK_QCOW2}" ]]; then
        echo "Disk file ${QEMU_DISK_QCOW2} does not exist. Please build the image first."
        exit 1
    fi
    just sudoif virt-install --os-variant almalinux9 --boot hd \
        --name "${image_name}-${tag}" \
        --memory 2048 \
        --vcpus 2 \
        --disk path="${QEMU_DISK_QCOW2}",format=raw,bus=scsi,discard=unmap \
        --network bridge=virbr0,model=virtio \
        --console pty,target_type=virtio \
        --noautoconsole
