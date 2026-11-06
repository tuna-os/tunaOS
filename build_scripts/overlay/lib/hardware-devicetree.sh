#!/usr/bin/env bash
# hardware-devicetree — give a kernel the device tree its hardware profile
# names, in the form the image's boot backend loads.
#
# Usage: hardware-devicetree add|remove [<kver>...]
#   With no <kver>, reads package-manager targets (usr/lib/modules/<kver>/vmlinuz,
#   one per line) on stdin, as a libalpm hook with NeedsTargets passes them.
#
# build_scripts/overlay/hardware-profile.sh installs this as
# /usr/libexec/tunaos/hardware-devicetree, writes its configuration
#   /usr/lib/tunaos/hardware-devicetree.conf
#     dtb=<path relative to a kernel's dtb directory>
#     layout=ostree|composefs
# and runs it for the image's kernel. Every LATER kernel reaches it through the
# kernel-install plugin (dnf) or the libalpm hooks (pacman) installed beside it,
# so a kernel that a derived image installs carries its own DTB rather than
# booting with none.
#
#   ostree     /usr/lib/modules/<kver>/devicetree. ostree copies it into each
#              deployment's /boot and writes a `devicetree` line into that
#              deployment's entry, so every deployment, upgrade and rollback
#              loads the DTB of its own kernel. With only a dtb/ directory
#              ostree writes `fdtdir`, which GRUB ignores.
#   composefs  bootc's composefs boot entries carry no `devicetree` line, so
#              the kernel carries the DTB: vmlinuz is wrapped in systemd-stub
#              with a .dtbauto section and the hardware-ID table, and the stub
#              picks the DTB by the machine's CHID (Fedora's kernel-dtb-loader
#              mechanism). The entry still supplies initramfs and command line.
#
# TUNAOS_SYSROOT prefixes every path (test hook, as in hardware-profile.sh).
set -euo pipefail

R="${TUNAOS_SYSROOT:-}"
CONF="${R}/usr/lib/tunaos/hardware-devicetree.conf"

die() {
	echo "hardware-devicetree: $*" >&2
	exit 1
}

dtb_rel=""
layout=""
[[ -r "${CONF}" ]] || die "no configuration at ${CONF}"
while IFS='=' read -r key value; do
	case "${key}" in
	dtb) dtb_rel="${value}" ;;
	layout) layout="${value}" ;;
	esac
done <"${CONF}"
[[ -n "${dtb_rel}" ]] || die "${CONF} names no dtb"
case "${layout}" in
ostree | composefs) ;;
*) die "${CONF} has layout '${layout}', expected ostree or composefs" ;;
esac

action="${1:-}"
case "${action}" in
add | remove) shift ;;
*) die "usage: hardware-devicetree add|remove [<kver>...]" ;;
esac
kvers=("$@")
if ((${#kvers[@]} == 0)); then
	while IFS= read -r target; do
		target="${target#/}"
		if [[ "${target}" =~ ^usr/lib/modules/([^/]+)/vmlinuz$ ]]; then
			kvers+=("${BASH_REMATCH[1]}")
		fi
	done
fi

# Succeeds when the PE image already has the named section.
has_section() {
	python3 -c 'import pefile, sys
names = {s.Name.rstrip(b"\0").decode() for s in pefile.PE(sys.argv[1], fast_load=True).sections}
sys.exit(0 if sys.argv[2] in names else 1)' "$1" "$2"
}

place() {
	local kver="$1"
	local module_dir="${R}/usr/lib/modules/${kver}"
	local dtb="${module_dir}/dtb/${dtb_rel}"
	if [[ ! -s "${dtb}" ]]; then
		# Arch-family kernel packages install their DTBs in /boot/dtbs, beside
		# the one kernel the package carries, instead of the module directory.
		# At the hook's PostTransaction they belong to the kernel just installed.
		dtb="${R}/boot/dtbs/${dtb_rel}"
	fi
	[[ -s "${dtb}" ]] || die "kernel ${kver} has no device tree ${dtb_rel}"
	[[ -f "${module_dir}/vmlinuz" ]] || die "kernel ${kver} has no ${module_dir}/vmlinuz"

	if [[ "${layout}" == ostree ]]; then
		install -m 0644 "${dtb}" "${module_dir}/devicetree"
		echo "hardware-devicetree: ${kver} devicetree <- ${dtb_rel}"
		return
	fi

	# A kernel that already carries a device tree is not wrapped twice.
	if has_section "${module_dir}/vmlinuz" .dtbauto; then
		echo "hardware-devicetree: ${kver} vmlinuz already carries .dtbauto"
		return
	fi
	local efi_arch
	case "$(uname -m)" in
	aarch64) efi_arch=aa64 ;;
	x86_64) efi_arch=x64 ;;
	*) die "no systemd-stub architecture for $(uname -m)" ;;
	esac
	command -v ukify >/dev/null 2>&1 || die "ukify is required to give kernel ${kver} its device tree"
	local stub_image
	stub_image="$(mktemp)"
	ukify build \
		--linux="${module_dir}/vmlinuz" \
		--devicetree-auto="${dtb}" \
		--hwids="${R}/usr/lib/systemd/boot/hwids/${efi_arch}" \
		--stub="${R}/usr/lib/systemd/boot/efi/linux${efi_arch}.efi.stub" \
		--uname="${kver}" \
		--output="${stub_image}"
	install -m 0755 "${stub_image}" "${module_dir}/vmlinuz"
	rm -f "${stub_image}"
	echo "hardware-devicetree: ${kver} vmlinuz wrapped with .dtbauto <- ${dtb_rel}"
}

for kver in "${kvers[@]}"; do
	if [[ "${action}" == add ]]; then
		place "${kver}"
	elif [[ "${layout}" == ostree ]]; then
		# Runs before the package removes the kernel, so its module
		# directory is not left behind holding only this file.
		rm -f "${R}/usr/lib/modules/${kver}/devicetree"
	fi
done
