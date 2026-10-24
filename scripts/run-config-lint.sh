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

# Every file walk prunes .git outright (it never descends into it) and skips
# vendored or generated trees that are not ours to lint.
repo_files() {
	find . \( \
		-path './.git' -o \
		-path './system_files/usr/share/gnome-shell/extensions' -o \
		-path './packages-repo' -o \
		-path './.build' -o \
		-path './_upstream-snapshots' \
		\) -prune -o -type f "$@" -print0
}

shell_files() { repo_files -iname '*.sh'; }
yaml_files() { repo_files \( -name '*.yaml' -o -name '*.yml' \); }
json_files() { repo_files -name '*.json'; }

# File lists are streamed through xargs -0 so the gates do not depend on the
# whole repository fitting into one argv (ARG_MAX). xargs exits non-zero when
# any batch fails, so a finding in any chunk still fails the gate.
run_shellcheck() {
	# Errors gate first. The all-severity advisory pass is useful only after
	# known errors are absent; otherwise it prints a misleading advisory warning.
	shell_files | xargs -0 bash -c \
		'(( $# == 0 )) || shellcheck --severity=error --exclude=SC1091,SC2114 "$@"' _
	shellcheck --severity=error --exclude=SC1091,SC2114 \
		tests/fixtures/lint/shellcheck-valid.fixture
	expect_invalid SC1046 shellcheck --severity=error --exclude=SC1091,SC2114 \
		tests/fixtures/lint/shellcheck-invalid.fixture
	if ! shell_files | xargs -0 bash -c \
		'(( $# == 0 )) || shellcheck --severity=style --exclude=SC1091,SC2114 "$@"' _; then
		echo "::warning::ShellCheck non-error findings are advisory."
	fi
}

# shfmt -l lists files needing formatting; test its output as well as its
# status, because a formatting gate that only checks an exit code can pass
# while drift exists.
run_shfmt() {
	local output
	output="$(shell_files | xargs -0 bash -c \
		'(( $# == 0 )) || shfmt -l "$@"' _)"
	if [[ -n "$output" ]]; then
		echo "::error::Shell formatting drift. Run 'just fix' and commit the result."
		echo "$output"
		exit 1
	fi
}

# CI installs yamllint with Homebrew; `just` bootstraps it with pip, which may
# put the executable in a directory that is not on PATH yet. The module form
# runs the same yamllint either way.
yamllint_cmd() {
	if command -v yamllint >/dev/null 2>&1; then
		yamllint "$@"
	else
		python3 -m yamllint "$@"
	fi
}

run_yaml() {
	local failed=0
	while IFS= read -r -d '' file; do
		yamllint_cmd -c .yamllint.yml "$file" || failed=1
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
	done < <(repo_files -name '*.just')
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
