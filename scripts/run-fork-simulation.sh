#!/usr/bin/env bash
# Execute the scoped PR workflows under act for the named contributor personas.
set -Eeuo pipefail

: "${GITHUB_WORKSPACE:?}"
: "${RUNNER_TEMP:?}"
: "${SIMULATION_GITHUB_TOKEN:?}"
: "${REPOSITORY:?}"
: "${ACT_IMAGE:?}"

results="${RESULTS_FILE:-${RUNNER_TEMP}/fork-simulation.tsv}"
: >"$results"

for persona in "$@"; do
	mapfile -t workflows < <(python3 scripts/fork-simulation.py matrix |
		jq -r --arg persona "$persona" '.include[] | select(.persona == $persona) | .workflow')
	for workflow in "${workflows[@]}"; do
		worktree="$(mktemp -d "${RUNNER_TEMP}/fork-simulation.XXXXXX")"
		git clone --quiet --local --no-hardlinks "$GITHUB_WORKSPACE" "$worktree/repo"
		cd "$worktree/repo"
		api_log="$worktree/repo/.fork-simulation-api.log"
		unexpected_log="$worktree/repo/.fork-simulation-unexpected.log"
		: >"$api_log"
		: >"$unexpected_log"
		git config user.name "Fork Simulation"
		git config user.email "fork-simulation@users.noreply.github.com"
		git switch --quiet --create "fork-simulation/${persona}"
		# Touch a path selected by each workflow's pull_request filter.
		printf '\n' >>".github/workflows/${workflow}"
		# Force just-fix through the fallback that replaced its unconditional
		# fork push. Other personas need no artificial formatter output.
		if [[ "$workflow:$persona" == "just-fix.yml:first-time-external" ]]; then
			printf '#!/usr/bin/env bash\nif true;then echo probe;fi\n' >fork-simulation-probe.sh
			git add fork-simulation-probe.sh
		fi
		git add ".github/workflows/${workflow}"
		git commit --quiet -m "test: synthetic untrusted head for ${persona}"
		head_sha="$(git rev-parse HEAD)"
		base_sha="$(git rev-parse HEAD^)"
		python3 scripts/fork-simulation.py event "$persona" \
			--repository "$REPOSITORY" --head-sha "$head_sha" --base-sha "$base_sha" \
			>"$worktree/event.json"

		# These workflows query or mutate PR state. Mount a strict gh fixture
		# over the runner binary so their synthetic PR #1 cannot read or modify
		# an unrelated real PR. Other workflows retain gh for read-only CI data.
		api_fixture=()
		case "$workflow" in
		drop-bot-review-requests.yml | pr-nudges.yml)
			api_fixture=(
				--container-options
				"--volume=${GITHUB_WORKSPACE}/scripts/fork-simulation-gh:/usr/local/bin/gh:ro"
			)
			;;
		esac

		echo "::group::${workflow} — ${persona}"
		set +e
		timeout 35m act pull_request \
			--workflows ".github/workflows/${workflow}" \
			--eventpath "$worktree/event.json" \
			--actor "$(python3 scripts/fork-simulation.py actor "$persona")" \
			--env "GITHUB_REPOSITORY=${REPOSITORY}" \
			--env "SIMULATION_PR=1" \
			--env "SIMULATION_API_LOG=.fork-simulation-api.log" \
			--env "SIMULATION_UNEXPECTED_LOG=.fork-simulation-unexpected.log" \
			"${api_fixture[@]}" \
			--secret-file /dev/null \
			--secret "GITHUB_TOKEN=${SIMULATION_GITHUB_TOKEN}" \
			--env-file /dev/null \
			--concurrent-jobs 1 \
			--container-architecture linux/amd64 \
			--platform "ubuntu-latest=${ACT_IMAGE}" \
			--platform "ubuntu-24.04=${ACT_IMAGE}"
		rc=$?
		set -e
		if [[ -s "$unexpected_log" ]]; then
			echo "fixture rejected unexpected synthetic API calls:" >&2
			cat "$unexpected_log" >&2
			[[ $rc -ne 0 ]] || rc=65
		fi
		expected_requests=()
		case "$workflow:$persona" in
		pr-nudges.yml:same-repo-contributor)
			expected_requests=(
				$'GET\trepos/'"${REPOSITORY}"'/pulls/1/files'
				$'GET\trepos/'"${REPOSITORY}"'/issues/1/comments'
				$'POST\trepos/'"${REPOSITORY}"'/issues/1/comments'
			)
			;;
		drop-bot-review-requests.yml:renovate)
			expected_requests=(
				$'GET\trepos/'"${REPOSITORY}"'/pulls/1'
				$'DELETE\trepos/'"${REPOSITORY}"'/pulls/1/requested_reviewers'
			)
			;;
		esac
		for request in "${expected_requests[@]}"; do
			if ! grep -Fqx "$request" "$api_log"; then
				echo "expected synthetic API call was not exercised: $request" >&2
				[[ $rc -ne 0 ]] || rc=65
			fi
		done
		if [[ "$persona" == first-time-external ]] &&
			grep -Eq $'^(POST|PUT|PATCH|DELETE)\t' "$api_log"; then
			echo "external simulation attempted a synthetic API mutation" >&2
			[[ $rc -ne 0 ]] || rc=65
		fi
		echo "::endgroup::"
		if [[ $rc -eq 0 ]]; then
			status=pass
		elif [[ $rc -eq 124 ]]; then
			status=timeout
		else
			status=fail
		fi
		printf '%s\t%s\t%s\t%s\n' "$workflow" "$persona" "$status" "$rc" >>"$results"
		cd "$GITHUB_WORKSPACE"
		rm -rf "$worktree"
	done
done
