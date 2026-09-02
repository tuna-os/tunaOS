export repo_organization := env("GITHUB_REPOSITORY_OWNER", "tuna-os")
export default_tag := env("DEFAULT_TAG", "latest")
export common_image := env("COMMON_IMAGE", "ghcr.io/projectbluefin/common")
export brew_image := env("BREW_IMAGE", "ghcr.io/ublue-os/brew")
export coreos_stable_version := env("COREOS_STABLE_VERSION", "43")
export enable_sshd_var := env("ENABLE_SSHD", "0")
just := just_executable()
arch := arch()
yq := `which yq`
export platform := env("PLATFORM", if arch == "x86_64" { if `rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; echo $?` == "0" { "linux/amd64/v2" } else { "linux/amd64" } } else if arch == "arm64" { "linux/arm64" } else if arch == "aarch64" { "linux/arm64" } else { error("Unsupported ARCH '" + arch + "'. Supported values are 'x86_64', 'aarch64', and 'arm64'.") })

import 'just/utilities.just'
import 'just/custom-overlay.just'
import 'just/vm-pipeline.just'
import 'just/qcow2-build.just'

# ==============================================================================
#  BUILD PIPELINE
# ==============================================================================

# Check if requirements are installed
[private]
_ensure-deps:
    #!/usr/bin/env bash
    if ! command -v "{{ yq }}" &> /dev/null; then
        echo "Missing requirement: 'yq' is not installed."
        echo "Please install yq (e.g. 'brew install yq' or download from https://github.com/mikefarah/yq)"
        exit 1
    fi

# Private build engine — thin wrapper that exports env vars and calls the script.
[private]
_build target_tag_with_version target_tag container_file base_image_for_build target_platform use_cache enable_gdx enable_hwe desktop_flavor is_ci_build enable_sshd_build *args: _ensure-deps
    #!/usr/bin/env bash
    set -euxo pipefail
    export IMAGE_TAG="{{ target_tag_with_version }}"
    export VARIANT="{{ target_tag }}"
    export CONTAINERFILE="{{ container_file }}"
    export BASE_IMAGE="{{ base_image_for_build }}"
    export PLATFORM="{{ target_platform }}"
    export USE_CACHE="{{ use_cache }}"
    export ENABLE_NVIDIA="{{ enable_gdx }}"
    export ENABLE_HWE="{{ enable_hwe }}"
    export DESKTOP_FLAVOR="{{ desktop_flavor }}"
    export IS_CI="{{ is_ci_build }}"
    export ENABLE_SSHD="{{ enable_sshd_build }}"
    export IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io}"
    export REPO_ORGANIZATION="{{ repo_organization }}"
    export COMMON_IMAGE="{{ common_image }}"
    export BREW_IMAGE="{{ brew_image }}"
    export COREOS_STABLE_VERSION="{{ coreos_stable_version }}"
    export YQ="{{ yq }}"
    # OVERLAY_TYPE inherited from parent shell (exported by build recipe)
    ./scripts/build-image-inner.sh

# Build a TunaOS variant
build variant='albacore' flavor='gnome' target_platform='' is_ci="0" tag='latest' chain_base_image='' enable_sshd="0": _ensure-deps
    #!/usr/bin/env bash
    set -euo pipefail

    # Initialize submodules locally
    DID_INIT="0"
    if [[ "{{ is_ci }}" != "1" ]] && [[ "${SKIP_SUBMODULES:-0}" != "1" ]]; then
        if [[ "{{ flavor }}" == *"gnome"* ]]; then
            git submodule update --init --recursive
            DID_INIT="1"
        fi
    fi

    BLUE='\033[0;34m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'

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

    # Resolve flavor into build parameters via external script (testable, DRY)
    eval "$(./scripts/resolve-flavor.sh "{{ variant }}" "${FLAVOR}" "{{ is_ci }}")"
    # CONTAINERFILE, DESKTOP_FLAVOR, ENABLE_HWE, ENABLE_NVIDIA, OVERLAY_TYPE, ENABLE_ASAHI, PARENT_FLAVOR now set
    export OVERLAY_TYPE
    export ENABLE_ASAHI

    # Resolve BASE_FOR_BUILD based on PARENT_FLAVOR
    if [[ -z "${PARENT_FLAVOR}" ]]; then
        BASE_FOR_BUILD=$(./scripts/get-base-image.sh "{{ variant }}" "${PLATFORM}")
    elif [[ "{{ is_ci }}" = "1" ]]; then
        # CI chains on the -testing stream tag
        BASE_FOR_BUILD=$(./scripts/published-image-ref.sh "{{ variant }}" "${PARENT_FLAVOR}-testing" ghcr)
    else
        # Stage-3 flavors (-nvidia, -hwe) chain on their parent flavor's image.
        # Locally that is normally in podman storage from an earlier `just
        # build`, but it is NOT there for a dev/e2e ISO: `just iso ... dev=1`
        # calls build with is_ci="0" hardcoded, so on a CI runner this branch
        # asked for an image nobody had built and buildah tried to resolve
        # "localhost" as a registry:
        #
        #   Error: initializing source docker://localhost/yellowfin:gnome:
        #   pinging container registry localhost
        #
        # That is the single cause of all 24 NVIDIA cells failing LUKS E2E
        # (run 29978067348) — one systemic issue, not 24. Fall back to the
        # published parent when the local one is absent, which also makes
        # `just iso <variant> <flavor>-nvidia ... 1` work on a clean machine.
        BASE_FOR_BUILD="localhost/{{ variant }}:${PARENT_FLAVOR}"
        if ! podman image exists "${BASE_FOR_BUILD}" 2>/dev/null; then
            echo "==> ${BASE_FOR_BUILD} not in local storage; chaining on the published parent instead"
            BASE_FOR_BUILD=$(./scripts/published-image-ref.sh "{{ variant }}" "${PARENT_FLAVOR}-testing" ghcr)
        fi
    fi

    if [[ -n "{{ chain_base_image }}" ]] && [[ "${FLAVOR}" != "base" ]]; then
        BASE_FOR_BUILD="{{ chain_base_image }}"
    fi

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

    if [[ "$DID_INIT" == "1" ]]; then
        echo "De-initializing submodules..."
        git submodule deinit -f --all
    fi

