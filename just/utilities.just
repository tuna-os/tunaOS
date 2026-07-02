# --- Default Base Image (for 'base' flavor builds) ---

export base_image := env("BASE_IMAGE", "quay.io/almalinuxorg/almalinux-bootc")
export base_image_tag := env("BASE_IMAGE_TAG", "10")

# Simulate the GitHub Actions CI matrix
simulate-matrix:
    #!/usr/bin/env bash
    ./scripts/simulate-matrix.sh

[private]
default:
    @{{ just }} --list

_ensure_check_deps:
    #!/usr/bin/env bash
    if ! command -v shellcheck &> /dev/null; then brew install shellcheck; fi
    if ! command -v shfmt &> /dev/null; then brew install shfmt; fi
    if ! command -v yamllint &> /dev/null; then brew install yamllint; fi
    if ! command -v jq &> /dev/null; then brew install jq; fi
    if ! command -v actionlint &> /dev/null; then brew install actionlint; fi

# Check Just Syntax
check: _ensure_check_deps
    #!/usr/bin/env bash
    echo "Checking syntax of shell scripts..."
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -iname "*.sh" -type f -exec shellcheck --exclude=SC1091 "{}" ";"
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.yaml" -exec yamllint -c ./.yamllint.yml {} \; -o -name "*.yml" -exec yamllint {} \; 2>/dev/null || true
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.json" -exec sh -c 'jq . "$1" > /dev/null' _ {} \; 2>/dev/null || true
    if command -v actionlint &> /dev/null; then
        actionlint -ignore "permission \"id-token\" is unknown" -ignore "SC2086" -ignore "SC2129" -ignore "SC2001" -ignore "SC2034" -ignore "SC2015" -ignore "SC1001" -ignore "SC2295" -ignore "SC2016" -ignore "save-always" -ignore "cannot be filtered" .github/workflows/*.yml .github/workflows/*.yaml || { exit 1; }
    fi
    just --unstable --fmt --check -f Justfile
    echo "Checking workflow drift..."
    python3 scripts/generate-workflows.py
    if ! git diff --exit-code .github/workflows/build-*.yml; then
        echo "::error::Generated workflow files are stale. Run 'just generate-workflows' and commit the changes."
        exit 1
    fi

# --- Test Targets ---
_ensure_test_deps: _ensure_check_deps
    #!/usr/bin/env bash
    if ! command -v bats &> /dev/null; then brew install bats-core; fi
    if ! python3 -c "import pytest" 2>/dev/null; then pip3 install pytest --break-system-packages 2>/dev/null || pip3 install pytest --user; fi

test: _ensure_test_deps
    #!/usr/bin/env bash
    set -euo pipefail; FAILED=0
    for f in tests/bats/*.bats; do [[ -f "$f" ]] || continue; bats --formatter tap "$f" || FAILED=1; done
    python3 -m pytest tests/ tests/pytest/ -v --tb=short || FAILED=1
    exit $FAILED

test-bats: _ensure_test_deps
    #!/usr/bin/env bash
    for f in tests/bats/*.bats; do [[ -f "$f" ]] || continue; bats --formatter tap "$f"; done

test-pytest: _ensure_test_deps
    #!/usr/bin/env bash
    python3 -m pytest tests/ tests/pytest/ -v --tb=short

generate-workflows:
    #!/usr/bin/env bash
    chmod +x scripts/generate-workflows.py && python3 scripts/generate-workflows.py

fix:
    #!/usr/bin/env bash
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -iname "*.sh" -type f -exec shfmt --write "{}" ";"
    find . -type f -name "*.just" -exec just --unstable --fmt -f {} \;
    just --unstable --fmt -f Justfile || { exit 1; }

clean:
    #!/usr/bin/env bash
    echo "Cleaning up build artifacts and images..."
    echo "Note: Preserving .rpm-cache for faster rebuilds. Use 'just clean-cache' to remove."
    rm -rf .build-logs; sudo rm -rf .build/*; rm -f out.ociarchive
    readarray -t VARIANTS < <({{ yq }} -r '.variants[].id' .github/build-config.yml 2>/dev/null || echo -e "yellowfin\nalbacore\nbonito\nskipjack\nredfin")
    for variant in "${VARIANTS[@]}"; do
        readarray -t FLAVORS < <({{ yq }} -r ".variants[] | select(.id == \"$variant\") | .flavors[].id" .github/build-config.yml 2>/dev/null || true)
        for flavor in "${FLAVORS[@]}"; do
            podman rmi -f "localhost/${variant}:${flavor}" 2>/dev/null || true
            sudo podman rmi -f "localhost/${variant}:${flavor}" 2>/dev/null || true
        done
    done

clean-cache:
    #!/usr/bin/env bash
    echo "Pruning local build caches..."
    rm -rf .rpm-cache
    echo "Use 'podman system prune --build-cache' to prune BuildKit cache."
