#!/usr/bin/env bash
# One explicitly approved diagnostic cell; existing installer test owns install logic.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ "${DIAGNOSTIC_SOURCE_SHA:-}" =~ ^[a-f0-9]{40}$ ]] || {
	echo 'Exact approved source SHA required' >&2
	exit 2
}
[[ "$(git rev-parse HEAD)" == "$DIAGNOSTIC_SOURCE_SHA" ]] || {
	echo 'Checkout differs from approved source SHA' >&2
	exit 2
}
[[ "${GITHUB_RUN_ATTEMPT:-1}" == "1" ]] || {
	echo 'Use a newly approved dispatch, not a rerun' >&2
	exit 2
}
export VARIANT=skipjack FLAVOR=gnome TACKLEBOX_FROM_SOURCE=1
export TUNAOS_COVERAGE_CAPTURE=1 TUNAOS_COVERAGE_SOURCE_SHA="$DIAGNOSTIC_SOURCE_SHA"
export TUNAOS_COVERAGE_WORKFLOW_SHA="${DIAGNOSTIC_WORKFLOW_SHA:?workflow SHA required}"
export E2E_WALL_CLOCK_DEADLINE="$(($(date +%s) + 90 * 60))"
export E2E_CHECKPOINT_STRICT=0 TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK=0
mkdir -p coverage-diagnostic
trap 'sudo chown -R "$(id -u):$(id -g)" coverage-diagnostic 2>/dev/null || true' EXIT
# No push, gallery publication, registry credentials, or external state mutation.
timeout --signal=TERM 70m sudo -E env "PATH=$PATH" just iso skipjack gnome ghcr "" 1
mapfile -t isos < <(find .build -maxdepth 3 -type f -name '*.iso')
[[ "${#isos[@]}" == "1" ]] || {
	echo 'Expected exactly one newly built diagnostic ISO' >&2
	exit 1
}
backend_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/coverage-fisherman.XXXXXX")"
timeout 5m git clone --depth 1 --branch dev https://github.com/tuna-os/fisherman "$backend_dir/source"
gover="$(awk '/^go /{print $2; exit}' "$backend_dir/source/fisherman/go.mod")"
[[ "$gover" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || {
	echo 'Invalid measured Go version' >&2
	exit 1
}
timeout 15m sudo podman run --rm -v "$backend_dir/source:/src:z" -w /src/fisherman \
	"docker.io/library/golang:$gover" go build -buildvcs=false -o /src/fisherman-bin ./cmd/fisherman
export FISHERMAN_OVERRIDE="$backend_dir/source/fisherman-bin"
set +e
sudo -E env FISHERMAN_OVERRIDE="$FISHERMAN_OVERRIDE" \
	TUNAOS_COVERAGE_CAPTURE=1 TUNAOS_COVERAGE_SOURCE_SHA="$TUNAOS_COVERAGE_SOURCE_SHA" \
	TUNAOS_COVERAGE_WORKFLOW_SHA="$TUNAOS_COVERAGE_WORKFLOW_SHA" \
	E2E_WALL_CLOCK_DEADLINE="$E2E_WALL_CLOCK_DEADLINE" \
	E2E_CHECKPOINT_STRICT=0 TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK=0 \
	scripts/iso-e2e.sh "${isos[0]}" --luks --output coverage-diagnostic --memory 10240 --timeout 1200
rc=$?
set -e
sudo chown -R "$(id -u):$(id -g)" coverage-diagnostic
outcome=failure
[[ "$rc" == "0" ]] && outcome=success
python3 scripts/iso-coverage-producer.py emit --identity coverage-diagnostic/coverage-identity.json \
	--evidence coverage-diagnostic/luks-evidence.log --cell-id skipjack:gnome:linux/amd64 \
	--source-sha "$DIAGNOSTIC_SOURCE_SHA" --workflow-sha "$DIAGNOSTIC_WORKFLOW_SHA" \
	--run-id "$GITHUB_RUN_ID" --attempt "$GITHUB_RUN_ATTEMPT" --outcome "$outcome" \
	>coverage-diagnostic/diagnostic-receipt.json
printf '%s\n' 'Diagnostic only: PR/head evidence is excluded from production coverage.' >coverage-diagnostic/NOT-PRODUCTION.txt
exit "$rc"