# Full lifecycle test: build → ISO → boot → install → verify (nested QEMU on corral VM)
# Usage: just lifecycle-test redfin gnome
# just lifecycle-test albacore kde
lifecycle-test variant='albacore' flavor='gnome':
    ./scripts/lifecycle-test.sh "{{ variant }}" "{{ flavor }}"

# Build on a corral VM (fans out the full flavor matrix on a KubeVirt builder)
# Usage: just corral-build redfin all
# just corral-build yellowfin gnome kde
corral-build variant='redfin' +flavors='all':
    ./scripts/corral-build.sh "{{ variant }}" {{ flavors }}

# Build a TunaOS live ISO via tacklebox (no Anaconda, tbox-live + sd-boot)
# Build a live ISO via tacklebox (replaces deprecated bootc-image-builder approach)
iso variant='skipjack' flavor='gnome' repo='local' tag='' dev='0':
    #!/usr/bin/env bash
    set -euo pipefail
    _tag="{{ tag }}"
    [[ -z "$_tag" ]] && _tag="{{ flavor }}"
    _repo="{{ repo }}"
    if [[ "{{ dev }}" == "1" ]]; then
        # Dev mode: rebuild locally with SSH enabled for e2e testing, and
        # customize that fresh local image — regardless of `repo`. Published
        # images (ghcr/registry) never have ENABLE_SSHD set, so pulling one
        # for a dev/e2e ISO leaves SSH unavailable (and, on apt-based
        # variants like grouper, no sshd package installed at all).
        {{ just }} build "{{ variant }}" "{{ flavor }}" "" "0" "$_tag" "" "1"
        _repo="local"
    fi
    sudo -E bash ./scripts/build-iso-tacklebox.sh "{{ variant }}" "{{ flavor }}" "$_repo" "$_tag" "{{ dev }}"

# Build ONE combined dedup ISO containing every desktop in an iso_group (#455).
# group: '' / default (flagship gnome+hwe), community (kde/cosmic/niri), nvidia.
iso-group variant='yellowfin' group='default' repo='ghcr':
    # --preserve-env: the inner sudo must not strip the CI-pinned tacklebox
    # source build vars (a plain sudo here silently fell back to the stale
    # ghcr tacklebox image while CI believed it was testing pinned fixes).
    sudo --preserve-env=GITHUB_REPOSITORY_OWNER,TACKLEBOX_FROM_SOURCE,TACKLEBOX_SHA,TACKLEBOX_IMAGE,TACKLEBOX_CACHE bash ./scripts/build-iso-group.sh "{{ variant }}" "{{ group }}" "{{ repo }}"
# ==============================================================================
#  QCOW2 DISK-IMAGE BUILD
# ==============================================================================
# (moved to just/qcow2-build.just — #508, cross-repo Justfile inflation)

# ==============================================================================
#  RUN / VM PIPELINE
# ==============================================================================
# (moved to just/vm-pipeline.just — #508, cross-repo Justfile inflation)

# ==============================================================================
#  DEV LOOP (same checks CI runs)
# ==============================================================================

# Shellcheck every script with the same excludes as lint.yml
lint:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> shellcheck"
    /usr/bin/find . \
      -not -path './system_files/usr/share/gnome-shell/extensions/*' \
      -not -path './packages-repo/*' \
      -not -path './.build/*' \
      -not -path './_upstream-snapshots/*' \
      -not -path './.git/*' \
      -iname "*.sh" -type f \
      -exec shellcheck --exclude=SC1091,SC2114 {} +
    if command -v yamllint &>/dev/null; then
        echo "==> yamllint"
        yamllint -d relaxed .github/
    else
        echo "(yamllint not installed; skipped)"
    fi

# Run the full staged build pipeline
pipeline variant='all' flavor='all' tag='latest' dry_run='0':
    #!/usr/bin/env bash
    export JUST="{{ just }}"
    ./scripts/pipeline.sh "{{ variant }}" "{{ flavor }}" "{{ tag }}" "{{ dry_run }}"

# Attach to the currently running Zellij pipeline session
attach:
    #!/usr/bin/env bash
    SESSION=$(zellij list-sessions 2>/dev/null | grep "pipeline-" | head -1 | awk '{print $1}')
    [[ -z "$SESSION" ]] && SESSION=$(zellij list-sessions 2>/dev/null | grep -v "gemini-" | head -1 | awk '{print $1}')
    if [ -n "$SESSION" ]; then echo "Attaching to Zellij session: $SESSION"; zellij attach "$SESSION"
    else echo "No active zellij session found."; exit 1; fi
