#!/usr/bin/env bash
# Log one tool in to a non-owner publish destination (#3801, RFC 016).
#
# Usage: publish-registry-login.sh <docker|podman|sudo-podman|skopeo|sudo-skopeo|cosign> <registry>/<namespace>
#
# Step environment:
#   TUNAOS_PUBLISH_MODE      must be registry-secret (from scripts/publish-credential.py)
#   TUNAOS_PUBLISH_USERNAME  secrets.TUNAOS_PUBLISH_USERNAME
#   TUNAOS_PUBLISH_PASSWORD  secrets.TUNAOS_PUBLISH_PASSWORD
#
# The owner path (ghcr.io/<owner>) keeps its existing GITHUB_TOKEN steps and
# never calls this script. The password reaches the tool on stdin only, never
# in argv or output. podman and skopeo store the entry under
# <registry>/<namespace> (containers-auth.json(5) namespace keys), so a ghcr.io
# GITHUB_TOKEN entry for upstream pulls stays usable. docker (read by oras) and
# cosign store entries per registry host. No workflow calls this script until
# RFC 016 is approved.
set -euo pipefail

tool="${1:-}"
scope="${2:-}"
username="${TUNAOS_PUBLISH_USERNAME:-}"
password="${TUNAOS_PUBLISH_PASSWORD:-}"

die() {
	printf '::error::publish login: %s\n' "$1" >&2
	exit 1
}
[[ "$tool" != *$'\n'* && "$tool" != *$'\r'* ]] ||
	die "tool contains a line break"


[[ "${TUNAOS_PUBLISH_MODE:-}" == registry-secret ]] ||
	die "TUNAOS_PUBLISH_MODE is not registry-secret; the owner path uses GITHUB_TOKEN"
registry_re='^(localhost|[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+)(:[0-9]{1,5})?$'
namespace_component_re='^[a-z0-9]+([._][a-z0-9]+|__[a-z0-9]+|-+[a-z0-9]+)*$'
[[ "$scope" == */* && "$scope" != */ && "$scope" != *//* &&
	"$scope" != *$'\n'* && "$scope" != *$'\r'* ]] ||
	die "scope must be the <registry>/<namespace> printed by publish-credential.py"
registry="${scope%%/*}"
namespace="${scope#*/}"
[[ "$registry" =~ $registry_re ]] ||
	die "scope must be the <registry>/<namespace> printed by publish-credential.py"
if [[ "$registry" == *:* ]]; then
	port="${registry##*:}"
	((10#$port <= 65535)) ||
		die "scope must be the <registry>/<namespace> printed by publish-credential.py"
fi
IFS='/' read -r -a namespace_components <<<"$namespace"
for component in "${namespace_components[@]}"; do
	[[ "$component" =~ $namespace_component_re ]] ||
		die "scope must be the <registry>/<namespace> printed by publish-credential.py"
done
[[ -n "$username" && -n "$password" ]] ||
	die "TUNAOS_PUBLISH_USERNAME and TUNAOS_PUBLISH_PASSWORD must both be set"
[[ "$username" =~ ^[A-Za-z0-9][A-Za-z0-9._@+-]*$ ]] ||
	die "TUNAOS_PUBLISH_USERNAME may contain only letters, digits and . _ @ + -"
[[ "$password" != *$'\n'* && "$password" != *$'\r'* ]] ||
	die "TUNAOS_PUBLISH_PASSWORD contains a line break"

case "$tool" in
podman | skopeo) command=("$tool" login "--username=$username" --password-stdin "$scope") ;;
sudo-podman | sudo-skopeo) command=(sudo "${tool#sudo-}" login "--username=$username" --password-stdin "$scope") ;;
docker | cosign) command=("$tool" login "--username=$username" --password-stdin "$registry") ;;
*) die "unknown tool '${tool}'; expected docker, podman, sudo-podman, skopeo, sudo-skopeo or cosign" ;;
esac

# printf is a shell builtin: the password is never an argument of a process.
printf '%s' "$password" | "${command[@]}" >/dev/null
echo "publish login: ${tool} -> ${scope}" >&2
