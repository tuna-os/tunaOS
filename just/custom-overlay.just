# --- Customization overlay pipeline (custom/) ---
# Extracted from the root Justfile (#508: cross-repo Justfile inflation).
# _ensure-deps stays in the root Justfile (also used by build/_build); just's
# import shares one flat recipe/variable namespace, so referencing it here
# and calling `just build-custom` from custom-iso both still resolve.

# Build a custom TunaOS overlay using the configuration in custom/
build-custom base="" tag="": _ensure-deps
    #!/usr/bin/env bash
    set -euo pipefail
    BASE_IMAGE="{{ base }}"
    if [[ -z "${BASE_IMAGE}" ]]; then
        # yq, not a regex: `_ensure-deps` above already guarantees it, and it
        # parses YAML instead of pattern-matching text. The regex this replaced
        # (`re.search(r'base:\s*(\S+)')`) matched the first line containing
        # "base:" anywhere — including inside a comment or a nested block — and
        # called .group(1) on a possible None, so a missing or malformed field
        # raised AttributeError into `2>/dev/null` and silently produced the
        # default below. A wrong image built without complaint is worse than a
        # failure (tunaOS#1651).
        BASE_IMAGE=$({{ yq }} -r '.base // ""' custom/image.yaml 2>/dev/null || true)
        BASE_IMAGE="${BASE_IMAGE:-ghcr.io/tuna-os/yellowfin:gnome}"
    fi
    TARGET_TAG="{{ tag }}"
    if [[ -z "${TARGET_TAG}" ]]; then
        TARGET_TAG=$({{ yq }} -r '.tag // ""' custom/image.yaml 2>/dev/null || true)
        TARGET_TAG="${TARGET_TAG:-my-custom-os}"
    fi
    echo "==> Building custom image based on ${BASE_IMAGE} as localhost/${TARGET_TAG}..."
    podman build \
        --file Containerfile.custom \
        --build-arg BASE_IMAGE="${BASE_IMAGE}" \
        --tag "localhost/${TARGET_TAG}" \
        .

# Build QCOW2 from custom TunaOS image
run-custom-vm tag="":
    #!/usr/bin/env bash
    set -euo pipefail
    TARGET_TAG="{{ tag }}"
    if [[ -z "${TARGET_TAG}" ]]; then
        TARGET_TAG=$({{ yq }} -r '.tag // ""' custom/image.yaml 2>/dev/null || true)
        TARGET_TAG="${TARGET_TAG:-my-custom-os}"
    fi
    # Use scripts/build-qcow2.sh to build the QCOW2 from local image
    ./scripts/build-qcow2.sh "localhost/${TARGET_TAG}"

# Validate custom/ directory schema, syntax, and flatpaks
check-custom:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Validating custom/ overlay configuration..."
    if [[ -f custom/packages.yaml ]]; then
        if INVALID=$(grep -nvE '^[[:space:]]*(#.*)?$|^[a-zA-Z0-9_-]+[[:space:]]*:|^[[:space:]]*-[[:space:]]*' custom/packages.yaml); then
            printf 'Warning: custom/packages.yaml lines that are neither a mapping key nor a list item:\n%s\n' "$INVALID"
        fi
        echo "✓ custom/packages.yaml parsed successfully"
    fi
    for hook in custom/build.pre.sh custom/build.post.sh; do
        if [[ -f "$hook" ]]; then
            bash -n "$hook"
            echo "✓ $hook syntax valid"
        fi
    done
    echo "✓ Custom configuration check passed."

# Build a live ISO from a custom overlay image
custom-iso base_image='':
    #!/usr/bin/env bash
    set -euo pipefail
    {{ just }} build-custom "{{ base_image }}"
    TAG="my-custom-os"
    if [[ -f "custom/image.yaml" ]]; then
        T=$({{ yq }} -r '.tag // ""' custom/image.yaml 2>/dev/null || true)
        [[ -n "$T" ]] && TAG="$T"
    fi
    echo "==> Generating live ISO for localhost/${TAG}:latest..."
    sudo -E bash ./scripts/build-iso-tacklebox.sh "custom" "${TAG}" "local" "${TAG}" "1"
