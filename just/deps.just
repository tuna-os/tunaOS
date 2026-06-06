# just/deps.just — Dependency management and code quality checks

# [deps]
# Check requirements for syntax checking
[private]
_ensure_check_deps:
    #!/usr/bin/env bash
    if ! command -v shellcheck &> /dev/null; then
        brew install shellcheck
    fi
    if ! command -v shfmt &> /dev/null; then
        brew install shfmt
    fi
    if ! command -v yamllint &> /dev/null; then
        brew install yamllint
    fi
    if ! command -v jq &> /dev/null; then
        brew install jq
    fi
    if ! command -v actionlint &> /dev/null; then
        brew install actionlint
    fi

# Check Just Syntax
# [deps]
check: _ensure_check_deps
    #!/usr/bin/env bash
    echo "Checking syntax of shell scripts..."
    /usr/bin/find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -iname "*.sh" -type f -exec shellcheck --exclude=SC1091 "{}" ";"
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.yaml" | while read -r file; do
        yamllint -c ./.yamllint.yml "$file" || { exit 1; }
    done

# Generate GitHub Actions workflows from build-config.yml
# [ci]
generate-workflows:
    #!/usr/bin/env bash
    set -euo pipefail
    python3 scripts/generate-workflows.py

# Fix Just Syntax
# [deps]
fix:
    #!/usr/bin/env bash
    set -euo pipefail

    is_installed() { command -v "$1" &>/dev/null; }

    echo "Fixing shell scripts with shfmt..."
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -iname "*.sh" -type f -print0 | xargs -0 shfmt -i 4 -bn -ci -sr -kp -w 2>/dev/null || true

    echo "Formatting YAML files..."
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f \( -name "*.yaml" -o -name "*.yml" \) | while read -r file; do
        if is_installed prettier; then
            prettier --write --parser yaml "$file" 2>/dev/null || true
        elif is_installed yq; then
            cp "$file" "$file.bak" && {{ yq }} -i -P "$file" && rm "$file.bak" 2>/dev/null || true
        fi
    done

    echo "Formatting JSON files..."
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f -name "*.json" | while read -r file; do if is_installed prettier; then prettier --write "$file" 2>/dev/null || true; fi; done

    echo "Formatting Markdown files..."
    find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -not -path './.build/*' -type f \( -name "*.md" -o -name "*.mdx" \) | while read -r file; do if is_installed prettier; then prettier --write "$file" 2>/dev/null || true; fi; done

# Remove common build artifacts
# [deps]
clean:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Cleaning TunaOS build artifacts..."

    rm -rf out.ociarchive 2>/dev/null || true
    rm -f Containerfile 2>/dev/null || true
    rm -rf ./packages-repo/ 2>/dev/null || true
    rm -rf .build/ 2>/dev/null || true

    for img in $(podman images --format "{{.Repository}}:{{.Tag}}" 2>/dev/null | grep "$(pwd)" || true); do
        podman rmi "$img" 2>/dev/null || true
    done

    podman system prune -f 2>/dev/null || true
    echo "Done."

# Prune build caches (DNF/RPM cache directory shared across all variants)
# [deps]
clean-cache:
    #!/usr/bin/env bash
    rm -rf ./build-cache/ 2>/dev/null || true
    echo "Build cache cleaned."
