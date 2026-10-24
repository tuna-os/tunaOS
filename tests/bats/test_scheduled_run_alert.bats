#!/usr/bin/env bats
# Behaviour of the step in .github/workflows/scheduled-run-alert.yml — the one
# listener that keeps a `ci-failure` tracking issue per scheduled workflow
# (tunaOS#3307).
#
# The step is shell, and none of what it decides can be read off the YAML: which
# branch a conclusion takes, how a late `workflow_run` delivery is reconciled
# against the run history, how the issue is matched among titles that are
# prefixes of each other, and what the body says when the jobs API does not
# answer. So the `run:` block is extracted from the real workflow (extracted,
# not restated — a rewritten step stops being covered here) and executed with
# `gh` stubbed on PATH. The stub answers each call with a fixture and records
# every invocation, so the requests themselves are assertable too.
#
# Two cases exist because a reviewer named them on PR #3874:
#   - an out-of-order delivery must not write. rerun-infra-failures.yml re-runs
#     the failed jobs of a red scheduled run 45 minutes later, so an OLD run
#     completes again as attempt 2 after the next run has already concluded.
#   - the jobs query must not ask for 100 jobs per page. This repository's
#     largest runs answer that page size with HTTP 502 every time (row 56 of
#     docs/ci-troubleshooting.md), and a swallowed failure used to be reported
#     as "no failed job", which is a measurement nobody made.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/scheduled-run-alert.yml"

setup() {
	command -v jq >/dev/null || skip "jq is required to drive the gh stub"
	python3 -c 'import yaml' 2>/dev/null || skip "PyYAML is required to extract the step"

	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="${TEST_ROOT}/bin"
	mkdir -p "$STUB_BIN"

	STEP="${TEST_ROOT}/step.sh"
	python3 - "$WORKFLOW" >"$STEP" <<'PY'
import sys

import yaml

doc = yaml.safe_load(open(sys.argv[1]))
(job,) = doc["jobs"].values()
sys.stdout.write("".join(step.get("run", "") for step in job["steps"]))
PY
	[ -s "$STEP" ]

	export GH_LOG="${TEST_ROOT}/gh.log"
	export BODY_FILE="${TEST_ROOT}/body.md"
	: >"$GH_LOG"

	cat >"${STUB_BIN}/gh" <<'STUB'
#!/usr/bin/env bash
# Answers the four calls the step makes, from fixtures in the environment, and
# records the argv of every one of them.
printf '%s\n' "$*" >>"$GH_LOG"
sub="$1"
shift
case "$sub" in
api)
	url=""
	filter=""
	while (($#)); do
		case "$1" in
		--jq)
			filter="$2"
			shift 2
			;;
		--paginate) shift ;;
		*)
			url="$1"
			shift
			;;
		esac
	done
	case "$url" in
	*/actions/workflows/*/runs*)
		if [[ "${RUNS_QUERY_FAILS:-0}" == 1 ]]; then
			echo "gh: HTTP 500: Server Error ($url)" >&2
			exit 1
		fi
		printf '%s' "${RUNS_JSON}" | jq -r "$filter"
		;;
	*/jobs*)
		if [[ "${JOBS_QUERY_FAILS:-0}" == 1 ]]; then
			echo "gh: HTTP 502: Server Error ($url)" >&2
			exit 1
		fi
		printf '%s' "${JOBS_JSON}" | jq -r "$filter"
		;;
	*)
		echo "stub gh: unexpected api url: $url" >&2
		exit 64
		;;
	esac
	;;
issue)
	action="$1"
	shift
	case "$action" in
	list) printf '%s' "${ISSUES_JSON}" ;;
	create | comment | close)
		while (($#)); do
			[[ "$1" == "--body-file" ]] && cp "$2" "$BODY_FILE"
			shift
		done
		echo "stub: issue ${action}"
		;;
	*)
		echo "stub gh: unexpected issue action: $action" >&2
		exit 64
		;;
	esac
	;;
*)
	echo "stub gh: unexpected subcommand: $sub" >&2
	exit 64
	;;
