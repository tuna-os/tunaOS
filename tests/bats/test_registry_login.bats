#!/usr/bin/env bats

setup() {
	REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
	SCRIPT="${REPO_ROOT}/scripts/registry-login.sh"
	STUB_BIN="${BATS_TEST_TMPDIR}/bin"
	LOGIN_LOG="${BATS_TEST_TMPDIR}/login.log"
	LOGIN_ATTEMPTS="${BATS_TEST_TMPDIR}/login-attempts.log"
	mkdir -p "$STUB_BIN"
	: >"$LOGIN_LOG"
	: >"$LOGIN_ATTEMPTS"

	cat >"${STUB_BIN}/registry-client" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
client="$(basename "$0")"
if [[ "$client" == podman && "${1:-}" == system ]]; then
	exit 0
fi
if [[ "${1:-}" == login ]]; then
	attempt="$(($(wc -l <"$LOGIN_ATTEMPTS") + 1))"
	printf '%s\n' "$attempt" >>"$LOGIN_ATTEMPTS"
	if ((attempt <= LOGIN_FAILS_BEFORE)); then
		exit 1
	fi
fi
secret="$(cat)"
printf '%s|%s|%s\n' "$client" "$*" "$secret" >>"$LOGIN_LOG"
EOF
	chmod +x "${STUB_BIN}/registry-client"
	for client in docker podman cosign skopeo; do
		ln -s registry-client "${STUB_BIN}/${client}"
	done
	ln -s /usr/bin/true "${STUB_BIN}/sleep"
	cat >"${STUB_BIN}/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == rm ]]; then
	exit 0
fi
exec "$@"
EOF
	chmod +x "${STUB_BIN}/sudo"

	export PATH="${STUB_BIN}:${PATH}"
	export LOGIN_LOG LOGIN_ATTEMPTS
	export LOGIN_FAILS_BEFORE=0
	export GITHUB_REPOSITORY_OWNER="Tuna-OS"
	export GITHUB_ACTOR="build-actor"
	export GITHUB_TOKEN="github-test-token"
	export GITHUB_EVENT_NAME="workflow_dispatch"
	export REGISTRY_LOGIN_MAX_RETRIES=1
	unset PUBLISH_REGISTRY_USERNAME PUBLISH_REGISTRY_TOKEN
}

@test "stock owner destination uses only the GitHub credential for every client" {
	export PUBLISH_DESTINATION="ghcr.io/Tuna-OS"
	export REGISTRY_LOGIN_CLIENTS="docker podman sudo-podman cosign skopeo"

	run "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$(wc -l <"$LOGIN_LOG")" -eq 5 ]
	[ "$(grep -c '|github-test-token$' "$LOGIN_LOG")" -eq 5 ]
	[[ "$output" != *"github-test-token"* ]]
}

@test "approved alternate registry uses the complete custom credential pair" {
	export PUBLISH_DESTINATION="quay.io/acme"
	export PUBLISH_REGISTRY_USERNAME="acme+publisher"
	export PUBLISH_REGISTRY_TOKEN="alternate-test-token"
	export REGISTRY_LOGIN_CLIENTS="podman cosign"

	run "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$(grep -c 'quay.io --username acme+publisher --password-stdin|alternate-test-token$' "$LOGIN_LOG")" -eq 2 ]
	[[ "$output" != *"alternate-test-token"* ]]
}

@test "alternate namespace on GHCR also requires and uses custom credentials" {
	export PUBLISH_DESTINATION="ghcr.io/sibling-org"
	export PUBLISH_REGISTRY_USERNAME="publisher"
	export PUBLISH_REGISTRY_TOKEN="namespace-test-token"
	export REGISTRY_LOGIN_CLIENTS="podman"

	run "$SCRIPT"

	[ "$status" -eq 0 ]
	grep -q 'podman|login ghcr.io --username publisher --password-stdin|namespace-test-token$' "$LOGIN_LOG"
}

@test "alternate destination without credentials fails before invoking a client" {
	export PUBLISH_DESTINATION="quay.io/acme"
	export REGISTRY_LOGIN_CLIENTS="podman"

	run "$SCRIPT"

	[ "$status" -ne 0 ]
	[[ "$output" == *"requires PUBLISH_REGISTRY_USERNAME and PUBLISH_REGISTRY_TOKEN"* ]]
	[ ! -s "$LOGIN_LOG" ]
}

