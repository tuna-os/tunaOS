#!/usr/bin/env bash
# verify-asahi-image.sh — validate that a bootc image contains everything an
# Apple Silicon (Asahi) machine needs to boot and run.
#
# Golden manifest derived from the known-working image
# quay.io/fedora-asahi-remix-atomic-desktops/silverblue:43.20260718.0
# (kernel 7.0.13-400.asahi.fc43.aarch64+16k), 2026-07-23.
# Path checks are multi-family (Fedora/EL, Debian/Ubuntu, Arch layouts).
#
# Usage: verify-asahi-image.sh <image-ref> [--no-pull]
# Works rootless; only needs podman. Exit 0 = all required checks pass.

set -u

IMAGE="${1:?usage: verify-asahi-image.sh <image-ref> [--no-pull]}"
NO_PULL="${2:-}"

if [[ "$NO_PULL" != "--no-pull" ]]; then
    podman pull --platform linux/arm64 "$IMAGE" >/dev/null || exit 2
fi

CTR=$(podman create --platform linux/arm64 "$IMAGE" true) || exit 2
trap 'podman rm -f "$CTR" >/dev/null 2>&1' EXIT

podman unshare bash -s "$CTR" <<'INNER'
CTR="$1"
mnt=$(podman mount "$CTR") || exit 2
trap 'podman umount "$CTR" >/dev/null 2>&1' EXIT

pass=0 fail=0 warn=0
ok()   { echo "  ok   $*"; ((pass++)); }
bad()  { echo "  FAIL $*"; ((fail++)); }
note() { echo "  warn $*"; ((warn++)); }
check_file() { [[ -e "$mnt$1" ]] && ok "$1" || bad "$1 missing"; }

echo "== kernel =="
mapfile -t kvers < <(ls "$mnt/usr/lib/modules/" 2>/dev/null)
if [[ ${#kvers[@]} -eq 1 ]]; then ok "exactly one kernel: ${kvers[0]}"
else bad "expected exactly 1 kernel in /usr/lib/modules, found ${#kvers[@]}: ${kvers[*]:-none}"; fi
kver="${kvers[0]:-}"
M="$mnt/usr/lib/modules/$kver"
[[ "$kver" == *+16k ]]     && ok "16K page-size kernel flavor (+16k)" || bad "kernel is not the 16k flavor: $kver"
[[ "$kver" == *asahi* ]]   && ok "asahi kernel build" || bad "kernel version lacks 'asahi': $kver"
[[ -f "$M/vmlinuz" ]]      && ok "vmlinuz present" || bad "vmlinuz missing"
[[ -f "$M/initramfs.img" ]] && ok "initramfs.img present" || bad "initramfs.img missing (bootc images must ship a prebuilt initramfs)"

echo "== kernel modules (Apple Silicon hardware) =="
deps="$M/modules.dep"
for mod in asahi.ko appledrm.ko nvme-apple.ko hci_bcm4377.ko brcmfmac.ko \
           apple-dart.ko macsmc.ko apple-isp.ko spi-hid-apple.ko \
           apple-admac.ko apple-soc-cpufreq.ko dockchannel-hid.ko; do
    if grep -qE "/${mod}(\.xz|\.zst|\.gz)?:" "$deps" 2>/dev/null; then ok "$mod"
    else bad "$mod not in modules.dep"; fi
done

echo "== devicetrees =="
dtb_dir="$M/dtb/apple"
dtb_count=$(ls "$dtb_dir" 2>/dev/null | wc -l)
[[ "$dtb_count" -ge 50 ]] && ok "apple DTBs present ($dtb_count)" || bad "apple DTB dir missing/sparse ($dtb_count)"
[[ -f "$dtb_dir/t8103-j313.dtb" ]] && ok "t8103-j313.dtb (M1 MacBook Air)" || bad "t8103-j313.dtb missing"

echo "== boot chain payloads =="
check_any() { # label, candidate paths...
    local label="$1"; shift
    for f in "$@"; do
        if [[ -e "$mnt$f" ]]; then ok "$label ($f)"; return; fi
    done
    bad "$label missing (tried: $*)"
}
# Paths differ per packaging family (Fedora lib64, Debian/Ubuntu lib, Arch boot)
check_any "m1n1 payload" /usr/lib64/m1n1/m1n1.bin /usr/lib/m1n1/m1n1.bin /usr/lib/asahi-boot/m1n1.bin /boot/m1n1.bin
check_any "Apple U-Boot payload" /usr/share/uboot/apple_m1/u-boot-nodtb.bin /usr/lib/u-boot/apple_m1/u-boot-nodtb.bin /usr/lib/asahi-boot/u-boot.bin
check_file /usr/bin/update-m1n1
check_any "update-m1n1 kernel hook" /usr/lib/kernel/install.d/15-update-m1n1.install /etc/kernel/postinst.d/update-m1n1

echo "== firmware handling =="
check_file /usr/bin/asahi-fwextract
check_file /usr/bin/asahi-fwupdate
[[ -d "$mnt/usr/lib/dracut/modules.d/99asahi-firmware" ]] && ok "dracut 99asahi-firmware" || bad "dracut module 99asahi-firmware missing"
[[ -d "$mnt/usr/lib/dracut/modules.d/91kernel-modules-asahi" ]] && ok "dracut 91kernel-modules-asahi" || bad "dracut module 91kernel-modules-asahi missing"
if grep -qs "asahi-firmware" "$mnt"/usr/lib/dracut/dracut.conf.d/*; then
    ok "dracut.conf.d enables asahi modules"
else bad "no dracut.conf.d entry adding asahi-firmware"; fi
# best-effort: confirm the built initramfs actually contains the asahi module
if command -v lsinitrd >/dev/null 2>&1; then
    if lsinitrd "$M/initramfs.img" 2>/dev/null | grep -q asahi; then ok "initramfs contains asahi bits"
    else bad "initramfs.img does not contain asahi bits"; fi
else
    note "lsinitrd unavailable — initramfs content not verified"
fi

echo "== audio stack (speakers stay disabled if any piece is missing) =="
check_file /usr/bin/speakersafetyd
check_file /usr/lib/systemd/system/speakersafetyd.service
[[ -d "$mnt/usr/share/alsa/ucm2/conf.d/macaudio" ]] && ok "alsa-ucm macaudio profiles" || bad "alsa ucm2/conf.d/macaudio missing"
aa=$(ls "$mnt/usr/share/asahi-audio" 2>/dev/null | wc -l)
[[ "$aa" -ge 5 ]] && ok "asahi-audio machine profiles ($aa)" || bad "asahi-audio profiles missing"

echo "== misc userspace =="
check_file /usr/bin/tiny-dfr
check_file /usr/lib/systemd/system/tiny-dfr.service
check_file /usr/bin/asahi-diagnose

echo
echo "RESULT: $pass passed, $fail failed, $warn warnings"
[[ "$fail" -eq 0 ]]
INNER
rc=$?
exit $rc
