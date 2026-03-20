#!/usr/bin/env bash
# Manage a local OCI registry for TunaOS development.
#
# Usage: scripts/registry.sh <subcommand> [variant] [flavor] [port] [host]
#
# Subcommands:
#   start [port=5000] [host=127.0.0.1]          — start local registry container
#   stop                                          — stop and remove registry container
#   push <variant> <flavor> [port] [host]         — push image to registry
#   pull <variant> <flavor> [port] [host]         — pull image from registry
#   list [port=5000] [host=127.0.0.1]             — list repositories in registry

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CMD="${1:-start}"
VARIANT="${2:-}"
FLAVOR="${3:-gnome}"
PORT="${4:-5000}"
HOST="${5:-127.0.0.1}"

case "$CMD" in
start)
	if podman container exists tuna-registry 2>/dev/null; then
		echo "Registry already running at ${HOST}:${PORT}"
	else
		podman run -d \
			--name tuna-registry \
			-p "${HOST}:${PORT}:5000" \
			docker.io/library/registry:2
		echo "Registry started at ${HOST}:${PORT}"
	fi
	echo ""
	echo "Add to /etc/containers/registries.conf or ~/.config/containers/registries.conf:"
	echo "  [[registry]]"
	echo "  location = \"${HOST}:${PORT}\""
	echo "  insecure = true"
	;;

stop)
	podman stop tuna-registry 2>/dev/null || true
	podman rm tuna-registry 2>/dev/null || true
	echo "Registry stopped and removed."
	;;

push)
	if [[ -z "$VARIANT" ]]; then
		echo "Usage: registry.sh push <variant> <flavor> [port] [host]" >&2
		exit 1
	fi
	podman push --tls-verify=false \
		"localhost/${VARIANT}:${FLAVOR}" \
		"${HOST}:${PORT}/${VARIANT}:${FLAVOR}"
	;;

pull)
	if [[ -z "$VARIANT" ]]; then
		echo "Usage: registry.sh pull <variant> <flavor> [port] [host]" >&2
		exit 1
	fi
	podman pull --tls-verify=false "${HOST}:${PORT}/${VARIANT}:${FLAVOR}"
	podman tag "${HOST}:${PORT}/${VARIANT}:${FLAVOR}" "localhost/${VARIANT}:${FLAVOR}"
	;;

list)
	curl -s "http://${HOST}:${PORT}/v2/_catalog" | jq .
	;;

*)
	echo "Usage: registry.sh <start|stop|push|pull|list> [args...]" >&2
	exit 1
	;;
esac
