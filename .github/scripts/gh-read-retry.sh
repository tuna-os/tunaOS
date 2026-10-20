#!/usr/bin/env bash
# Source for read-only gh queries. Never use this wrapper for mutations.
# README refresh run 39310599051 aborted on a single GitHub HTTP 502.
# Buffer each attempt: gh api --paginate may emit earlier pages before failing.
gh_read_retry() {
	local output errors rc attempt delay
	errors=$(mktemp) || return 1
	for attempt in 1 2 3; do
		if output=$(gh "$@" 2>"$errors"); then
			cat "$errors" >&2
			rm -f "$errors"
			printf '%s\n' "$output"
			return 0
		else
			rc=$?
		fi
		cat "$errors" >&2
		# Authentication/ordinary authorization errors are permanent. A 403
		# must not be retried without a trustworthy Retry-After/reset time.
		if grep -Eqi 'HTTP (401|403|404|422|429)|rate limit' "$errors"; then
			break
		fi
		# gh run list does not expose reset headers. Preserve a rate-limit
		# diagnostic rather than guessing a delay earlier than GitHub allows.
		if grep -Eqi 'HTTP 5[0-9][0-9]|connection (reset|refused)|TLS handshake timeout|i/o timeout|unexpected EOF|temporary failure in name resolution|network is unreachable|error connecting to api.github.com' "$errors"; then
			delay=$((5 * attempt))
		else
			break
		fi
		[[ "$attempt" -lt 3 ]] || break
		echo "::warning::GitHub read failed (attempt ${attempt}/3); retrying in ${delay}s" >&2
		sleep "$delay"
	done
	rm -f "$errors"
	return "$rc"
}
