# Image build and ISO orchestration recipes.
#
# Extracted from the root Justfile for issue #508. Imports share one flat
# namespace, so these recipes retain the existing names and can call root
# helpers such as _build and _ensure-deps without wrappers.

# Build a TunaOS variant
build variant='albacore' flavor='gnome' target_platform='' is_ci="0" tag='latest' chain_base_image='' enable_sshd="0": _ensure-deps
    #!/usr/bin/env bash
    set -euo pipefail
    DID_INIT="0"
    if [[ "{{ is_ci }}" != "1" ]] && [[ "${SKIP_SUBMODULES:-0}" != "1" ]] && [[ "{{ flavor }}" == *"gnome"* ]]; then
        git submodule update --init --recursive
        DID_INIT="1"
    fi
    if [[ -z "{{ target_platform }}" ]]; then
        if [[ "{{ is_ci }}" != "1" ]]; then PLATFORM="{{ platform }}"; else
            PLATFORM=$({{ yq }} -r ".variants[] | select(.id == \"{{ variant }}\") | .platforms | join(\",\")" .github/build-config.yml)
        fi
    else PLATFORM="{{ target_platform }}"; fi
    BASE_FOR_BUILD=""
    ENABLE_SSHD="{{ enable_sshd_var }}"
    FLAVOR="{{ flavor }}"
    if [[ "${FLAVOR}" == "all" ]]; then
        readarray -t FLAVORS < <({{ yq }} -r '.variants[] | select(.id == "{{ variant }}") | .flavors[].id' .github/build-config.yml)
        for f in "${FLAVORS[@]}"; do {{ just }} build "{{ variant }}" "$f"; done
        exit 0
    fi
    eval "$(./scripts/resolve-flavor.sh "{{ variant }}" "${FLAVOR}" "{{ is_ci }}")"
    export OVERLAY_TYPE ENABLE_ASAHI
    if [[ -z "${PARENT_FLAVOR}" ]]; then
        BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}" "${PLATFORM}")
    elif [[ "{{ is_ci }}" = "1" ]]; then
        BASE_FOR_BUILD=$(./scripts/published-image-ref.sh "{{ variant }}" "${PARENT_FLAVOR}-testing" ghcr)
    else
        BASE_FOR_BUILD="localhost/{{ variant }}:${PARENT_FLAVOR}"
        if ! podman image exists "${BASE_FOR_BUILD}" 2>/dev/null; then
            echo "==> ${BASE_FOR_BUILD} not in local storage; chaining on the published parent instead"
            BASE_FOR_BUILD=$(./scripts/published-image-ref.sh "{{ variant }}" "${PARENT_FLAVOR}-testing" ghcr)
        fi
    fi
    if [[ -n "{{ chain_base_image }}" ]] && [[ "${FLAVOR}" != "base" ]]; then BASE_FOR_BUILD="{{ chain_base_image }}"; fi
    TARGET_TAG="{{ variant }}"
    TARGET_IMAGE_TAG="{{ tag }}"
    [[ "{{ tag }}" == "latest" ]] && TARGET_IMAGE_TAG="${FLAVOR}"
    TARGET_TAG_WITH_VERSION="${TARGET_TAG}:${TARGET_IMAGE_TAG}"
    if [[ "{{ is_ci }}" == "0" ]]; then
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "$PLATFORM" "1" "${ENABLE_NVIDIA}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}" "{{ is_ci }}" "{{ enable_sshd }}"
        ./scripts/sync-build-cache.sh "${TARGET_TAG}" || true
    else
        {{ just }} _build "${TARGET_TAG_WITH_VERSION}" "{{ variant }}" "${CONTAINERFILE}" "${BASE_FOR_BUILD}" "$PLATFORM" "0" "${ENABLE_NVIDIA}" "${ENABLE_HWE}" "${DESKTOP_FLAVOR}" "{{ is_ci }}" "{{ enable_sshd }}"
    fi
    if [[ "$DID_INIT" == "1" ]]; then git submodule deinit -f --all; fi

# Full lifecycle test and remote corral build helpers.
lifecycle-test variant='albacore' flavor='gnome':
    ./scripts/lifecycle-test.sh "{{ variant }}" "{{ flavor }}"

corral-build variant='redfin' +flavors='all':
    ./scripts/corral-build.sh "{{ variant }}" {{ flavors }}

# Build a TunaOS live ISO via tacklebox.
iso variant='skipjack' flavor='gnome' repo='local' tag='' dev='0':
    #!/usr/bin/env bash
    set -euo pipefail
    _tag="{{ tag }}"
    [[ -z "$_tag" ]] && _tag="{{ flavor }}"
    _repo="{{ repo }}"
    if [[ "{{ dev }}" == "1" ]]; then
        {{ just }} build "{{ variant }}" "{{ flavor }}" "" "0" "$_tag" "" "1"
        _repo="local"
    fi
    sudo -E bash ./scripts/build-iso-tacklebox.sh "{{ variant }}" "{{ flavor }}" "$_repo" "$_tag" "{{ dev }}"

# Build one combined deduplicated ISO for an iso_group.
iso-group variant='yellowfin' group='default' repo='ghcr':
    sudo --preserve-env=GITHUB_REPOSITORY_OWNER,TACKLEBOX_FROM_SOURCE,TACKLEBOX_SHA,TACKLEBOX_IMAGE,TACKLEBOX_CACHE bash ./scripts/build-iso-group.sh "{{ variant }}" "{{ group }}" "{{ repo }}"
