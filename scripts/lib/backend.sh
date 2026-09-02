#!/usr/bin/env bash
# Detect the bootc storage backend by probing image contents. This library is
# side-effect free when sourced so focused consumers do not inherit common.sh's
# repository-root cwd change or its unrelated build helpers.

# THE ORDER IS LOAD-BEARING: a bootupd payload identifies ostree even when
# composefs is sealed; otherwise an enabled composefs config or systemd-boot
# identifies composefs-native. Unknown images are never guessed.
# shellcheck disable=SC2016  # the $-free sh body is intentionally unexpanded
TUNAOS_BACKEND_PROBE_SH='
if { ls /usr/lib/bootupd/updates/EFI/*/grubx64.efi >/dev/null 2>&1 ||
     { test -f /usr/lib/bootupd/updates/EFI.json &&
       find /usr/lib/efi/grub2 -type f -name grubx64.efi -print -quit 2>/dev/null | grep -q . &&
       find /usr/lib/efi/shim -type f -name shimx64.efi -print -quit 2>/dev/null | grep -q .; }; }; then
    echo BACKEND=ostree
elif grep -A8 "^\[composefs\]" /usr/lib/ostree/prepare-root.conf 2>/dev/null \
     | grep -qiE "enabled[[:space:]]*=[[:space:]]*(yes|true|1|signed)"; then
    echo BACKEND=composefs-native
elif test -f /usr/lib/systemd/boot/efi/systemd-bootx64.efi; then
    echo BACKEND=composefs-native
else
    echo BACKEND=unknown
fi
grep -A8 "^\[composefs\]" /usr/lib/ostree/prepare-root.conf 2>/dev/null \
  | grep -qiE "enabled[[:space:]]*=[[:space:]]*(yes|true|1|signed)" && echo SEALED=1 || echo SEALED=0
'

# probe_image_backend <image-ref> [podman-prefix...]
# Echoes BACKEND=<ostree|composefs-native|unknown> and SEALED=<0|1>. Inspection
# failures remain fatal so callers never silently select an incompatible path.
probe_image_backend() {
	local ref="${1:?probe_image_backend <image-ref>}"
	shift
	local -a runner=("$@")
	[[ ${#runner[@]} -eq 0 ]] && runner=(podman)
	timeout 300 "${runner[@]}" run --rm --entrypoint="" "$ref" sh -c "$TUNAOS_BACKEND_PROBE_SH"
}
