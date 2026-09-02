# --- Default Base Image (for 'base' flavor builds) ---

export base_image := env("BASE_IMAGE", "quay.io/almalinuxorg/almalinux-bootc")
export base_image_tag := env("BASE_IMAGE_TAG", "10")

# Simulate the GitHub Actions CI matrix
simulate-matrix:
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    ./scripts/simulate-matrix.sh

[private]
default:
    @{{ just }} --list

_ensure_check_deps:
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    if ! command -v shellcheck &> /dev/null; then brew install shellcheck; fi
    if ! command -v shfmt &> /dev/null; then brew install shfmt; fi
    if ! command -v yamllint &> /dev/null; then brew install yamllint; fi
    if ! command -v jq &> /dev/null; then brew install jq; fi
    if ! command -v actionlint &> /dev/null; then brew install actionlint; fi

# Check Just Syntax
check: _ensure_check_deps
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    echo "Checking syntax of shell scripts..."
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -iname "*.sh" -type f -exec shellcheck --exclude=SC1091 "{}" ";"
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.yaml" -exec yamllint -c ./.yamllint.yml {} \; -o -name "*.yml" -exec yamllint {} \; 2>/dev/null || true
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.json" -exec sh -c 'jq . "$1" > /dev/null' _ {} \; 2>/dev/null || true
    if command -v actionlint &> /dev/null; then
        actionlint -ignore "permission \"id-token\" is unknown" -ignore "SC2086" -ignore "SC2129" -ignore "SC2001" -ignore "SC2034" -ignore "SC2015" -ignore "SC1001" -ignore "SC2295" -ignore "SC2016" -ignore "save-always" -ignore "cannot be filtered" .github/workflows/*.yml .github/workflows/*.yaml || { exit 1; }
    fi
    just --unstable --fmt --check -f Justfile
    echo "Checking workflow drift..."
    python3 {{ justfile_directory() }}/scripts/generate-workflows.py
    if ! git diff --exit-code .github/workflows/build-*.yml; then
        echo "::error::Generated workflow files are stale. Run 'just generate-workflows' and commit the changes."
        exit 1
    fi

# --- Test Targets ---
_ensure_test_deps: _ensure_check_deps
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    if ! command -v bats &> /dev/null; then brew install bats-core; fi
    if ! python3 -c "import pytest" 2>/dev/null; then pip3 install pytest --break-system-packages 2>/dev/null || pip3 install pytest --user; fi

test: _ensure_test_deps
    #!/usr/bin/env bash
    set -euo pipefail; FAILED=0
    cd {{ justfile_directory() }}
    for f in tests/bats/*.bats; do [[ -f "$f" ]] || continue; bats --formatter tap "$f" || FAILED=1; done
    python3 -m pytest tests/ tests/pytest/ -v --tb=short || FAILED=1
    exit $FAILED

test-bats: _ensure_test_deps
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    for f in tests/bats/*.bats; do [[ -f "$f" ]] || continue; bats --formatter tap "$f"; done

test-pytest: _ensure_test_deps
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    python3 -m pytest tests/ tests/pytest/ -v --tb=short

# --- Contributor contract (epic #2250 item 14) ---
#
# `just ci` is the PR gate, locally: what test.yml, lint.yml and the CI
# contract run, in one command, so nobody has to reverse-engineer forty
# workflows to know what will be checked. The scheduled lanes (full build
# matrix, boot gates, installer E2E, lifecycle) are NOT part of it; they are
# what `just test-cell` and `just test-e2e` reproduce one cell at a time.

# Install the tools the checks and tests need (brew/pip), then print versions
setup: _ensure_test_deps
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    for t in shellcheck shfmt yamllint jq actionlint bats yq; do
        printf '%-11s %s\n' "$t" "$(command -v "$t" >/dev/null && $t --version 2>&1 | head -1 || echo MISSING)"
    done
    python3 -c 'import pytest, yaml; print("pytest", pytest.__version__, "pyyaml", yaml.__version__)'

# Fast feedback: the Python suites only, stop at the first failure
test-fast: _ensure_test_deps
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    python3 -m pytest tests/ tests/pytest/ -q --tb=short -x

# The CI contract: every green gate exists, is reachable, and meets its freshness SLA
test-contract:
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    python3 {{ justfile_directory() }}/scripts/check-ci-contract.py

# The same suites as `test`, in a seeded random order. Reproduce a failure with the printed TUNAOS_TEST_SEED.
test-random seed='': _ensure_test_deps
    #!/usr/bin/env bash
    set -uo pipefail; FAILED=0
    cd {{ justfile_directory() }}
    seed="{{ seed }}"
    [[ -z "$seed" ]] && seed="${TUNAOS_TEST_SEED:-$(( (RANDOM << 15) | RANDOM ))}"
    export TUNAOS_TEST_SEED="$seed"
    echo "==> TUNAOS_TEST_SEED=$seed (reproduce with: TUNAOS_TEST_SEED=$seed just test-random)"
    # bats files in a seed-derived order; pytest shuffles itself from the env var
    readarray -t FILES < <(ls tests/bats/*.bats | shuf --random-source=<(yes "$seed"))
    for f in "${FILES[@]}"; do bats --formatter tap "$f" || FAILED=1; done
    python3 -m pytest tests/ tests/pytest/ -q --tb=short || FAILED=1
    if [[ "$FAILED" -ne 0 ]]; then echo "==> FAILED under TUNAOS_TEST_SEED=$seed"; fi
    exit $FAILED

# Run the desktop contract (green criterion `desktop`) against one published cell, exactly as the nightly sweep does
test-cell variant='yellowfin' flavor='gnome':
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}
    ref="ghcr.io/{{ repo_organization }}/{{ variant }}:{{ flavor }}"
    desktop="${ref##*:}"; desktop="${desktop%%-*}"
    echo "==> $ref: desktop contract ($desktop)"
    sudo podman run --rm --pull=always \
        -v "$PWD/build_scripts:/run/context/build_scripts:ro,z" \
        "$ref" bash /run/context/build_scripts/checks/verify-desktop-experience.sh "$desktop"

# Boot an ISO under QEMU and assert the live environment reaches readiness (green criterion `iso`); build one with `just iso`
test-e2e iso:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}
    sudo -E ./scripts/iso-e2e.sh "{{ iso }}"

# The PR gate, locally: format + lint checks, the CI contract, then every unit suite
ci: check test-contract test

generate-workflows:
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    chmod +x {{ justfile_directory() }}/scripts/generate-workflows.py && python3 {{ justfile_directory() }}/scripts/generate-workflows.py

fix:
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -iname "*.sh" -type f -exec shfmt --write "{}" ";"
    find . -type f -name "*.just" -exec just --unstable --fmt -f {} \;
    just --unstable --fmt -f Justfile || { exit 1; }

clean:
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
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
    cd {{ justfile_directory() }}
    echo "Pruning local build caches..."
    rm -rf .rpm-cache
    echo "Use 'podman system prune --build-cache' to prune BuildKit cache."
