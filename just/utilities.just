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

# Refuse to format or lint with anything except the reviewed toolchain.
#
# CI and contributors both read toolchain/lint-tools.json. The bootstrap checks
# release-asset SHA-256 digests before installation; this check then rejects a
# missing or shadowed binary before any formatter or linter can touch the tree.
_check_lint_tool_versions:
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    python3 scripts/lint_tools.py verify

_ensure_check_deps: _check_lint_tool_versions
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    if ! command -v yamllint &> /dev/null; then python3 -m pip install yamllint --break-system-packages 2>/dev/null || python3 -m pip install yamllint --user; fi
    if ! command -v jq &> /dev/null; then brew install jq; fi
    if ! command -v yq &> /dev/null; then brew install yq; fi
    if ! command -v node &> /dev/null; then brew install node; fi

# Check prose with the same pinned shared linter and budget as CI. This is a
# check, not a formatter: STE findings need a human wording change, so `just
# fix` deliberately does not alter Markdown.
ste: _ensure_check_deps
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    ./scripts/run-ste-lint.sh

# Check Just Syntax
check: _ensure_check_deps ste
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    python3 "{{ justfile_directory() }}/scripts/config.py" generate >/dev/null || exit 1
    python3 "{{ justfile_directory() }}/scripts/config.py" check-builder-config >/dev/null || exit 1
    python3 "{{ justfile_directory() }}/scripts/config.py" check-flatpak-policy >/dev/null || exit 1
    python3 "{{ justfile_directory() }}/scripts/config.py" check-builder-flavors >/dev/null || exit 1
    echo "Checking syntax of shell scripts..."
    ./scripts/run-config-lint.sh shellcheck
    echo "Checking shell formatting (shfmt)..."
    ./scripts/run-config-lint.sh shfmt
    echo "Checking YAML..."
    ./scripts/run-config-lint.sh yaml
    echo "Checking JSON..."
    ./scripts/run-config-lint.sh json
    echo "Checking GitHub Actions workflows..."
    ./scripts/run-config-lint.sh actionlint
    echo "Checking Justfile formatting..."
    ./scripts/run-config-lint.sh just
    echo "Checking workflow drift..."
    python3 {{ justfile_directory() }}/scripts/generate-workflows.py
    python3 {{ justfile_directory() }}/scripts/gen-ci-lanes.py --check
    # Check only generated per-variant wrappers; build-variant.yml is shared workflow source.
    generated_workflows=()
    while IFS= read -r variant; do
        generated_workflows+=(".github/workflows/build-${variant}.yml")
    done < <(yq -r '.variants[].id' .github/build-config.yml)
    if ! git diff --exit-code -- "${generated_workflows[@]}"; then
        echo "::error::Generated workflow files are stale. Run 'just generate-workflows' and commit the changes."
        exit 1
    fi

# --- Test Targets ---
_ensure_test_deps: _ensure_check_deps
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    python3 "{{ justfile_directory() }}/scripts/config.py" generate >/dev/null || exit 1
    if ! command -v bats &> /dev/null; then brew install bats-core; fi
    if ! python3 -c "import pytest" 2>/dev/null; then pip3 install pytest --break-system-packages 2>/dev/null || pip3 install pytest --user; fi
    python3 -m pip install -r requirements-package-authoring.txt --break-system-packages || python3 -m pip install -r requirements-package-authoring.txt --user
    command -v yq >/dev/null || { echo "yq is required to read test dependency pins" >&2; exit 1; }
    schema_version=$(yq -r '.downloads.jsonschema // ""' image-versions.yaml)
    [[ "$schema_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid jsonschema test pin" >&2; exit 1; }
    installed=$(python3 -c 'import importlib.metadata; print(importlib.metadata.version("jsonschema"))' 2>/dev/null || true)
    if [[ "$installed" != "$schema_version" ]]; then python3 -m pip install "jsonschema==$schema_version" --break-system-packages || python3 -m pip install "jsonschema==$schema_version" --user; fi

test: _ensure_test_deps
    #!/usr/bin/env bash
    set -euo pipefail; FAILED=0
    cd {{ justfile_directory() }}
    for f in tests/bats/*.bats; do [[ -f "$f" ]] || continue; bats --formatter tap "$f" || FAILED=1; done
    python3 -m pytest tests/ tests/pytest/ -v --tb=short || FAILED=1
    python3 {{ justfile_directory() }}/scripts/generate-countme-allowlist.py --check || FAILED=1
    npm ci --ignore-scripts --prefix services/countme || FAILED=1
    npm test --prefix services/countme || FAILED=1
    npm run build --prefix services/countme || FAILED=1
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

# Install checksum-verified lint tools, then the remaining test dependencies.
# TUNAOS_LINT_BIN_DIR supports an isolated prefix; ~/.local/bin is the default
# so the same bootstrap works without root on Linux and macOS.
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}
    bin_dir="${TUNAOS_LINT_BIN_DIR:-$HOME/.local/bin}"
    python3 scripts/lint_tools.py install --bin-dir "$bin_dir"
    export PATH="$bin_dir:$PATH"
    just _ensure_test_deps
    python3 scripts/lint_tools.py verify
    for t in yamllint jq bats yq node; do
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
    ref="$(./scripts/publish-destination.sh)/{{ variant }}:{{ flavor }}"
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

fix: _check_lint_tool_versions
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    # _upstream-snapshots is VENDORED upstream code kept for reference. Its
    # value is being byte-identical to what upstream ships, so reformatting it
    # destroys the only reason it exists -- and it was 14 of the files `just
    # fix` rewrote on a clean main.
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './_upstream-snapshots/*' -iname "*.sh" -type f -exec shfmt --write "{}" ";"
    # Same exclusion as the shell loop above, and for the same reason. Without
    # it the automation bot reformats vendored .just files and opens a PR for
    # the change on every run: #2421, #2422 and #2423 were three identical
    # rewrites of the same _upstream-snapshots/zirconium/.../67-gamerslop.just,
    # regenerated as fast as they were rejected.
    find . -not -path './_upstream-snapshots/*' -not -path './packages-repo/*' -type f -name "*.just" -exec just --unstable --fmt -f {} \;
    just --unstable --fmt -f Justfile || { exit 1; }

clean:
    #!/usr/bin/env bash
    cd {{ justfile_directory() }}
    python3 "{{ justfile_directory() }}/scripts/config.py" generate >/dev/null || exit 1
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
