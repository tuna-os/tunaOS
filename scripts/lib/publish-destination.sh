#!/usr/bin/env bash
# Resolve where TunaOS images publish: a registry host and a namespace.
#
# A fork names its own destination in tunaos.toml:
#
#   [build.publish]
#   registry = "quay.io"
#   namespace = "acme"
#
# Each field resolves independently, highest precedence first:
#   1. IMAGE_REGISTRY / REPO_ORGANIZATION in the environment (operator override)
#   2. [build.publish] in tunaos.toml, read from the generated build config
#   3. the GitHub repository owner (namespace only), so a GitHub fork that sets
#      nothing still publishes under its own account
#   4. ghcr.io and tuna-os
#
# The stock tunaos.toml omits [build.publish], so TunaOS resolves to
# ghcr.io/tuna-os exactly as before and the file stays fork-neutral.

# tunaos_publish_destination <build-config-path>
# Prints "<registry> <namespace>" on one line.
tunaos_publish_destination() {
	local config="${1:-}" yq="${YQ:-yq}" registry="${IMAGE_REGISTRY:-}" namespace="${REPO_ORGANIZATION:-}"
	# CI jobs carry the combined form (IMAGE_REGISTRY=ghcr.io/<owner>); the
	# build engine uses a bare host. Accept both.
	if [[ "$registry" == */* ]]; then
		[[ -n "$namespace" ]] || namespace="${registry#*/}"
		registry="${registry%%/*}"
	fi
	if [[ -n "$config" && (-z "$registry" || -z "$namespace") ]]; then
		[[ -n "$registry" ]] || registry="$("$yq" -r '.config.publish.registry // ""' "$config")"
		[[ -n "$namespace" ]] || namespace="$("$yq" -r '.config.publish.namespace // ""' "$config")"
	fi
	[[ -n "$namespace" ]] || namespace="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
	# Registries reject uppercase repository paths; GitHub owners may have it.
	printf '%s %s\n' "${registry:-ghcr.io}" "${namespace,,}"
}
