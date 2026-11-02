#!/usr/bin/env bash
# Manual lab only. Ordinary source CI must not enter the runtime path.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == --plan && "$#" -eq 1 ]]; then
	exec python3 "${SCRIPT_DIR}/mesa_3969.py" inputs
fi
# Admission precedes directory creation, dependency inspection and sudo.
python3 "${SCRIPT_DIR}/mesa_3969.py" admit --runtime >/dev/null
if [[ "$#" -ne 0 ]]; then
	echo 'usage: mesa-3969-guest.sh [--plan]; runtime requires MESA_3969_ARTIFACT_ID and MESA_3969_ARTIFACT_DIGEST' >&2
	exit 2
fi
ROOT="$(python3 "${SCRIPT_DIR}/mesa_3969.py" init-root --role runtime)"
cleanup() {
	local status=$?
	trap - EXIT
	if ! sudo -n --preserve-env=RUNNER_TEMP,GITHUB_REPOSITORY,GITHUB_REPOSITORY_ID,GITHUB_SHA,GITHUB_RUN_ID \
		python3 "${SCRIPT_DIR}/mesa_3969.py" cleanup-child --role runtime --child work; then
		if [[ "$status" != 130 && "$status" != 143 ]]; then
			status=1
		fi
	fi
	exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -m 0700 "${ROOT}/work"
printf 'evidence_path=%s\n' "${ROOT}/evidence" >>"${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
# The orchestrator never accepts a caller-supplied image, input directory or VM.
sudo -n --preserve-env=PATH,RUNNER_TEMP,GITHUB_ACTIONS,GITHUB_SERVER_URL,GITHUB_API_URL,GITHUB_EVENT_NAME,GITHUB_REPOSITORY,GITHUB_REPOSITORY_ID,GITHUB_SHA,GITHUB_RUN_ID,GITHUB_RUN_ATTEMPT,GITHUB_WORKFLOW_REF,GITHUB_WORKSPACE,GITHUB_TOKEN,REVIEWED_HEAD,MESA_3969_APPROVED_HEAD,MESA_3969_RUNTIME_APPROVED_HEAD,LAB_CONFIRM,MESA_3969_ARTIFACT_ID,MESA_3969_ARTIFACT_DIGEST,ImageOS,ImageVersion \
	timeout --kill-after=30s 3300s python3 "${SCRIPT_DIR}/mesa_3969_guest.py" run --root "$ROOT"