esac
STUB
	chmod +x "${STUB_BIN}/gh"

	# The default event: run 10, attempt 1 of "Build Bonito" concluded failure,
	# it is the newest scheduled run, nothing is open, and two of its jobs are red.
	export GH_TOKEN=stub-token
	export GH_REPO=tuna-os/tunaos
	export WORKFLOW_NAME="Build Bonito"
	export WORKFLOW_ID=4242
	export CONCLUSION=failure
	export RUN_ID=9001
	export RUN_URL="https://github.com/tuna-os/tunaos/actions/runs/9001"
	export RUN_NUMBER=10
	export RUN_ATTEMPT=1
	export HEAD_BRANCH=main
	export HEAD_SHA=deadbeef
	export ISSUES_JSON='[]'
	export RUNS_JSON='{"workflow_runs":[{"run_number":10,"run_attempt":1,"conclusion":"failure"}]}'
	export JOBS_JSON='{"jobs":[
	  {"name":"Build yellowfin:gnome","conclusion":"failure","html_url":"https://x/1"},
	  {"name":"Build marlin:kde","conclusion":"success","html_url":"https://x/2"},
	  {"name":"Promote","conclusion":"timed_out","html_url":"https://x/3"}
	]}'
	export RUNS_QUERY_FAILS=0
	export JOBS_QUERY_FAILS=0
}

teardown() {
	[ -n "${TEST_ROOT:-}" ] && rm -rf "$TEST_ROOT"
	return 0
}

run_step() {
	PATH="${STUB_BIN}:${PATH}" run bash "$STEP"
}

# The write calls, in order, one per line ("create", "comment", "close").
writes() {
	grep -oE '^issue (create|comment|close)' "$GH_LOG" | awk '{print $2}'
}

@test "a red scheduled run with nothing open files one issue" {
	run_step
	[ "$status" -eq 0 ]
	[ "$(writes)" = "create" ]

	grep -qF -- '--title [operations] Build Bonito scheduled run failed' "$GH_LOG"
	grep -qF -- '--label ci-failure' "$GH_LOG"

	# The body carries what triage would otherwise have to fetch: the run, the
	# ref, and which legs went red (the green one is not named).
	grep -qF 'concluded **failure**' "$BODY_FILE"
	grep -qF '[9001](https://github.com/tuna-os/tunaos/actions/runs/9001) (attempt 1)' "$BODY_FILE"
	grep -qF '`main` at `deadbeef`' "$BODY_FILE"
	grep -qF '`Build yellowfin:gnome` (failure): https://x/1' "$BODY_FILE"
	grep -qF '`Promote` (timed_out): https://x/3' "$BODY_FILE"
	run grep -cF 'Build marlin:kde' "$BODY_FILE"
	[ "$status" -ne 0 ]
}

@test "a repeat red run comments on the open issue instead of opening a second" {
	export ISSUES_JSON='[{"number":99,"title":"[operations] Build Bonito scheduled run failed"}]'
	run_step
	[ "$status" -eq 0 ]
	[ "$(writes)" = "comment" ]
	grep -qE '^issue comment 99' "$GH_LOG"
}

@test "an open issue for a workflow whose name is a prefix is not mistaken for this one" {
	# "Build Bonito" is a prefix of "Build Bonito-rawhide": a search-term match
	# would comment on the rawhide incident and leave bonito untracked.
	export ISSUES_JSON='[{"number":77,"title":"[operations] Build Bonito-rawhide scheduled run failed"}]'
	run_step
	[ "$status" -eq 0 ]
	[ "$(writes)" = "create" ]
}

@test "the next green scheduled run closes the issue" {
	export CONCLUSION=success
	export RUNS_JSON='{"workflow_runs":[{"run_number":10,"run_attempt":1,"conclusion":"success"}]}'
	export ISSUES_JSON='[{"number":99,"title":"[operations] Build Bonito scheduled run failed"}]'
	run_step
	[ "$status" -eq 0 ]
	[ "$(writes)" = "close" ]
	grep -qE '^issue close 99' "$GH_LOG"
	grep -qF -- '--reason completed' "$GH_LOG"
}

