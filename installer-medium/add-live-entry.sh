#!/usr/bin/env bash
# Add the medium-only live boot entry to an installed disk (tunaOS#4907, #4913).
#
# Usage (CI, root): installer-medium/add-live-entry.sh CELL ROOT ESP [--dry-run]
#
# ROOT is the mounted root filesystem, ESP the mounted ESP. GRUB cells get a
# BLS live entry (ro tunaos.live, the GRUB default) plus a live kernel and
# initrd copied onto the ESP, so a CD boot that cannot see /boot still finds
# them. systemd-boot cells get a Type #1 live entry with a live-only initrd
# (setup-root-conf.toml cpio, Dakota's pattern) and the loader default.
# With --dry-run, print each file operation and exit 0.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
CELL="${1:?usage: add-live-entry.sh CELL ROOT ESP [--dry-run]}"
MNT="${2:?usage: add-live-entry.sh CELL ROOT ESP [--dry-run]}"
ESP="${3:?usage: add-live-entry.sh CELL ROOT ESP [--dry-run]}"
DRY_RUN="${4:-}"
LIVE_ID=medium-live

row() {
	python3 -c 'import importlib.util,sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
medium = c.installer_medium_policy()
cell = medium.cell(c.load(root / "tunaos.toml"), sys.argv[2])
print(cell[sys.argv[3]])' "${ROOT}" "${CELL}" "$1"
}

BOOTLOADER="$(row bootloader)"
ENTRY_TOOL="${HERE}/live-entry.py"

say() {
	echo "live-entry: $*"
}

