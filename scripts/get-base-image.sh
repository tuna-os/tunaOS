#!/usr/bin/env bash

set -euo pipefail

variant="$1"

case "$variant" in
"yellowfin") echo "quay.io/almalinuxorg/almalinux-bootc:10-kitten" ;;
"albacore") echo "quay.io/almalinuxorg/almalinux-bootc:10" ;;
"skipjack") echo "quay.io/centos-bootc/centos-bootc:stream10" ;;
"bonito") echo "quay.io/fedora/fedora-bootc:43" ;;
"grouper") echo "docker.io/library/ubuntu:resolute" ;;
"bonito-rawhide") echo "quay.io/fedora/fedora-bootc:rawhide" ;;
"redfin") echo "registry.redhat.io/rhel10/rhel-bootc:latest" ;;
"sailfin") echo "registry.opensuse.org/opensuse/tumbleweed:latest" ;;
"guppy") echo "docker.io/gentoo/stage3:latest" ;;
"marlin") echo "docker.io/archlinux/archlinux:latest" ;; 
"flounder") echo "docker.io/library/debian:trixie" ;;
"flounder-sid") echo "docker.io/library/debian:sid" ;;
*)
	echo "Unknown variant: $variant" >&2
	exit 1
	;;
esac
