#!/usr/bin/env bash
# Rebuild a cell's hardware overlays on the parent Promote just published.
#
# Called by reusable-build-image.yml's `Hardware overlays` job after Promote
# wrote the bare :<flavor> tag. A hardware-profile flavor (`hardware = "<id>"`
# and `parent = "<flavor>"` in tunaos.toml, e.g. bonito:gnome-x13s) is that
# parent plus one profile, and its users follow it with `bootc upgrade`. Built
# on a schedule it lagged the parent by up to a week, and built in the same
# nightly it chained on a -candidate parent that might never be promoted.
# build-variant.yml therefore leaves these flavors out of every matrix that
# does not name them, and this script names them: one build-<variant>.yml
# dispatch per hardware flavor whose parent is the promoted cell. The overlay
# build pins the parent tag to its index digest and records it in the label
# org.tunaos.hardware-overlay.base-digest (scripts/build-image-inner.sh).
#
# Exits 0 without dispatching when the cell has no hardware overlay.
#
# Environment (all required unless noted):
#   EVENT_NAME, REPOSITORY, REF   github.event_name / github.repository / github.ref
#   PROMOTED                      "true" when Promote wrote the bare tag
#   VARIANT, FLAVOR               the promoted cell (variant id, flavor id)
#   GH                            optional; the gh binary (tests stub it)
#   RETRY_SLEEP                   optional; seconds between dispatch retries (10)
#   TUNAOS_BUILD_CONFIG           optional; the generated build config
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# shellcheck source=lib/build-config.sh
source scripts/lib/build-config.sh

# Only main publishes images (RFC 016's `publish` environment admits main
# alone), so only a main Promote has a published parent to rebuild on.
PUBLISHING_REPOSITORY="tuna-os/tunaOS"
PUBLISHING_REF="refs/heads/main"
GH="${GH:-gh}"

skip() {
	echo "hardware overlays: not dispatching for ${VARIANT:-?}:${FLAVOR:-?}: $*"
	exit 0
}

: "${EVENT_NAME:?}" "${REPOSITORY:?}" "${REF:?}" "${VARIANT:?}" "${FLAVOR:?}"

[[ "$EVENT_NAME" != "pull_request" ]] || skip "pull requests do not publish"
# GitHub compares repository names case-insensitively; so does this.
[[ "${REPOSITORY,,}" == "${PUBLISHING_REPOSITORY,,}" ]] ||
	skip "${REPOSITORY} is not ${PUBLISHING_REPOSITORY}"
[[ "$REF" == "$PUBLISHING_REF" ]] || skip "${REF} is not ${PUBLISHING_REF}"
[[ "${PROMOTED:-}" == "true" ]] || skip "Promote did not write the bare tag"

config="$(tunaos_build_config)"
mapfile -t overlays < <(VARIANT_ID="$VARIANT" PARENT_ID="$FLAVOR" yq -r '
	.variants[] | select(.id == strenv(VARIANT_ID)) | .flavors[]
	| select((.hardware // "") != "" and .parent == strenv(PARENT_ID) and (.build_image // false))
	| .id' "$config")
((${#overlays[@]})) || skip "no enabled hardware flavor has parent ${FLAVOR}"

workflow="build-${VARIANT}.yml"
failed=0
for overlay in "${overlays[@]}"; do
	dispatched=0
	for attempt in 1 2 3; do
		if "$GH" workflow run "$workflow" \
			--repo "$REPOSITORY" \
			--ref "${REF#refs/heads/}" \
			-f flavor="$overlay"; then
			echo "hardware overlays: dispatched ${workflow} flavor=${overlay} on the promoted ${VARIANT}:${FLAVOR}"
			dispatched=1
			break
		fi
		((attempt == 3)) || sleep $((attempt * ${RETRY_SLEEP:-10}))
	done
	if ((! dispatched)); then
		echo "::error::could not dispatch ${workflow} flavor=${overlay} after 3 attempts; ${VARIANT}:${overlay} stays on the previous ${FLAVOR}" >&2
		failed=1
	fi
done
exit "$failed"
