#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
	printf 'usage: %s {shellcheck|shfmt|yaml|json|actionlint|just}\n' "$0" >&2
	exit 2
}

expect_invalid() {
	local expected="$1"
	shift
	local output
	output="$(mktemp)"
	if "$@" >"$output" 2>&1; then
		echo "::error::intentionally invalid lint fixture unexpectedly passed: $*" >&2
		rm -f "$output"
		exit 1
	fi
	if ! grep -Fq "$expected" "$output"; then
		echo "::error::invalid fixture failed without expected diagnostic $expected" >&2
		cat "$output" >&2
		rm -f "$output"
		exit 1
	fi
	rm -f "$output"
}

shell_files() {
	find . \
		-not -path './.git/*' \
		-not -path './system_files/usr/share/gnome-shell/extensions/*' \
		-not -path './packages-repo/*' \
		-not -path './.build/*' \
		-not -path './_upstream-snapshots/*' \
		-iname '*.sh' -type f -print0
}

yaml_files() {
	find . \
		-not -path './.git/*' \
		-not -path './system_files/usr/share/gnome-shell/extensions/*' \
		-not -path './packages-repo/*' \
		-not -path './.build/*' \
		-not -path './_upstream-snapshots/*' \
		-type f \( -name '*.yaml' -o -name '*.yml' \) -print0
}

json_files() {
	find . \
		-not -path './.git/*' \
		-not -path './system_files/usr/share/gnome-shell/extensions/*' \
		-not -path './packages-repo/*' \
		-not -path './.build/*' \
		-not -path './_upstream-snapshots/*' \
		-type f -name '*.json' -print0
}

run_shellcheck() {
	local -a files=()
	while IFS= read -r -d '' file; do
		files+=("$file")
	done < <(shell_files)
	if ! shellcheck --severity=style --exclude=SC1091,SC2114 "${files[@]}"; then
		echo "::warning::ShellCheck non-error findings are advisory; errors gate below."
	fi
	shellcheck --severity=error --exclude=SC1091,SC2114 "${files[@]}" >/dev/null
	shellcheck --severity=error --exclude=SC1091,SC2114 \
		tests/fixtures/lint/shellcheck-valid.fixture
	expect_invalid SC1046 shellcheck --severity=error --exclude=SC1091,SC2114 \
		tests/fixtures/lint/shellcheck-invalid.fixture
}

run_shfmt() {
	local -a files=()
	local output
	while IFS= read -r -d '' file; do
		files+=("$file")
	done < <(shell_files)
	output="$(shfmt -l "${files[@]}")"
	if [[ -n "$output" ]]; then
		echo "::error::Shell formatting drift. Run 'just fix' and commit the result."
		echo "$output"
		exit 1
	fi
}

run_yaml() {
	local failed=0
	while IFS= read -r -d '' file; do
		yamllint -c .yamllint.yml "$file" || failed=1
	done < <(yaml_files)
	return "$failed"
}

run_json() {
	local failed=0
	while IFS= read -r -d '' file; do
		jq . "$file" >/dev/null || {
			echo "::error::invalid JSON in $file" >&2
			failed=1
		}
	done < <(json_files)
	return "$failed"
}

actionlint_args=(
	-ignore 'permission "id-token" is unknown'
	-ignore SC2086
	-ignore SC2129
	-ignore SC2001
	-ignore SC2034
	-ignore SC2015
	-ignore SC1001
	-ignore SC2295
	-ignore SC2016
	-ignore save-always
	-ignore 'cannot be filtered'
)

run_actionlint() {
	local -a workflows=()
	while IFS= read -r -d '' file; do
		workflows+=("$file")
	done < <(find .github/workflows -maxdepth 1 -type f \
		\( -name '*.yaml' -o -name '*.yml' \) -print0)
	actionlint "${actionlint_args[@]}" "${workflows[@]}"
	actionlint "${actionlint_args[@]}" tests/fixtures/lint/actionlint-valid.fixture
	expect_invalid unknown_context actionlint "${actionlint_args[@]}" \
		tests/fixtures/lint/actionlint-invalid.fixture
}

run_just() {
	just --unstable --fmt --check -f Justfile
	local failed=0
	while IFS= read -r -d '' file; do
		just --unstable --fmt --check -f "$file" || failed=1
	done < <(find . \
		-not -path './.git/*' \
		-not -path './system_files/usr/share/gnome-shell/extensions/*' \
		-not -path './packages-repo/*' \
		-not -path './.build/*' \
		-not -path './_upstream-snapshots/*' \
		-type f -name '*.just' -print0)
	return "$failed"
}

case "${1:-}" in
shellcheck) run_shellcheck ;;
shfmt) run_shfmt ;;
yaml) run_yaml ;;
json) run_json ;;
actionlint) run_actionlint ;;
just) run_just ;;
*) usage ;;
esac
