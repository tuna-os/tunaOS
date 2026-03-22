#!/usr/bin/env bash
# VM run/demo helpers.
#
# Usage: scripts/run-vm.sh <subcommand> [args...]
#
# Subcommands:
#   run <type> <variant> [flavor] [iso_file]  — run a VM using the QEMU container
#   demo <variant> [flavor] [rebuild]          — build qcow2 and boot it
#   demo-iso <variant> [flavor] [rebuild]      — build live ISO and boot it

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CMD="${1:-}"
shift || true

case "$CMD" in
run)
	TYPE="${1:-}"
	VARIANT="${2:-}"
	FLAVOR="${3:-gnome}"
	ISO_FILE="${4:-}"

	set -x

	image_file=""
	if [[ -n "$ISO_FILE" ]]; then
		image_file="$ISO_FILE"
	elif [[ "$TYPE" == "iso" ]]; then
		FOUND_ISO=$(find . -maxdepth 1 -name "${VARIANT}-${FLAVOR}-*.iso" | head -1)
		if [[ -f "$FOUND_ISO" ]]; then image_file="$FOUND_ISO"; else image_file="${VARIANT}.iso"; fi
	else
		if [[ -f "${VARIANT}-${FLAVOR}.qcow2" ]]; then
			image_file="${VARIANT}-${FLAVOR}.qcow2"
		else image_file="${VARIANT}.qcow2"; fi
	fi

	if [[ ! -f "${image_file}" ]]; then
		if [[ -n "$ISO_FILE" ]]; then
			echo "ISO not found: ${ISO_FILE}"
			exit 1
		fi
		echo "Image ${image_file} not found. Building it now..."
		just "$TYPE" "$VARIANT" "$FLAVOR"
		if [[ ! -f "${image_file}" ]]; then
			if [[ "$TYPE" == "qcow2" ]]; then
				image_file="${VARIANT}.qcow2"
			elif [[ "$TYPE" == "iso" ]]; then image_file="${VARIANT}.iso"; fi
		fi
	fi

	port=8100
	while ss -tln | grep -q ":${port} "; do port=$((port + 1)); done
	echo "Using Web Port: ${port}"
	echo "Connect via Web: http://127.0.0.1:${port}"

	run_args=(--rm --privileged --pull=newer --publish "0.0.0.0:${port}:8006" --env "CPU_CORES=4" --env "RAM_SIZE=4G" --env "DISK_SIZE=64G" --env "TPM=Y" --env "GPU=Y" --device=/dev/kvm)

	ssh_port=$((port + 1))
	while ss -tln | grep -q ":${ssh_port} "; do ssh_port=$((ssh_port + 1)); done
	echo "Using SSH Port: ${ssh_port}"
	echo "Connect via SSH: ssh centos@127.0.0.1 -p ${ssh_port}"
	run_args+=(--publish "0.0.0.0:${ssh_port}:22" --env "USER_PORTS=22" --env "NETWORK=user")

	run_args+=(--volume "${PWD}/${image_file}:/boot.${TYPE}" ghcr.io/qemus/qemu)

	(sleep 5 && xdg-open "http://127.0.0.1:${port}") &
	podman run "${run_args[@]}"
	;;

demo)
	VARIANT="${1:-albacore}"
	FLAVOR="${2:-gnome}"
	REBUILD="${3:-0}"

	if [[ -f "${VARIANT}-${FLAVOR}.qcow2" ]]; then
		QCOW2_FILE="${VARIANT}-${FLAVOR}.qcow2"
	else
		QCOW2_FILE="${VARIANT}.qcow2"
	fi

	if [[ "$REBUILD" == "1" ]] || [[ ! -f "${QCOW2_FILE}" ]]; then
		echo "==> Building qcow2..."
		just qcow2 "$VARIANT" "$FLAVOR"
		if [[ -f "${VARIANT}-${FLAVOR}.qcow2" ]]; then
			QCOW2_FILE="${VARIANT}-${FLAVOR}.qcow2"
		else QCOW2_FILE="${VARIANT}.qcow2"; fi
	fi

	if [[ ! -f "${QCOW2_FILE}" ]]; then
		echo "Error: ${QCOW2_FILE} not found after build."
		exit 1
	fi

	just _run-vm qcow2 "$VARIANT" "$FLAVOR"
	;;

demo-iso)
	VARIANT="${1:-skipjack}"
	FLAVOR="${2:-gnome}"
	REBUILD="${3:-0}"

	BUILD_DIR=".build/live-iso/${VARIANT}-${FLAVOR}"
	ISO_FILE=$(find "${BUILD_DIR}" -maxdepth 1 -name "*.iso" 2>/dev/null | head -1 || true)

	if [[ "$REBUILD" == "1" ]] || [[ -z "${ISO_FILE}" ]] || [[ ! -f "${ISO_FILE}" ]]; then
		echo "==> Building live ISO..."
		just live-iso "$VARIANT" "$FLAVOR" local
		ISO_FILE=$(find "${BUILD_DIR}" -maxdepth 1 -name "*.iso" 2>/dev/null | head -1 || true)
	fi

	if [[ -z "${ISO_FILE}" ]] || [[ ! -f "${ISO_FILE}" ]]; then
		echo "Error: ISO not found in ${BUILD_DIR}. Check build output."
		exit 1
	fi

	just _run-vm iso "$VARIANT" "$FLAVOR" "$(realpath "${ISO_FILE}")"
	;;

*)
	echo "Usage: run-vm.sh <run|demo|demo-iso> [args...]" >&2
	exit 1
	;;
esac