@test "a partial custom credential pair fails closed" {
	export PUBLISH_DESTINATION="quay.io/acme"
	export PUBLISH_REGISTRY_USERNAME="publisher"
	export REGISTRY_LOGIN_CLIENTS="podman"

	run "$SCRIPT"

	[ "$status" -ne 0 ]
	[[ "$output" == *"must be configured together"* ]]
	[ ! -s "$LOGIN_LOG" ]
}

@test "custom credentials conflict with the stock owner destination" {
	export PUBLISH_DESTINATION="ghcr.io/tuna-os"
	export PUBLISH_REGISTRY_USERNAME="publisher"
	export PUBLISH_REGISTRY_TOKEN="conflicting-test-token"
	export REGISTRY_LOGIN_CLIENTS="podman"

	run "$SCRIPT"

	[ "$status" -ne 0 ]
	[[ "$output" == *"conflict with the stock"* ]]
	[[ "$output" != *"conflicting-test-token"* ]]
	[ ! -s "$LOGIN_LOG" ]
}

@test "malicious destination and username values are rejected without execution" {
	export PUBLISH_DESTINATION='quay.io/acme;touch-pwned'
	export PUBLISH_REGISTRY_USERNAME='publisher$(touch-pwned)'
	export PUBLISH_REGISTRY_TOKEN="malicious-test-token"
	export REGISTRY_LOGIN_CLIENTS="podman"

	run "$SCRIPT"

	[ "$status" -ne 0 ]
	[[ "$output" == *"invalid publish destination"* ]]
	[ ! -e "${BATS_TEST_TMPDIR}/touch-pwned" ]
	[ ! -s "$LOGIN_LOG" ]
}

@test "untrusted pull request execution cannot authenticate" {
	export GITHUB_EVENT_NAME="pull_request"
	export PUBLISH_DESTINATION="quay.io/acme"
	export PUBLISH_REGISTRY_USERNAME="publisher"
	export PUBLISH_REGISTRY_TOKEN="pr-test-token"
	export REGISTRY_LOGIN_CLIENTS="podman"

	run "$SCRIPT"

	[ "$status" -ne 0 ]
	[[ "$output" == *"disabled for untrusted pull request"* ]]
	[[ "$output" != *"pr-test-token"* ]]
	[ ! -s "$LOGIN_LOG" ]
}

@test "sudo podman retry exhaustion remains a visible failure" {
	export PUBLISH_DESTINATION="ghcr.io/tuna-os"
	export REGISTRY_LOGIN_CLIENTS="sudo-podman"
	export REGISTRY_LOGIN_MAX_RETRIES=3
	export LOGIN_FAILS_BEFORE=3

	run "$SCRIPT"

	[ "$status" -ne 0 ]
	[ "$(wc -l <"$LOGIN_ATTEMPTS")" -eq 3 ]
	[[ "$output" == *"sudo-podman registry login failed after 3 attempts"* ]]
}

@test "sudo podman succeeds when a later retry clears the failure" {
	export PUBLISH_DESTINATION="ghcr.io/tuna-os"
	export REGISTRY_LOGIN_CLIENTS="sudo-podman"
	export REGISTRY_LOGIN_MAX_RETRIES=3
	export LOGIN_FAILS_BEFORE=1

	run "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$(wc -l <"$LOGIN_ATTEMPTS")" -eq 2 ]
	[[ "$output" == *"failed (attempt 1/3); retrying"* ]]
}

@test "sudo podman success on the first attempt does not enter retry handling" {
	export PUBLISH_DESTINATION="ghcr.io/tuna-os"
	export REGISTRY_LOGIN_CLIENTS="sudo-podman"
	export REGISTRY_LOGIN_MAX_RETRIES=3

	run "$SCRIPT"

	[ "$status" -eq 0 ]
	[ "$(wc -l <"$LOGIN_ATTEMPTS")" -eq 1 ]
	[[ "$output" != *"retrying"* ]]
}
