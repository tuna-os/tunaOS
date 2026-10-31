#!/usr/bin/env bash
# Rebind a cell's live overlay to the base Promote just published.
#
# Called by reusable-build-image.yml's `Live overlay` job after Promote wrote
# the bare :<flavor> tag. live-overlay:<variant>-<flavor> carries
# org.tunaos.live-overlay.base-digest, and tacklebox refuses an overlay whose
# binding is not the base it selected (fail-closed since #425). A Promote that
# moves the base therefore makes the published overlay unusable until the
# overlay is rebuilt: skipjack:gnome was promoted within two hours of a hand
# publish of its overlay and browser builds of it were refused.
#
# Dispatches live-overlay.yml for exactly this cell, passing the index digest
# Promote wrote so the overlay run can prove it customized that index and not
# a newer one. Exits 0 without dispatching when the cell has nothing to rebind.
#
# Environment (all required unless noted):
#   EVENT_NAME, REPOSITORY, REF   github.event_name / github.repository / github.ref
#   PROMOTED                      "true" when Promote wrote the bare tag
#   BASE_INDEX_DIGEST             digest of the index Promote wrote there
#   VARIANT, FLAVOR               the cell (variant id, flavor id)
#   IMAGE_NAME, IMAGE_TAG         the repository and tag Promote wrote
#   GH_TOKEN                      token with actions:write (used by gh)
#   GH                            optional; the gh binary (tests stub it)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Overlays publish to ghcr.io/tuna-os/live-overlay (the token scope in
# live-overlay.yml), and only main publishes images (RFC 016's `publish`
# environment admits main alone).
PUBLISHING_REPOSITORY="tuna-os/tunaOS"
PUBLISHING_REF="refs/heads/main"
WORKFLOW="live-overlay.yml"
GH="${GH:-gh}"

skip() {
	echo "live overlay: not dispatching ${VARIANT:-?}:${FLAVOR:-?}: $*"
	exit 0
}

: "${EVENT_NAME:?}" "${REPOSITORY:?}" "${REF:?}" "${VARIANT:?}" "${FLAVOR:?}" "${IMAGE_NAME:?}" "${IMAGE_TAG:?}"

[[ "$EVENT_NAME" != "pull_request" ]] || skip "pull requests do not publish"
# GitHub compares repository names case-insensitively; so does this.
[[ "${REPOSITORY,,}" == "${PUBLISHING_REPOSITORY,,}" ]] ||
	skip "${REPOSITORY} is not ${PUBLISHING_REPOSITORY}; overlays publish to its registry only"
[[ "$REF" == "$PUBLISHING_REF" ]] || skip "${REF} is not ${PUBLISHING_REF}"
[[ "${PROMOTED:-}" == "true" ]] || skip "Promote did not write the bare tag"

# live-overlay.yml builds from <destination>/<variant>:<flavor>. A cell that
# publishes under another name (bonito-rawhide -> bonito:<flavor>-rawhide)
# did not move that base, so it has no binding to refresh here.
if [[ "$IMAGE_NAME" != "$VARIANT" || "$IMAGE_TAG" != "$FLAVOR" ]]; then
	skip "Promote wrote ${IMAGE_NAME}:${IMAGE_TAG}, not the overlay's base ${VARIANT}:${FLAVOR}"
fi

if [[ ! "${BASE_INDEX_DIGEST:-}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
	echo "::error::Promote reported a promotion but no index digest (got '${BASE_INDEX_DIGEST:-}'); cannot bind the live overlay" >&2
	exit 1
fi

cells="$(bash scripts/live-overlay-matrix.sh "$VARIANT" "$FLAVOR" | jq '.include | length')"
[[ "$cells" != "0" ]] || skip "not a live-overlay cell (scripts/live-overlay-matrix.sh selects none)"

# A disabled workflow refuses dispatch with a bare HTTP 422. Say what to do.
state="$("$GH" api "repos/${REPOSITORY}/actions/workflows/${WORKFLOW}" --jq .state)"
if [[ "$state" != "active" ]]; then
	echo "::error::${WORKFLOW} is ${state}, so ${VARIANT}:${FLAVOR}'s live overlay stays bound to the previous base. Re-enable it: gh workflow enable ${WORKFLOW} --repo ${REPOSITORY}" >&2
	exit 1
fi

for attempt in 1 2 3; do
	if "$GH" workflow run "$WORKFLOW" \
		--repo "$REPOSITORY" \
		--ref "${REF#refs/heads/}" \
		-f variant="$VARIANT" \
		-f flavors="$FLAVOR" \
		-f base_index_digest="$BASE_INDEX_DIGEST"; then
		echo "live overlay: dispatched ${WORKFLOW} for ${VARIANT}:${FLAVOR} bound to ${BASE_INDEX_DIGEST}"
		exit 0
	fi
	((attempt == 3)) || sleep $((attempt * 10))
done
echo "::error::could not dispatch ${WORKFLOW} for ${VARIANT}:${FLAVOR} after 3 attempts" >&2
exit 1
