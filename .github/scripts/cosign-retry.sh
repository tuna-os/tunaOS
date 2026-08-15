#!/usr/bin/env bash
# cosign-retry.sh — ride out a Sigstore outage, fail fast on everything else.
#
# Source this and call `cosign_retry cosign sign ...`. Sourced rather than
# executed so callers keep `set -euo pipefail` semantics and can count
# successes in their own shell.
#
# Why a deadline and not an attempt count. The previous version retried a
# fixed six times with a doubling sleep, which is a *budget* of 15m45s but
# reads like a *duration* only if every attempt is instant. Two things went
# wrong with it on the 08-14/08-15 nightlies:
#
#   1. Rekor returned 502 for longer than the budget. Run 31858324517
#      (albacore) burned all six attempts on `cosign attest` and failed at
#      16m19s, and every one of that variant's twelve Promote jobs was
#      skipped as a result — for images that had built, pushed and passed
#      their gates.
#   2. The loop slept *after* the final attempt. The 480s following
#      "attempt 6/6" bought nothing and made every failing job eight
#      minutes longer than it needed to be.
#
# A wall-clock deadline says what we actually mean ("keep trying for N
# minutes"), and capping the backoff means a long outage is probed every
# two minutes instead of once at the eight-minute mark — recovery is
# noticed sooner, not later.
#
# Fail-fast matters as much as the retrying. A bad --certificate-identity,
# a missing predicate file or a registry 403 are not going to fix
# themselves, and the old loop spent the full budget on them before saying
# so. Only errors that name a Sigstore endpoint *and* look like
# unavailability are retried.

# Retry budget in minutes for a single cosign invocation.
: "${SIGN_DEADLINE_MINUTES:=40}"
# Ceiling on the backoff between attempts, in seconds.
: "${SIGN_BACKOFF_CAP_SECONDS:=120}"

# _cosign_transient <file> — true when the captured output is a Sigstore
# availability failure rather than a real error.
_cosign_transient() {
	local out="$1"
	grep -qEi 'rekor\.sigstore\.dev|fulcio\.sigstore\.dev|tuf-repo-cdn\.sigstore\.dev|timestamp\.sigstore\.dev' "$out" || return 1
	grep -qEi 'status (408|425|429|5[0-9][0-9])|Bad Gateway|Service Unavailable|Gateway Time-?out|Internal Server Error|Too Many Requests|context deadline exceeded|connection reset|connection refused|unexpected EOF|i/o timeout|TLS handshake timeout|no such host' "$out"
}

# cosign_retry <command...> — run until it succeeds, the error turns out to
# be non-transient, or the deadline passes.
cosign_retry() {
	local attempt=1 backoff=15 rc=0 now remaining out deadline
	out="$(mktemp)"
	deadline=$(( $(date +%s) + SIGN_DEADLINE_MINUTES * 60 ))

	while :; do
		rc=0
		"$@" >"$out" 2>&1 || rc=$?
		if [ "$rc" -eq 0 ]; then
			cat "$out"
			rm -f "$out"
			return 0
		fi

		cat "$out" >&2

		if ! _cosign_transient "$out"; then
			echo "::error::${2:-$1} failed with a non-transient error (exit ${rc}); not retrying." >&2
			rm -f "$out"
			return "$rc"
		fi

		now="$(date +%s)"
		remaining=$(( deadline - now ))
		if [ "$remaining" -le "$backoff" ]; then
			# Marker, not prose: rerun-infra-failures.yml greps job logs for
			# SIGSTORE_OUTAGE to tell "Sigstore was down" apart from "this
			# build is broken", and only re-runs the former.
			echo "::error::SIGSTORE_OUTAGE: ${2:-$1} still failing after ${SIGN_DEADLINE_MINUTES}m of Sigstore unavailability; giving up." >&2
			rm -f "$out"
			return "$rc"
		fi

		echo "::warning::${2:-$1} failed (attempt ${attempt}, transient Sigstore error); retrying in ${backoff}s ($(( remaining / 60 ))m of budget left)..." >&2
		sleep "$backoff"
		attempt=$(( attempt + 1 ))
		backoff=$(( backoff * 2 ))
		if [ "$backoff" -gt "$SIGN_BACKOFF_CAP_SECONDS" ]; then
			backoff="$SIGN_BACKOFF_CAP_SECONDS"
		fi
	done
}
