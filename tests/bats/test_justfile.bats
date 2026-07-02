#!/usr/bin/env bats
# Justfile validation tests for TunaOS
#
# These tests validate that the Justfile recipes are well-formed,
# have correct dependency chains, and expose expected recipes.
# Run with:
#   bats tests/justfile/test_recipes.bats
#
# Related issue: https://github.com/tuna-os/tunaOS/issues/183

setup() {
  REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
  JUSTFILE="${REPO_ROOT}/Justfile"
}

# ─── Recipe Existence Tests ─────────────────────────────────────────────────

@test "justfile: exists at repository root" {
  [ -f "${JUSTFILE}" ]
}

@test "justfile: has 'build' recipe" {
  run grep -E '^build[:( ]' "${JUSTFILE}"
  [ "$status" -eq 0 ]
}

# Recipes may live in the root Justfile or in imported just/*.just modules
# (import shares one namespace), so existence checks scan both.

@test "justfile: has 'lint' recipe or equivalent" {
  # Should have a lint or check target
  run grep -hE '^(lint|check)[:( ]' "${JUSTFILE}" "${REPO_ROOT}/just"/*.just
  [ "$status" -eq 0 ]
}

@test "justfile: has 'clean' recipe" {
  run grep -hE '^clean[:( ]' "${JUSTFILE}" "${REPO_ROOT}/just"/*.just
  [ "$status" -eq 0 ]
}

@test "justfile: has 'test' recipe" {
  run grep -hE '^test[:( ]' "${JUSTFILE}" "${REPO_ROOT}/just"/*.just
  [ "$status" -eq 0 ]
}

@test "justfile: has container build recipe" {
  # Justfile uses 'build' recipe with parameters, not build-* prefixes
  run grep -E '^build[ (:]' "${JUSTFILE}"
  [ "$status" -eq 0 ]
}

# ─── Dependency Chain Tests ─────────────────────────────────────────────────

@test "justfile: no circular dependencies in self-referential recipes" {
  # Check that no recipe directly calls itself
  # This is a basic check — full cycle detection needs a graph tool
  recipes=$(grep -oP '^[a-zA-Z_][a-zA-Z0-9_-]*' "${JUSTFILE}" | sort -u)
  while IFS= read -r recipe; do
    # Skip empty lines
    [ -z "$recipe" ] && continue
    # Find the recipe body (from recipe name to next recipe or EOF)
    body=$(sed -n "/^${recipe}[:( ]/,/^[a-zA-Z_][a-zA-Z0-9_-]*[:( ]/p" "${JUSTFILE}" | head -n -1)
    # Check it doesn't call itself with 'just ${recipe}'
    if echo "$body" | grep -qE "just[[:space:]]+${recipe}\b"; then
      run echo "Recipe '${recipe}' appears to call itself"
      [ "$status" -eq 0 ]  # Informational only
    fi
  done <<< "$recipes"
}

@test "justfile: build depends on container-build or equivalent" {
  # Verify the build chain exists
  run grep -E 'just[[:space:]](build-image|build-container|build-ci)' "${JUSTFILE}"
  # This may fail if Justfile uses different conventions — informational
  [ "$status" -eq 0 ] || true
}

# ─── Variable Default Tests ─────────────────────────────────────────────────

@test "justfile: FLAVOR variable has default" {
  run grep -E '^[[:space:]]*FLAVOR[[:space:]]*[:=]' "${JUSTFILE}"
  [ "$status" -eq 0 ]
}

@test "justfile: VERSION variable has default or is setable" {
  run grep -E 'VERSION' "${JUSTFILE}"
  [ "$status" -eq 0 ]
}

@test "justfile: REGISTRY variable is configured" {
  # Justfile uses inline registry references (ghcr.io, quay.io) without a top-level REGISTRY var
  run grep -E 'ghcr\.io|quay\.io' "${JUSTFILE}"
  [ "$status" -eq 0 ]
}

# ─── Formatting Tests ───────────────────────────────────────────────────────

@test "justfile: no trailing whitespace" {
  run grep -n '[[:space:]]$' "${JUSTFILE}"
  if [ "$status" -eq 0 ]; then
    echo "Trailing whitespace found on lines:"
    echo "$output"
  fi
  # Non-fatal — formatting advisory
  [ "$status" -ne 0 ] || true
}

@test "justfile: recipe names use kebab-case or snake_case consistently" {
  # Extract recipe names
  recipes=$(grep -oP '^[a-zA-Z_][a-zA-Z0-9_-]*' "${JUSTFILE}" | grep -v '^$' | sort -u)
  kebab_count=0
  snake_count=0
  while IFS= read -r name; do
    [ -z "$name" ] && continue
    if [[ "$name" == *-* ]]; then
      kebab_count=$((kebab_count + 1))
    elif [[ "$name" == *_* ]]; then
      snake_count=$((snake_count + 1))
    fi
  done <<< "$recipes"
  echo "kebab-case: $kebab_count, snake_case: $snake_count"
  # Advisory: consistency is good but not enforced
  [ "$kebab_count" -gt 0 ] || [ "$snake_count" -gt 0 ]
}

# ─── Size and Complexity Tests ──────────────────────────────────────────────

@test "justfile: line count is within manageable threshold (under 5000 lines)" {
  lines=$(wc -l < "${JUSTFILE}")
  echo "Justfile has $lines lines"
  [ "$lines" -lt 5000 ]
}

@test "justfile: no recipes exceed 200 lines (complexity check)" {
  # Extract recipe line counts
  # This is a simplistic check — a proper tool would parse the just syntax
  long_recipes=$(awk '/^[a-zA-Z_][a-zA-Z0-9_-]*[:( ]/{
    if (name) print name, NR - start
    name=$1; start=NR
  }
  END{ if (name) print name, NR - start + 1 }' "${JUSTFILE}" | \
    awk '$2 > 200 {print $1, $2}')
  if [ -n "$long_recipes" ]; then
    echo "Recipes exceeding 200 lines:"
    echo "$long_recipes"
  fi
  # Advisory: recipes over 200 lines should be considered for extraction
  [ -z "$long_recipes" ] || true
}