@test "a green run with nothing open writes nothing" {
	export CONCLUSION=success
	export RUNS_JSON='{"workflow_runs":[{"run_number":10,"run_attempt":1,"conclusion":"success"}]}'
	run_step
	[ "$status" -eq 0 ]
	[ -z "$(writes)" ]
	[[ "$output" == *"nothing open"* ]]
}

@test "a late green event does not close an issue a newer red run owns" {
	# The 45-minute re-run of run 10 goes green and completes as attempt 2,
	# after run 11 has already failed and opened the issue. Closing here would
	# say "recovered" about a workflow that is red right now.
	export CONCLUSION=success
	export RUN_ATTEMPT=2
	export RUNS_JSON='{"workflow_runs":[
	  {"run_number":11,"run_attempt":1,"conclusion":"failure"},
	  {"run_number":10,"run_attempt":2,"conclusion":"success"}
	]}'
	export ISSUES_JSON='[{"number":99,"title":"[operations] Build Bonito scheduled run failed"}]'
	run_step
	[ "$status" -eq 0 ]
	[ -z "$(writes)" ]
	[[ "$output" == *"is behind"* ]]
}

@test "a late red event does not re-open an incident a newer green run cleared" {
	export RUN_NUMBER=9
	export RUNS_JSON='{"workflow_runs":[
	  {"run_number":10,"run_attempt":1,"conclusion":"success"},
	  {"run_number":9,"run_attempt":1,"conclusion":"failure"}
	]}'
	run_step
	[ "$status" -eq 0 ]
	[ -z "$(writes)" ]
}

@test "an event for an attempt a later attempt of the same run superseded writes nothing" {
	export RUNS_JSON='{"workflow_runs":[{"run_number":10,"run_attempt":2,"conclusion":"success"}]}'
	run_step
	[ "$status" -eq 0 ]
	[ -z "$(writes)" ]
}

@test "a newer cancelled run does not supersede this one" {
	# A concurrency group or a human cancelling run 11 says nothing about the
	# health of the workflow; run 10's failure is still the current state.
	export RUNS_JSON='{"workflow_runs":[
	  {"run_number":11,"run_attempt":1,"conclusion":"cancelled"},
	  {"run_number":10,"run_attempt":1,"conclusion":"failure"}
	]}'
	run_step
	[ "$status" -eq 0 ]
	[ "$(writes)" = "create" ]
}

@test "an unreadable run history still files the alert, and says it is unreconciled" {
	# Reconciliation that fails closed would drop the incident entirely, which
	# is the silence this listener exists to end.
	export RUNS_QUERY_FAILS=1
	run_step
	[ "$status" -eq 0 ]
	[ "$(writes)" = "create" ]
	[[ "$output" == *"::warning::"* ]]
	[[ "$output" == *"unreconciled"* ]]
}

@test "the jobs query asks for 50 per page, on the attempt the event is about" {
	# per_page=100 is answered with HTTP 502 on this repository's largest runs,
	# every attempt (row 56 of docs/ci-troubleshooting.md).
	export RUN_ATTEMPT=2
	export RUNS_JSON='{"workflow_runs":[{"run_number":10,"run_attempt":2,"conclusion":"failure"}]}'
	run_step
	[ "$status" -eq 0 ]
	grep -qF 'actions/runs/9001/attempts/2/jobs?per_page=50' "$GH_LOG"
	run grep -F 'per_page=100' "$GH_LOG"
	[ "$status" -ne 0 ]
}

@test "an unanswered jobs query is reported as unknown, not as no failed job" {
	export JOBS_QUERY_FAILS=1
	run_step
	[ "$status" -eq 0 ]
	[ "$(writes)" = "create" ]
	grep -qF 'jobs API did not answer' "$BODY_FILE"
	run grep -F 'no failed job reported' "$BODY_FILE"
	[ "$status" -ne 0 ]
}

@test "a run that reported no red job says so plainly" {
	export CONCLUSION=timed_out
	export JOBS_JSON='{"jobs":[{"name":"Promote","conclusion":"success","html_url":"https://x/9"}]}'
	run_step
	[ "$status" -eq 0 ]
	grep -qF 'no failed job reported' "$BODY_FILE"
	grep -qF 'concluded **timed_out**' "$BODY_FILE"
}
