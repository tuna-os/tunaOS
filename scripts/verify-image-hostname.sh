#!/usr/bin/env bash
# verify-image-hostname.sh <image>: fail when a built image ships an
# /etc/hostname that names a host.
#
# systemd names the host from /etc/hostname when that file holds a name. Only
# when it is absent or empty does it use DEFAULT_HOSTNAME from os-release,
# which 90-image-info.sh sets to the variant. The installer writes
# /etc/hostname for an installed system, so the image must not ship one. The
# published grouper image did: docker.io/library/ubuntu:resolute ships the
# file containing "localhost.localdomain", and every grouper booted with that
# name (Gate hostname FAIL, run 44926166422).
#
# The file is read from the finished image with `podman cp`. A check inside a
# build RUN step reads the builder's own bind-mounted /etc/hostname, not the
# image's, and passes while the image leaks. An empty file passes: buildah
# leaves one behind after a RUN step built without --no-hostname, and systemd
# treats an empty file as absent.
#
# Prints TUNAOS_IMAGE_HOSTNAME_OK or TUNAOS_IMAGE_HOSTNAME_FAIL. Exits 1 on a
# name, and also when podman cannot read the image (then nothing is proven).

set -euo pipefail

image="${1:?usage: verify-image-hostname.sh <image>}"

fail() {
	echo "  FAIL: $*" >&2
	echo "TUNAOS_IMAGE_HOSTNAME_FAIL image=${image} hostname=${name:-}" >&2
	exit 1
}

name=""
tmp="$(mktemp -d)"
ctr=""
cleanup() {
	if [[ -n "$ctr" ]]; then
		podman rm -f "$ctr" >/dev/null 2>&1 || true
	fi
	rm -rf "$tmp"
}
trap cleanup EXIT

ctr="$(podman create "$image" /bin/true)" || fail "podman create ${image} failed; cannot read the image's /etc/hostname"
[[ -n "$ctr" ]] || fail "podman create ${image} printed no container id"
if ! err="$(podman cp "${ctr}:/etc/hostname" "${tmp}/hostname" 2>&1)"; then
	# podman 4.9: Error: "/etc/hostname" could not be found on container …: no such file or directory
	[[ "$err" == *"no such file or directory"* ]] || fail "podman cp ${ctr}:/etc/hostname: ${err}"
	echo "TUNAOS_IMAGE_HOSTNAME_OK image=${image} etc_hostname=absent"
	exit 0
fi
[[ -f "${tmp}/hostname" ]] || fail "podman cp ${ctr}:/etc/hostname succeeded but wrote no file"

name="$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "${tmp}/hostname" | head -n 1 | tr -d '[:space:]')"
if [[ -n "$name" ]]; then
	fail "${image} ships /etc/hostname '${name}'; the installed system would keep that name instead of DEFAULT_HOSTNAME. Remove it in 90-image-info.sh, built with --no-hostname"
fi
echo "TUNAOS_IMAGE_HOSTNAME_OK image=${image} etc_hostname=empty"
