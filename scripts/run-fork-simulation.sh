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
audit_root="${RUNNER_TEMP}/fork-simulation-audit"
act_homebrew_path="/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:/root/.linuxbrew/bin:/root/.linuxbrew/sbin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:${PATH}"
export PATH="$act_homebrew_path"

mkdir -p "$audit_root"
for persona in "$@"; do
	mapfile -t workflows < <(python3 scripts/fork-simulation.py matrix |
		jq -r --arg persona "$persona" '.include[] | select(.persona == $persona) | .workflow')
	for workflow in "${workflows[@]}"; do
		worktree="$(mktemp -d "${RUNNER_TEMP}/fork-simulation.XXXXXX")"
		audit_dir="$(mktemp -d "${audit_root}/XXXXXX")"
		git clone --quiet --local --no-hardlinks "$GITHUB_WORKSPACE" "$worktree/repo"
		cd "$worktree/repo"
		api_log="$audit_dir/api.log"
		unexpected_log="$audit_dir/unexpected.log"
		summary="$audit_dir/summary.md"
		: >"$api_log"
		: >"$unexpected_log"
		: >"$summary"
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
			--workflow "$workflow" \
			>"$worktree/event.json"

		# The synthetic event carries the isolated PR fixture. Mount both the
		# fixture executable and a dedicated audit directory into every act
		# container, so read-only lanes cannot contact GitHub and host checks
		# observe exactly what the container recorded.
		api_fixture=(
			--container-options
			"--volume=${GITHUB_WORKSPACE}/scripts/fork-simulation-gh:/usr/local/bin/gh:ro --volume=${audit_dir}:/run/fork-simulation-audit"
		)

		echo "::group::${workflow} — ${persona}"
		act_log="$audit_dir/act.log"
		set +e
		timeout 35m act pull_request \
			--workflows ".github/workflows/${workflow}" \
			--eventpath "$worktree/event.json" \
			--actor "$(python3 scripts/fork-simulation.py actor "$persona")" \
			--env "GITHUB_REPOSITORY=${REPOSITORY}" \
			--env "GITHUB_STEP_SUMMARY=/run/fork-simulation-audit/summary.md" \
			--env "PATH=${act_homebrew_path}" \
			--env "SIMULATION_PR=1" \
			--env "SIMULATION_API_LOG=/run/fork-simulation-audit/api.log" \
			--env "SIMULATION_UNEXPECTED_LOG=/run/fork-simulation-audit/unexpected.log" \
			--secret-file /dev/null \
			--secret "GITHUB_TOKEN=${SIMULATION_GITHUB_TOKEN}" \
			--env-file /dev/null \
			--concurrent-jobs 1 \
			--container-architecture linux/amd64 \
			--platform "ubuntu-latest=${ACT_IMAGE}" \
			--platform "ubuntu-24.04=${ACT_IMAGE}" \
			"${api_fixture[@]}" 2>&1 | tee "$act_log"
		rc="${PIPESTATUS[0]}"
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
		if [[ "$workflow:$persona" == "just-fix.yml:first-time-external" ]] &&
			! grep -Fq "This pull request comes from a fork" "$act_log"; then
			echo "fork fallback was not reached for the external just-fix simulation" >&2
			[[ $rc -ne 0 ]] || rc=65
		fi
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
		rm -rf "$worktree" "$audit_dir"
	done
done
