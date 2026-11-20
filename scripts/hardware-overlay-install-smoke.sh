#!/usr/bin/env bash
# hardware-overlay-install-smoke.sh <image ref> <profile id> <work dir>
#
# Install a hardware overlay to a loop-backed disk with `bootc install
# to-disk`, check the boot entry it wrote, then boot that disk on a generic
# QEMU machine. Run as root on a host of the image's architecture.
#
#   entry   the installed BLS entry carries every profile karg, and (for a
#           profile with a DTB) a `devicetree` line naming a file in /boot whose
#           bytes are the image's copy of the profile DTB. That line is how
#           GRUB hands the board its device tree; without it the board boots
#           on its ACPI tables and has no display, USB or NVMe.
#   boot    with that one line removed, the disk boots on QEMU's `virt`
#           machine to a serial login prompt. The profile's DTB describes the
#           board, not `virt`, so it cannot be booted here; this checks that the
#           rest of the install (GRUB, kernel, the rebuilt initramfs, ostree,
#           the profile's kargs) boots on a generic machine.
#
# Neither is evidence about the board itself; that needs the hardware.
#
# Environment: PODMAN (optional) names the binary; BOOT_TIMEOUT (seconds,
# default 2400) bounds the boot; FIRMWARE_CODE / FIRMWARE_VARS override the
# UEFI images (AAVMF on aarch64, OVMF on x86_64).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

image="${1:?usage: hardware-overlay-install-smoke.sh <image ref> <profile id> <work dir>}"
id="${2:?usage: hardware-overlay-install-smoke.sh <image ref> <profile id> <work dir>}"
work="${3:?usage: hardware-overlay-install-smoke.sh <image ref> <profile id> <work dir>}"
PODMAN="${PODMAN:-podman}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-2400}"
case "$(uname -m)" in
aarch64)
	qemu=(qemu-system-aarch64 -machine virt -cpu max)
	console=ttyAMA0
	code="${FIRMWARE_CODE:-/usr/share/AAVMF/AAVMF_CODE.fd}"
	vars="${FIRMWARE_VARS:-/usr/share/AAVMF/AAVMF_VARS.fd}"
	;;
x86_64)
	qemu=(qemu-system-x86_64 -machine q35 -cpu max)
	console=ttyS0
	code="${FIRMWARE_CODE:-/usr/share/OVMF/OVMF_CODE_4M.fd}"
	vars="${FIRMWARE_VARS:-/usr/share/OVMF/OVMF_VARS_4M.fd}"
	;;
*)
	echo "ERROR: no QEMU machine for $(uname -m)" >&2
	exit 2
	;;
esac
profile="$(jq -ce --arg id "$id" '.profiles[$id]' build_scripts/lib/hardware-profiles.json)"
mapfile -t kargs < <(jq -r '.kargs[]?' <<<"$profile")
dtb="$(jq -r '.devicetree.dtb // ""' <<<"$profile")"

mkdir -p "$work"
work="$(readlink -f "$work")"
disk="$work/disk.raw"
mnt="$work/boot"
loop=""
qemu_pid=""
# shellcheck disable=SC2329 # run by the EXIT trap
cleanup() {
	[[ -n "$qemu_pid" ]] && kill "$qemu_pid" 2>/dev/null
	mountpoint -q "$mnt" && umount "$mnt"
	[[ -n "$loop" ]] && losetup -d "$loop"
	return 0
}
trap cleanup EXIT

# ── install ──────────────────────────────────────────────────────────────────
# The backend from the image content, as build-qcow2.sh does: a sealed
# composefs rootfs needs ext4 (fs-verity), and only the ostree/GRUB layout
# writes the BLS entry checked below. A composefs-native hardware image keeps
# its DTB in the systemd-stub kernel instead; no such flavor is built yet, so
# this refuses it rather than checking the wrong thing.
# shellcheck source=lib/backend.sh
source scripts/lib/backend.sh
probe="$(probe_image_backend "$image" "$PODMAN")"
echo "== image probe: $(tr '\n' ' ' <<<"$probe")"
if ! grep -q '^BACKEND=ostree$' <<<"$probe"; then
	echo "FAIL entry: only the ostree/GRUB layout is checked here; ${image} is $(grep '^BACKEND=' <<<"$probe")" >&2
	exit 1
