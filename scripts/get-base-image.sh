#!/usr/bin/env bash

set -euo pipefail

variant="$1"

case "$variant" in
"yellowfin" | "almalinux-kitten") echo "quay.io/almalinuxorg/almalinux-bootc:10-kitten" ;;
"albacore" | "almalinux") echo "quay.io/almalinuxorg/almalinux-bootc:10" ;;
"skipjack" | "centos" | "lts") echo "quay.io/centos-bootc/centos-bootc:stream10" ;;
"bonito" | "fedora" | "bluefin") echo "quay.io/fedora/fedora-bootc:42" ;;
"bonito-rawhide" | "rawhide") echo "quay.io/fedora/fedora-bootc:rawhide" ;;
*)
	echo "Unknown variant: $variant" >&2
	exit 1
	;;
esac
