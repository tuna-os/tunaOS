#!/usr/bin/env bash
# Authenticate only the registry clients a publish job needs.
#
# Required environment:
#   GITHUB_EVENT_NAME          event whose trust boundary is being evaluated
#   GITHUB_REPOSITORY_OWNER    owner used to identify the stock GHCR destination
#   PUBLISH_DESTINATION        resolved <registry>/<namespace>
#   REGISTRY_LOGIN_CLIENTS     space-separated client names
# Optional credentials for non-owner destinations:
#   PUBLISH_REGISTRY_USERNAME
#   PUBLISH_REGISTRY_TOKEN
#
# ghcr.io/<repository owner> deliberately keeps the stock github.actor /
# github.token path. Every other destination requires the complete custom pair.
set -euo pipefail

fail() {
	printf '::error::%s\n' "$*" >&2
	exit 1
}

event_name="${GITHUB_EVENT_NAME:-}"
[[ -n "$event_name" ]] || fail "GITHUB_EVENT_NAME is required"
case "$event_name" in
pull_request | pull_request_target)
	fail "registry authentication is disabled for untrusted pull request execution"
	;;
esac

destination="${PUBLISH_DESTINATION:-}"
repository_owner="${GITHUB_REPOSITORY_OWNER:-}"
[[ -n "$repository_owner" ]] || fail "GITHUB_REPOSITORY_OWNER is required"
stock_destination="ghcr.io/${repository_owner,,}"
# GitHub preserves an account's display casing in some contexts. OCI
# repository paths are lowercase, so normalize only the exact owner default;
# configured destinations must already satisfy the primary config grammar.
if [[ "${destination,,}" == "$stock_destination" ]]; then
	destination="$stock_destination"
fi
# Match [build.publish] exactly: localhost or a dotted lowercase host (including
# dotted IPv4 syntax). Bracketed IPv6 and private single-label hosts are
# intentionally outside the primary configuration contract.
registry_re='(localhost|[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+)(:[0-9]{1,5})?'
namespace_component='[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*'
if [[ ! "$destination" =~ ^${registry_re}/${namespace_component}(/${namespace_component})*$ ]]; then
	fail "invalid publish destination; expected a lowercase <registry>/<namespace> OCI path"
fi

registry="${destination%%/*}"
if [[ "$registry" == *:* ]]; then
	port="${registry##*:}"
	((10#$port >= 1 && 10#$port <= 65535)) ||
		fail "invalid publish destination; registry port must be between 1 and 65535"
fi
custom_username="${PUBLISH_REGISTRY_USERNAME:-}"
custom_token="${PUBLISH_REGISTRY_TOKEN:-}"

if [[ -n "$custom_username" && -z "$custom_token" ]] ||
	[[ -z "$custom_username" && -n "$custom_token" ]]; then
	fail "PUBLISH_REGISTRY_USERNAME and PUBLISH_REGISTRY_TOKEN must be configured together"
fi

if [[ "$destination" == "$stock_destination" ]]; then
	if [[ -n "$custom_username" ]]; then
		fail "custom publish credentials conflict with the stock ${stock_destination} destination"
	fi
	username="${GITHUB_ACTOR:-}"
	token="${GITHUB_TOKEN:-}"
	credential_source="GitHub owner"
	[[ -n "$username" && -n "$token" ]] || fail "github.actor and github.token are required for ${stock_destination}"
else
	[[ -n "$custom_username" && -n "$custom_token" ]] ||
		fail "${destination} requires PUBLISH_REGISTRY_USERNAME and PUBLISH_REGISTRY_TOKEN"
	username="$custom_username"
	token="$custom_token"
	credential_source="custom publish"
fi

if [[ "$credential_source" == "custom publish" &&
	! "$username" =~ ^[A-Za-z0-9][A-Za-z0-9_.@+-]*$ ]]; then
	fail "registry username contains unsupported characters"
fi
if [[ "$username" == *$'\n'* || "$username" == *$'\r'* ]]; then
	fail "registry username must be a single line"
fi
if [[ "$token" == *$'\n'* || "$token" == *$'\r'* ]]; then
	fail "registry token must be a single line"
fi

max_retries="${REGISTRY_LOGIN_MAX_RETRIES:-3}"
[[ "$max_retries" =~ ^[1-9]$|^10$ ]] || fail "REGISTRY_LOGIN_MAX_RETRIES must be between 1 and 10"
read -r -a clients <<<"${REGISTRY_LOGIN_CLIENTS:-}"
[[ "${#clients[@]}" -gt 0 ]] || fail "REGISTRY_LOGIN_CLIENTS must name at least one client"

login_client() {
	local client="$1" attempt
	for ((attempt = 1; attempt <= max_retries; attempt++)); do
		case "$client" in
		docker)
			if printf '%s\n' "$token" | docker login --username "$username" --password-stdin "$registry"; then
				return 0
			fi
			;;
		podman)
			if printf '%s\n' "$token" | podman login --username "$username" --password-stdin "$registry"; then
				return 0
			fi
			;;
		sudo-podman)
			sudo rm -f /dev/shm/libpod_lock* 2>/dev/null || true
			sudo podman system renumber >/dev/null 2>&1 || true
			if printf '%s\n' "$token" | sudo podman login --username "$username" --password-stdin "$registry"; then
				return 0
			fi
			;;
		cosign)
			if printf '%s\n' "$token" | cosign login --username "$username" --password-stdin "$registry"; then
				return 0
			fi
			;;
		skopeo)
			if printf '%s\n' "$token" | skopeo login --username "$username" --password-stdin "$registry"; then
				return 0
			fi
			;;
		sudo-skopeo)
			if printf '%s\n' "$token" | sudo skopeo login --username "$username" --password-stdin "$registry"; then
				return 0
			fi
			;;
		*)
			fail "unsupported registry login client: ${client}"
			;;
		esac
		if [[ "$attempt" -lt "$max_retries" ]]; then
			printf '::warning::%s registry login failed (attempt %s/%s); retrying...\n' \
				"$client" "$attempt" "$max_retries" >&2
			sleep $((attempt * 5))
		fi
	done
	fail "${client} registry login failed after ${max_retries} attempts"
}

for client in "${clients[@]}"; do
	login_client "$client"
	printf 'Authenticated %s to %s with %s credentials.\n' "$client" "$registry" "$credential_source"
done
