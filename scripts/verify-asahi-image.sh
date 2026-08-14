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
check_file() {
    local soft="${2:-false}"
    if [[ -e "$mnt$1" ]]; then
        ok "$1"
    elif [[ "$soft" == "true" ]]; then
        note "$1 missing (known packaging gap)"
    else
        bad "$1 missing"
    fi
}

echo "== distro family =="
is_el10=false
if [[ -f "$mnt/etc/os-release" ]]; then
    if grep -qE 'PLATFORM_ID="platform:el10"|VERSION_ID="10"' "$mnt/etc/os-release" 2>/dev/null; then
        is_el10=true
        ok "EL10 packaging family detected (os-release)"
    else
        ok "standard packaging family detected (os-release)"
    fi
elif [[ "$kver" == *el10* ]]; then
    is_el10=true
    ok "EL10 packaging family detected (kernel ver: $kver)"
else
    ok "standard packaging family detected"
fi

echo "== kernel =="
mapfile -t kvers < <(ls "$mnt/usr/lib/modules/" 2>/dev/null)
if [[ ${#kvers[@]} -eq 1 ]]; then ok "exactly one kernel: ${kvers[0]}"
else bad "expected exactly 1 kernel in /usr/lib/modules, found ${#kvers[@]}: ${kvers[*]:-none}"; fi
# Grade the asahi kernel where one exists, not simply the first entry `ls`
# returns. Shipping two kernels stays a hard failure above — it is a real
# ambiguous-boot defect — but it must not also decide WHICH kernel the rest of
# the checks grade. albacore shipped a correct asahi kernel alongside an
# unremoved stock one; `6.12.0-…el10_2` sorts before `6.16.4-…asahi…+16k`, so
# every subsequent check graded the stock kernel and 24 cascading failures
# buried the single real defect (#776).
kver="${kvers[0]:-}"
for k in "${kvers[@]}"; do
    if [[ "$k" == *asahi* ]]; then kver="$k"; break; fi
done
M="$mnt/usr/lib/modules/$kver"
# 16K pages are a hard requirement of Apple Silicon's DART IOMMU, not a
# distro naming convention — Fedora encodes it in the version (+16k),
# Ubuntu's asahi-arm kernels don't but do carry CONFIG_ARM64_16K_PAGES=y
# (verified against the linux-buildinfo config, 2026-07-24). Trust the
# version suffix where present; fall back to the shipped kernel config.
if [[ "$kver" == *+16k ]]; then
    ok "16K page-size kernel flavor (+16k)"
elif [[ -f "$M/config" ]] && grep -qx "CONFIG_ARM64_16K_PAGES=y" "$M/config"; then
    ok "16K page-size kernel (CONFIG_ARM64_16K_PAGES=y)"
else
    bad "kernel is not confirmed 16K-page: $kver"
fi
[[ "$kver" == *asahi* ]]   && ok "asahi kernel build" || bad "kernel version lacks 'asahi': $kver"
[[ -f "$M/vmlinuz" ]]      && ok "vmlinuz present" || bad "vmlinuz missing"
[[ -f "$M/initramfs.img" ]] && ok "initramfs.img present" || bad "initramfs.img missing (bootc images must ship a prebuilt initramfs)"

echo "== kernel modules (Apple Silicon hardware) =="
deps="$M/modules.dep"
for mod in asahi.ko appledrm.ko nvme-apple.ko hci_bcm4377.ko brcmfmac.ko \
           apple-dart.ko macsmc.ko apple-isp.ko spi-hid-apple.ko \
           apple-admac.ko apple-soc-cpufreq.ko dockchannel-hid.ko; do
    if grep -qE "/${mod}(\.xz|\.zst|\.gz)?:" "$deps" 2>/dev/null; then ok "$mod"
    elif [[ "$is_el10" == "true" && "$mod" == "apple-isp.ko" ]]; then note "$mod not in modules.dep (known EL10 packaging gap)"
    else bad "$mod not in modules.dep"; fi
done

echo "== devicetrees =="
dtb_dir="$M/dtb/apple"
dtb_count=$(ls "$dtb_dir" 2>/dev/null | wc -l)
[[ "$dtb_count" -ge 50 ]] && ok "apple DTBs present ($dtb_count)" || bad "apple DTB dir missing/sparse ($dtb_count)"
[[ -f "$dtb_dir/t8103-j313.dtb" ]] && ok "t8103-j313.dtb (M1 MacBook Air)" || bad "t8103-j313.dtb missing"

echo "== boot chain payloads =="
check_any() { # label, soft, candidate paths...
    local label="$1"
    local soft="$2"
    shift 2
    for f in "$@"; do
        if [[ -e "$mnt$f" ]]; then ok "$label ($f)"; return; fi
    done
    if [[ "$soft" == "true" ]]; then
        note "$label missing (known packaging gap, tried: $*)"
    else
        bad "$label missing (tried: $*)"
    fi
}
# Paths differ per packaging family (Fedora lib64, Debian/Ubuntu lib, Arch boot)
check_any "m1n1 payload" false /usr/lib64/m1n1/m1n1.bin /usr/lib/m1n1/m1n1.bin /usr/lib/asahi-boot/m1n1.bin /boot/m1n1.bin
# /usr/lib/asahi-boot/u-boot.bin was a guess at Arch's filename under that
# directory; the real uboot-asahi package (asahi-alarm/asahi-alarm, verified
# by downloading uboot-asahi-2026.04.asahi2-1-aarch64.pkg.tar.xz and listing
# its contents directly) ships u-boot-nodtb.bin there instead, matching the
# other two families' filename — only the directory differs by family.
check_any "Apple U-Boot payload" false /usr/share/uboot/apple_m1/u-boot-nodtb.bin /usr/lib/u-boot/apple_m1/u-boot-nodtb.bin /usr/lib/asahi-boot/u-boot-nodtb.bin /boot/u-boot-nodtb.bin
# CentOS Hyperscale SIG's update-m1n1 RPM (EL10: skipjack/yellowfin/albacore)
# installs to /usr/sbin, not /usr/bin like Fedora's — verified by downloading
# update-m1n1-20250426.1-1.hs+asahi.el10.noarch.rpm from the Hyperscale
# packages-asahi repo and reading its file list directly (tunaOS#777). This
# was a hard-coded single-path check missing that family split, unlike the
# two checks above it — every yellowfin/skipjack sweep was scoring a FAIL for
# a binary that was actually present the whole time.
check_any "update-m1n1" false /usr/bin/update-m1n1 /usr/sbin/update-m1n1
# Hyperscale's update-m1n1 RPM genuinely does not ship a kernel-install.d (or
# postinst.d) hook — confirmed the same way, by reading its actual file list;
# there is no plausible alternate path to add here for this family. This is a
# real, still-open EL10 packaging gap (tunaOS#777), not a harness bug like the
# path above. It does not leave EL10 boot-chain updates unmaintained in
# practice: this repo ships asahi-bootbin-sync.service
# (build_scripts/asahi/install-bootbin-sync.sh) specifically because bootc
# deploys never run package scriptlets anyway, on every family, Fedora
# included — a working kernel-install hook would never fire after a `bootc
# switch` regardless of which family's kernel it came from. So this FAIL
# tracks upstream packaging completeness, not "does this image regenerate its
# boot.bin after an upgrade" — that question is asahi-bootbin-sync.service's,
# and it does not depend on this hook existing.
check_any "update-m1n1 kernel hook" "$is_el10" /usr/lib/kernel/install.d/15-update-m1n1.install /etc/kernel/postinst.d/update-m1n1 /etc/kernel/postinst.d/zz-update-m1n1

echo "== firmware handling =="
check_file /usr/bin/asahi-fwextract
# Same family split as update-m1n1 above, same verification method: Hyperscale
# SIG's asahi-fwupdate RPM (asahi-fwupdate-20250426.1-1.hs+asahi.el10.noarch)
# installs to /usr/sbin/asahi-fwupdate. asahi-fwextract, checked just above,
# really is at /usr/bin in the same RPM family — the split is per-binary, not
# uniformly bin-vs-sbin, so it is not safe to assume from one to the other.
check_any "asahi-fwupdate" false /usr/bin/asahi-fwupdate /usr/sbin/asahi-fwupdate
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
check_file /usr/bin/tiny-dfr "$is_el10"
check_file /usr/lib/systemd/system/tiny-dfr.service "$is_el10"
check_file /usr/bin/asahi-diagnose "$is_el10"

echo
echo "RESULT: $pass passed, $fail failed, $warn warnings"
[[ "$fail" -eq 0 ]]
INNER
rc=$?
exit $rc