fi
install_args=()
grep -q '^SEALED=1$' <<<"$probe" && install_args+=(--filesystem ext4)
rm -f "$disk"
truncate -s 24G "$disk"
"$PODMAN" run --rm --privileged --pid=host --security-opt label=type:unconfined_t \
	-v /dev:/dev -v /var/lib/containers:/var/lib/containers -v "$work:/output" \
	"$image" bootc install to-disk --via-loopback --generic-image --wipe "${install_args[@]}" \
	--karg "console=${console},115200" --karg systemd.journald.forward_to_console=1 /output/disk.raw

# ── the boot entry ───────────────────────────────────────────────────────────
loop="$(losetup -fP --show "$disk")"
udevadm settle || true
boot_part="$(lsblk -lnpo PATH,PARTLABEL "$loop" | awk '$2 == "boot" {print $1}')"
[[ -n "$boot_part" ]] || boot_part="$(lsblk -lnpo PATH,FSTYPE "$loop" | awk '$2 == "ext4" {print $1}' | head -n1)"
if [[ -z "$boot_part" ]]; then
	echo "FAIL entry: no boot partition on the installed disk" >&2
	lsblk -o NAME,SIZE,PARTLABEL,FSTYPE "$loop" >&2
	exit 1
fi
mkdir -p "$mnt"
mount "$boot_part" "$mnt"
mapfile -t entries < <(find "$mnt/loader/entries" -name '*.conf' 2>/dev/null)
if ((${#entries[@]} != 1)); then
	echo "FAIL entry: expected one BLS entry, found ${#entries[@]}" >&2
	exit 1
fi
entry="${entries[0]}"
echo "== ${entry#"$mnt"/}"
cat "$entry"
failed=0
options="$(sed -n 's/^options[[:space:]]\+//p' "$entry")"
for karg in "${kargs[@]}"; do
	if [[ " $options " != *" $karg "* ]]; then
		echo "FAIL entry: options lack ${karg}"
		failed=1
	fi
done
if [[ -n "$dtb" ]]; then
	dt_line="$(sed -n 's/^devicetree[[:space:]]\+//p' "$entry")"
	# shellcheck disable=SC2016 # expanded inside the image
	"$PODMAN" run --rm --entrypoint /bin/bash "$image" -c \
		'kver="$(ls /usr/lib/modules | sort -V | tail -n1)"; cat "/usr/lib/modules/${kver}/dtb/$1"' _ "$dtb" >"$work/profile.dtb"
	if [[ -z "$dt_line" ]]; then
		echo "FAIL entry: no devicetree line"
		failed=1
	elif ! cmp -s "$mnt/${dt_line#/}" "$work/profile.dtb"; then
		echo "FAIL entry: devicetree ${dt_line} is not the image's ${dtb}"
		failed=1
	else
		echo "PASS entry: devicetree ${dt_line} is ${dtb} ($(stat -c %s "$work/profile.dtb") bytes)"
	fi
fi
((failed)) && exit 1
echo "PASS entry: options carry ${kargs[*]:-no profile kargs}"

# The generic-machine boot: drop only the board's device tree.
sed -i '/^devicetree[[:space:]]/d' "$entry"
umount "$mnt"
losetup -d "$loop"
loop=""

# ── boot on a generic machine ────────────────────────────────────────────────
cp "$vars" "$work/vars.fd"
accel=tcg
[[ -w /dev/kvm ]] && accel=kvm
serial="$work/serial.log"
: >"$serial"
"${qemu[@]}" -accel "$accel" -smp 4 -m 4096 \
	-drive if=pflash,format=raw,readonly=on,file="$code" \
	-drive if=pflash,format=raw,file="$work/vars.fd" \
	-drive if=virtio,format=raw,file="$disk" \
	-display none -serial "file:$serial" -monitor none -nic none &
qemu_pid=$!
echo "== booting under ${accel}, serial log ${serial}, up to ${BOOT_TIMEOUT}s"
start=$SECONDS
while ((SECONDS - start < BOOT_TIMEOUT)); do
	if grep -qa 'login:' "$serial"; then
		echo "PASS boot: serial login prompt after $((SECONDS - start))s"
		grep -a -m1 'Kernel command line' "$serial" || true
		exit 0
	fi
	if ! kill -0 "$qemu_pid" 2>/dev/null; then
		echo "FAIL boot: QEMU exited after $((SECONDS - start))s"
		tail -n 60 "$serial"
		exit 1
	fi
	sleep 10
done
echo "FAIL boot: no serial login prompt in ${BOOT_TIMEOUT}s"
tail -n 60 "$serial"
exit 1