# Kernel arguments of the live entry only, after `ro tunaos.live`. The
# installed system does not get them.
#
# enforcing=0: the live root is an overlay with a tmpfs upper layer
# (medium-live-root.service, from Utah, which has no SELinux). With SELinux
# enforcing, the live boot of albacore:gnome reached the real root and then
# every service stopped with "cannot open shared object file: Permission
# denied" (run 45582312346). The same medium with enforcing=0 reached the
# GNOME session, sshd and the readiness stamp (run 45588977100). So the live
# session runs permissive until the initrd gives the overlay root its labels.
#
# MEDIUM_LIVE_KARGS adds arguments for a diagnosis run: the pull request lane
# of image-installer.yml sets a serial console there, so the boot log of a
# guest that never reaches sshd is in the evidence.
LIVE_KARGS=(enforcing=0)
# A live session with no locale runs as C.UTF-8, and then gnome-setup selects
# the first keyboard of its list, Dari (run 45651057509, tunaOS#5010). Only
# where the image has the locale: the kernel argument is for the live entry,
# the installed system takes what the person chooses.
for locale in "${MNT}"/ostree/deploy/*/deploy/*/usr/lib/locale "${MNT}"/state/deploy/*/usr/lib/locale; do
	if [[ -d "${locale}/en_US.utf8" ]] || grep -qsa 'en_US.utf8' "${locale}/locale-archive"; then
		LIVE_KARGS+=(locale.LANG=en_US.UTF-8)
		break
	fi
done
read -r -a extra_kargs <<<"${MEDIUM_LIVE_KARGS:-}"
LIVE_KARGS+=("${extra_kargs[@]}")

if [[ "${BOOTLOADER}" = "grub" ]]; then
	mapfile -t entries < <(find "${MNT}/boot/loader/entries/" -maxdepth 1 -name '*.conf' ! -name "${LIVE_ID}.conf" 2>/dev/null || true)
	if [[ "${DRY_RUN}" = "--dry-run" ]]; then
		say "grub: live-entry ${entries[0]:-<entry>} ${MNT}/boot/loader/entries/${LIVE_ID}.conf"
		say "grub: copy <kernel>+<initrd> to ${ESP}/EFI/tunaos-live/"
		say "grub: grubenv ${MNT}/boot/grub2/grubenv saved_entry=${LIVE_ID}"
		exit 0
	fi
	[[ ${#entries[@]} -eq 1 ]] || {
		echo "live-entry: expected one deployment entry, found ${#entries[@]}" >&2
		exit 1
	}
	python3 "${ENTRY_TOOL}" live-entry "${entries[0]}" "${MNT}/boot/loader/entries/${LIVE_ID}.conf" "${LIVE_KARGS[@]}"
	read -r kernel _ < <(
		python3 - "${entries[0]}" <<'PY'
import sys
for line in open(sys.argv[1]):
    key, _, value = line.partition(" ")
    if key == "linux":
        print(value.strip())
        break
PY
	)
	read -r -a initrds < <(
		python3 - "${entries[0]}" <<'PY'
import sys
print(" ".join(line.split(None, 1)[1].strip() for line in open(sys.argv[1]) if line.startswith("initrd")))
PY
	)
	mkdir -p "${ESP}/EFI/tunaos-live"
	cp -a "${MNT}/boot/${kernel#/boot/}" "${ESP}/EFI/tunaos-live/vmlinuz"
	: >"${ESP}/EFI/tunaos-live/initramfs.img"
	for initrd in "${initrds[@]}"; do
		cat "${MNT}/boot/${initrd#/boot/}" >>"${ESP}/EFI/tunaos-live/initramfs.img"
	done
	# A CD boot reads this payload off the ESP: fail now if it does not fit,
	# instead of shipping a medium that boots from USB only.
	avail="$(df --output=avail -B1 "${ESP}" | tail -n +2 | tr -d ' ')"
	[[ "${avail}" -ge 104857600 ]] || {
		echo "live-entry: only ${avail} bytes free on the ESP" >&2
		exit 1
	}
	# A CD boot reaches this menu through repart/iso-grub-stub.py. The kernel
	# and initrd on the ESP stay for firmware that shows GRUB the El Torito
	# image only.
	# live-entry.py takes IN OUT, then the arguments. The first real build
	# passed the entry id as OUT and stopped with "cat: /tmp/medium-grubenv:
	# No such file or directory" (run 45551665028).
	scratch="$(mktemp)"
	python3 "${ENTRY_TOOL}" grubenv "${MNT}/boot/grub2/grubenv" "${scratch}" "${LIVE_ID}"
	cat "${scratch}" >"${MNT}/boot/grub2/grubenv"
	rm -f "${scratch}"
	# The static grub.cfg of bootupd never reads saved_entry: it starts the
	# first entry, and blscfg puts the deployment entry first. The first
	# boot that showed the menu had "*Albacore (ostree:0)" selected and
	# started the deployment, not the live entry (run 45574919609, serial
	# log of the USB lane). That grub.cfg sources $prefix/custom.cfg after
	# blscfg (configs.d/41_custom.cfg), so the default goes there. On the
	# installed copy the live entry is gone, the id matches nothing, and
	# GRUB starts the first entry again.
	custom="${MNT}/boot/grub2/custom.cfg"
	if ! grep -qs '^# tunaos-medium: default' "${custom}"; then
		printf '%s\n' "# tunaos-medium: default to the live entry while it exists (add-live-entry.sh)" \
			"set default=\"${LIVE_ID}\"" >>"${custom}"
	fi
else
	mapfile -t entries < <(find "${ESP}/loader/entries/" -maxdepth 1 -name '*.conf' ! -name "${LIVE_ID}.conf" 2>/dev/null || true)
	if [[ "${DRY_RUN}" = "--dry-run" ]]; then
		say "systemd-boot: live-entry ${entries[0]:-<entry>} (Type#1 + live initrd, or UKI + live addon)"
		say "systemd-boot: loader.conf default=${LIVE_ID}.conf timeout=5"
		exit 0
	fi
	[[ ${#entries[@]} -eq 1 ]] || {
		echo "live-entry: expected one deployment entry, found ${#entries[@]}" >&2
		exit 1
	}
	if grep -q '^efi ' "${entries[0]}" && ! grep -q '^linux ' "${entries[0]}"; then
		uki="$(grep '^efi ' "${entries[0]}" | head -1 | cut -d' ' -f2)"
		mkdir -p "${ESP}/EFI/Linux/medium-live/boot.efi.d"
		cp -a "${ESP}/${uki#/}" "${ESP}/EFI/Linux/medium-live/boot.efi"
		"${HERE}/build-live-addon.sh" "${ESP}/EFI/Linux/medium-live/boot.efi.d/live.addon.efi"
		python3 - "${entries[0]}" "${ESP}/loader/entries/${LIVE_ID}.conf" "${LIVE_KARGS[@]}" <<'PY'
import sys
from pathlib import Path
lines = Path(sys.argv[1]).read_text().splitlines()
options = next(line for line in lines if line.startswith("options"))
args = [a for a in options.split()[1:] if a not in ("rw", "ro", "tunaos.live")]
Path(sys.argv[2]).write_text("title TunaOS Live (try or install)\n"
                              "efi /EFI/Linux/medium-live/boot.efi\n"
                              "options " + " ".join(args + ["ro", "tunaos.live"] + sys.argv[3:]) + "\n")
PY
	else
		live_cpio="${ESP}/EFI/Linux/medium-live/live.initrd"
		mkdir -p "$(dirname "${live_cpio}")"
		mkdir -p "${MNT}/tmp/medium-cpio/usr/lib/composefs"
		cp -a "${HERE}/live/setup-root-conf.toml" "${MNT}/tmp/medium-cpio/usr/lib/composefs/setup-root-conf.toml"
		(cd "${MNT}/tmp/medium-cpio" && find usr | cpio -o -H newc --quiet >"${live_cpio}")
		rm -rf "${MNT}/tmp/medium-cpio"
		python3 "${ENTRY_TOOL}" live-entry "${entries[0]}" "${ESP}/loader/entries/${LIVE_ID}.conf" "${LIVE_KARGS[@]}"
		# The entry names the file by its path on the ESP, not by the path of
		# the build mount. It goes after the last initrd of the image: a later
		# cpio wins, and the live one must replace setup-root-conf.toml.
		python3 - "${ESP}/loader/entries/${LIVE_ID}.conf" "/${live_cpio#"${ESP%/}"/}" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
lines = path.read_text().splitlines()
initrds = [i for i, line in enumerate(lines) if line.startswith("initrd")]
at = initrds[-1] + 1 if initrds else len(lines)
lines.insert(at, f"initrd {sys.argv[2]}")
path.write_text("\n".join(lines) + "\n")
PY
	fi
	scratch="$(mktemp)"
	python3 "${ENTRY_TOOL}" loader-conf "${ESP}/loader/loader.conf" "${scratch}" "${LIVE_ID}.conf" 5
	cat "${scratch}" >"${ESP}/loader/loader.conf"
	rm -f "${scratch}"
fi
say "${BOOTLOADER}: live entry ${LIVE_ID} ready"
