#!/usr/bin/env bats
# Dry-run coverage for installer-medium build scripts (tunaOS#4907, #4913).
#
# Every stage of build-medium.sh runs with --dry-run here: no root, no loop
# devices, no image builds. The tests assert each stage prints its contract
# command (bootc install with the cell backend, --el-torito=yes repart,
# CopyBlocks definitions, the fixed Flatpak set, chunked OCI layout).

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
MEDIUM="${REPO_ROOT}/installer-medium"

@test "build-medium dry-run binds RAW/MNT and calls the real publish script" {
  run "${MEDIUM}/build-medium.sh" albacore:gnome /tmp/medium-test.iso --dry-run
  [ "$status" -eq 0 ]
  # RAW used to be unbound: the script died under set -u before any stage ran.
  [[ "$output" == *"/medium-raw.img"* ]]
  # There is no chunk-publish.sh; the producer is the Python script.
  [[ "$output" == *"chunk-publish.py"* ]]
  [[ "$output" == *"/tmp/medium-test.iso"* ]]
}

@test "build-to-disk resolves the cell and prints the bootc command" {
  run "${MEDIUM}/build-to-disk.sh" albacore:gnome /tmp/medium-test.raw --dry-run
  [ "$status" -eq 0 ]
  # GRUB cannot open the encrypted root: /boot is a partition of its own.
  [[ "$output" == *"bootc install to-filesystem"* ]]
  [[ "$output" == *"/boot 2048 MiB (ext4), root (xfs)"* ]]
  [[ "$output" == *"rhgb"* ]]
}

@test "build-to-disk prints composefs and systemd-boot for tromso:kde" {
  run "${MEDIUM}/build-to-disk.sh" tromso:kde /tmp/medium-test.raw --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"--composefs-backend"* ]]
  [[ "$output" == *"--bootloader systemd"* ]]
}

@test "each BuildStream sibling cell installs its own published image, ext4 on composefs" {
  for pair in tromso:kde=ghcr.io/tuna-os/tromso:latest brussels:xfce=ghcr.io/tuna-os/brussels:latest; do
    run "${MEDIUM}/build-to-disk.sh" "${pair%%=*}" /tmp/medium-test.raw --dry-run
    [ "$status" -eq 0 ]
    [[ "$output" == *"--target-imgref ${pair#*=} "* ]]
    [[ "$output" == *"--filesystem ext4 --composefs-backend --bootloader systemd"* ]]
    run bash -u "${MEDIUM}/verify-cell-layout.sh" "${pair%%=*}" --dry-run
    [ "$status" -eq 0 ]
    [[ "$output" == *"expects bootloader=systemd composeFsBackend=true filesystem=ext4"* ]]
  done
}

@test "add-live-entry dry-run names the grub entry and ESP payload" {
  run "${MEDIUM}/add-live-entry.sh" albacore:gnome /tmp/root /tmp/esp --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"grub"* ]]
  [[ "$output" == *"EFI/tunaos-live"* ]]
}

@test "add-live-entry dry-run names the systemd-boot entry and live initrd" {
  run "${MEDIUM}/add-live-entry.sh" tromso:kde /tmp/root /tmp/esp --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"systemd-boot"* ]]
  [[ "$output" == *"live initrd"* ]]
}

@test "build-hybrid dry-run requires --el-torito=yes" {
  run "${MEDIUM}/repart/build-hybrid.sh" albacore:gnome /tmp/medium-test.raw /tmp/medium-test.iso --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"--el-torito=yes"* ]]
}

@test "bake-flatpaks dry-run lists the fixed set for each cell" {
  run "${MEDIUM}/flatpak/bake-flatpaks.sh" albacore:gnome /tmp/root --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"org.mozilla.firefox"* ]]
  [[ "$output" == *"com.mattjakeman.ExtensionManager"* ]]
  run "${MEDIUM}/flatpak/bake-flatpaks.sh" tromso:kde /tmp/root --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" != *"ExtensionManager"* ]]
  # A native frontend's Flatpak is left out of the check (run 45902212282).
  run "${MEDIUM}/flatpak/bake-flatpaks.sh" bonito:xfce /tmp/root --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"--installer org.tunaos.InstallerXfce --store"* ]]
}

@test "live layer ships a drop-in for every skipped unit" {
  for unit in flatpak-preinstall.service bootc-fetch-apply-updates.timer uupd.service \
      brew-setup.service bootloader-update.service remove-installer.service secure-boot-update.service \
      systemd-fsck@.service; do
    [ -f "${MEDIUM}/live/usr/lib/systemd/system/${unit}.d/50-medium-live.conf" ]
  done
  [ -f "${MEDIUM}/live/usr/lib/systemd/user/brew-preinstall.service.d/50-medium-live.conf" ]
  [ -f "${MEDIUM}/live/usr/lib/dracut/modules.d/90medium-sr0/medium-sr0.sh" ]
}

@test "the initrd attaches a disc in blocks of 512 bytes, keeps one with partitions and detaches any other" {
  # A pre-mount hook ran after the wait for the root device, which is on the disc.
  dir="${MEDIUM}/live/usr/lib/dracut/modules.d/90medium-sr0"
  ! grep -q 'inst_hook' "${dir}/module-setup.sh"
  grep -q 'SYSTEMD_WANTS}+="medium-sr0@%k.service"' "${dir}/61-medium-sr0.rules"
  bin="$(mktemp -d)"
  printf '#!/bin/sh\necho "losetup $*" >>"%s/log"\ncase "$*" in *--show*) echo /dev/loop9 ;; esac\n' "${bin}" >"${bin}/losetup"
  printf '#!/bin/sh\nexit 0\n' >"${bin}/udevadm"
  # The initrd of a GNOME OS image has no dd: nothing may call it.
  printf '#!/bin/sh\nexit 99\n' >"${bin}/dd"
  chmod +x "${bin}"/*
  sys="$(mktemp -d)"
  # A disc that holds no partition 1 is detached again.
  SYS_CLASS_BLOCK="${sys}" PATH="${bin}:${PATH}" run sh "${dir}/medium-sr0.sh" sr0
  [ "$status" -eq 0 ]
  [ "$(cat "${bin}/log")" = "losetup --read-only --partscan --sector-size 512 --find --show /dev/sr0
losetup --detach /dev/loop9" ]
  rm "${bin}/log"
  # The disc of the medium has the partitions of its GPT.
  touch "${sys}/loop9p1"
  SYS_CLASS_BLOCK="${sys}" PATH="${bin}:${PATH}" run sh "${dir}/medium-sr0.sh" sr0
  [ "$status" -eq 0 ]
  [ "$(cat "${bin}/log")" = "losetup --read-only --partscan --sector-size 512 --find --show /dev/sr0" ]
  rm -rf "${bin}" "${sys}"
}

# build-medium.sh itself: every supported cell of the resolver (promoted or
# not) must run end to end in dry-run mode under `bash -u`, so an unassigned
# variable (RAW, MNT) or a stage script that does not exist or is not
# executable fails here, not in CI. Prints "cell frontend desktop" rows.
medium_cells() {
	python3 -c 'import importlib.util, sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
for row in c.installer_medium_policy().cells(c.load(root / "tunaos.toml")):
    print(row["cell"], row["frontend"], row["desktop"])' "${REPO_ROOT}"
}

medium_cells_with_status() {
	python3 -c 'import importlib.util, sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("c", root / "scripts/lib/tunaos_config.py")
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
for row in c.installer_medium_policy().resolve(c.load(root / "tunaos.toml")):
    if row["status"] == sys.argv[2]:
        print(row["cell"])' "${REPO_ROOT}" "$1"
}

@test "build-medium dry-run completes under bash -u for every supported cell" {
	cells="$(medium_cells)"
	# More than the seven promoted cells: the loop covers the whole matrix.
	[ "$(wc -l <<<"${cells}")" -gt 7 ]
	out="${BATS_TEST_TMPDIR}/out.iso"
	while read -r cell frontend desktop; do
		run bash -u "${MEDIUM}/build-medium.sh" "${cell}" "${out}" --dry-run
		[ "${status}" -eq 0 ] || { echo "cell ${cell}: ${output}" >&2; false; }
		[[ "${output}" != *"unbound variable"* ]] || { echo "cell ${cell}: ${output}" >&2; false; }
		[[ "${output}" == *"install-frontend: ${frontend} -> /stage"* ]] || { echo "cell ${cell}: no frontend ${frontend}" >&2; false; }
		[[ "${output}" != *"WARNING"* ]] || { echo "cell ${cell}: ${output}" >&2; false; }
		[[ "${output}" == *"verify-layout: ${cell} expects"* ]]
		[[ "${output}" == *"build-to-disk.sh ${cell} "*"/medium-raw.img --dry-run"* ]]
		[[ "${output}" == *"flatpak: bake "*" apps for ${desktop} into"* ]] || { echo "cell ${cell}: flatpak set is not for ${desktop}" >&2; false; }
		[[ "${output}" == *"publish/chunk-publish.py ${cell} ${out} "*"--dry-run"* ]]
		[[ "${output}" == *"medium: ${out} ready"* ]]
	done <<<"${cells}"
}

@test "build-medium refuses an unverified or headless cell with the reason" {
	for kind in unverified no-medium; do
		cell="$(medium_cells_with_status "${kind}" | head -1)"
		[ -n "${cell}" ]
		run bash -u "${MEDIUM}/build-medium.sh" "${cell}" "${BATS_TEST_TMPDIR}/out.iso" --dry-run
		[ "${status}" -ne 0 ]
		[[ "${output}" == *"is ${kind}"* ]]
		[[ "${output}" != *"ready"* ]]
	done
}

@test "resolve-cell-image prints the published ref, with the variant tag suffix" {
	run "${MEDIUM}/resolve-cell-image.sh" bonito:kde
	[ "$status" -eq 0 ]
	[[ "${output}" == *"/bonito:kde" ]]
	if medium_cells | grep -q '^bonito-rawhide:gnome '; then
		run "${MEDIUM}/resolve-cell-image.sh" bonito-rawhide:gnome
		[ "$status" -eq 0 ]
		[[ "${output}" == *"/bonito:gnome-rawhide" ]]
	fi
	run "${MEDIUM}/resolve-cell-image.sh" bonito:base
	[ "$status" -ne 0 ]
	[[ "${output}" == *"no-medium"* ]]
}

@test "a hardware flavor takes the frontend, flatpak set and input path of its desktop" {
	cell="$(medium_cells | awk '$1 ~ /:cosmic-/ {print $1; exit}')"
	[ -n "${cell}" ] || skip "no supported cosmic hardware cell in the evidence"
	run python3 "${REPO_ROOT}/scripts/installer-e2e/matrix.py" --cell "${cell}"
	[ "$status" -eq 0 ]
	[[ "${output}" == *'"input": "ocr-fallback"'* ]]
	[[ "${output}" == *'"gpu": true'* ]]
	[[ "${output}" == *'"frontend": "cosmic"'* ]]
}

@test "the workflow matrix is the promoted cells by default and any supported cell by name" {
	run python3 "${REPO_ROOT}/scripts/installer-e2e/matrix.py"
	[ "$status" -eq 0 ]
	[ "$(jq '.include | length' <<<"${output}")" -eq 7 ]
	[ "$(jq '[.include[] | select(.promoted)] | length' <<<"${output}")" -eq 7 ]
	run python3 "${REPO_ROOT}/scripts/installer-e2e/matrix.py" --cell bonito:base
	[ "$status" -ne 0 ]
	[[ "${output}" == *"no-medium"* ]]
	run python3 "${REPO_ROOT}/scripts/installer-e2e/matrix.py" --cell bonito:plasma
	[ "$status" -ne 0 ]
	# An arm64-only cell is supported for a build, but the workflow has no arm64 lane.
	if medium_cells | grep -q '^bonito:gnome-x13s '; then
		run python3 "${REPO_ROOT}/scripts/installer-e2e/matrix.py" --cell bonito:gnome-x13s
		[ "$status" -ne 0 ]
		[[ "${output}" == *"no arm64 lane"* ]]
	fi
}

@test "verify-cell-layout prints the expected layout and the probe command in a dry run" {
	run bash -u "${MEDIUM}/verify-cell-layout.sh" bonito:kde --dry-run
	[ "$status" -eq 0 ]
	[[ "${output}" == *"expects bootloader=grub2 composeFsBackend=false filesystem=btrfs"* ]]
	[[ "${output}" == *"TUNAOS_INSTALLER_ALLOW_BTRFS=1"*"installer-recipe-backend.sh"*"medium-live-bonito-kde"* ]]
	run bash -u "${MEDIUM}/verify-cell-layout.sh" tromso:kde --dry-run
	[ "$status" -eq 0 ]
	[[ "${output}" == *"expects bootloader=systemd composeFsBackend=true filesystem=ext4"* ]]
}

@test "build-medium dry-run creates no work directory and needs no root" {
	run env MEDIUM_WORK="${BATS_TEST_TMPDIR}/work" bash -u "${MEDIUM}/build-medium.sh" \
		albacore:gnome "${BATS_TEST_TMPDIR}/out.iso" --dry-run
	[ "${status}" -eq 0 ]
	[ ! -e "${BATS_TEST_TMPDIR}/work" ]
	[ ! -e "${BATS_TEST_TMPDIR}/out.iso" ]
}

@test "every script build-medium.sh names exists and is executable" {
	scripts="$(grep -o '"\${HERE}/[A-Za-z0-9_./-]*"' "${MEDIUM}/build-medium.sh" | tr -d '"' | sed "s#\${HERE}#${MEDIUM}#" | sort -u)"
	[ -n "${scripts}" ]
	while read -r s; do
		[ -x "${s}" ] || { echo "not executable or missing: ${s}" >&2; false; }
	done <<<"${scripts}"
}

@test "installer-medium shell scripts pass shellcheck" {
	command -v shellcheck >/dev/null || skip "shellcheck not installed"
	run bash -c "cd '${REPO_ROOT}' && git ls-files 'installer-medium/*.sh' | xargs shellcheck"
	[ "${status}" -eq 0 ] || { echo "${output}" >&2; false; }
}

@test "live image build names the daemon, its pinned commit and the desktop frontend for every cell" {
	ref="$(python3 -c 'import sys, tomllib
print(tomllib.load(open(sys.argv[1] + "/tunaos.toml", "rb"))["installer_medium"]["fisherman_ref"])' "${REPO_ROOT}")"
	[[ "${ref}" =~ ^[0-9a-f]{40}$ ]]
	cells="$(medium_cells)"
	while read -r cell frontend _; do
		run bash -u "${MEDIUM}/build-live-image.sh" "${cell}" --dry-run
		[ "${status}" -eq 0 ] || { echo "cell ${cell}: ${output}" >&2; false; }
		[[ "${output}" == *"live: frontend ${frontend}, fishermand https://github.com/tuna-os/fisherman.git @ ${ref}"* ]]
		[[ "${output}" == *"build-fishermand.sh"* || "${output}" == *"fishermand: "* ]]
		[[ "${output}" == *"install-frontend: ${frontend} -> /stage"* ]]
	done <<<"${cells}"
}

@test "build-medium runs the live layer, which carries the daemon and frontend, before repart" {
	run bash -u "${MEDIUM}/build-medium.sh" bonito:kde "${BATS_TEST_TMPDIR}/out.iso" --dry-run
	[ "${status}" -eq 0 ]
	live="${output%%build-to-disk.sh*}"
	[[ "${live}" == *"fishermand:"* ]]
	[[ "${live}" == *"install-frontend: kde"* ]]
	[[ "${output%%repart/build-hybrid.sh*}" == *"install-frontend: kde"* ]]
}

@test "the dispatcher rejects an unknown desktop and a host root" {
	run "${MEDIUM}/frontends/install-frontend.sh" plasma "${BATS_TEST_TMPDIR}"
	[ "${status}" -ne 0 ]
	[[ "${output}" == *"unknown desktop"* ]]
	run "${MEDIUM}/frontends/install-frontend.sh" gnome /
	[ "${status}" -ne 0 ]
	# `base` has no frontend: the dispatcher never invents one.
	run "${MEDIUM}/frontends/install-frontend.sh" base "${BATS_TEST_TMPDIR}"
	[ "${status}" -ne 0 ]
}

@test "build-fishermand refuses a branch ref and a non-https repo" {
	run "${MEDIUM}/daemon/build-fishermand.sh" https://github.com/tuna-os/fisherman.git dev /tmp/x --dry-run
	[ "${status}" -ne 0 ]
	run "${MEDIUM}/daemon/build-fishermand.sh" git@github.com:tuna-os/fisherman.git 2fc33965f294b4ceb3462c3b3877b1938ae77c5d /tmp/x --dry-run
	[ "${status}" -ne 0 ]
}

@test "fisherman-module-dir finds the Go module in the fisherman repo and in the installer repo" {
	old="${BATS_TEST_TMPDIR}/fisherman-repo"
	mkdir -p "${old}/fisherman/cmd/fishermand"
	touch "${old}/fisherman/go.mod"
	run "${MEDIUM}/daemon/fisherman-module-dir.sh" "${old}"
	[ "${status}" -eq 0 ]
	[ "${output}" = "${old}/fisherman" ]
	# tuna-os/installer#495: the module is one level down, under the project directory.
	new="${BATS_TEST_TMPDIR}/installer-repo"
	mkdir -p "${new}/fisherman/fisherman/cmd/fishermand" "${new}/fisherman/docs"
	touch "${new}/fisherman/fisherman/go.mod"
	run "${MEDIUM}/daemon/fisherman-module-dir.sh" "${new}"
	[ "${status}" -eq 0 ]
	[ "${output}" = "${new}/fisherman/fisherman" ]
	# A module without the daemon is no fisherman: say so, build nothing.
	bad="${BATS_TEST_TMPDIR}/other-repo"
	mkdir -p "${bad}/fisherman/cmd/fisherman"
	touch "${bad}/fisherman/go.mod"
	run "${MEDIUM}/daemon/fisherman-module-dir.sh" "${bad}"
	[ "${status}" -ne 0 ]
	[[ "${output}" == *"no Go module with cmd/fishermand"* ]]
}

@test "extensionless medium scripts pass shellcheck" {
	command -v shellcheck >/dev/null || skip "shellcheck not installed"
	run shellcheck "${MEDIUM}/frontends/medium-live-installer" "${MEDIUM}/live/usr/libexec/medium-fishermand" "${MEDIUM}/live/usr/libexec/medium-live-setup"
	[ "${status}" -eq 0 ] || { echo "${output}" >&2; false; }
}

# The dry-run tests above never ran live-entry.py, so a wrong argument order
# in add-live-entry.sh reached the first real build (run 45551665028). These
# two run the script for real on a scratch tree; they need no root.
@test "add-live-entry writes the grub live entry and grubenv on a real tree" {
  T="$(mktemp -d)"
  mkdir -p "${T}/root/boot/loader/entries" "${T}/root/boot/grub2" "${T}/root/boot/ostree/x" "${T}/esp" "${T}/cwd"
  printf 'kernel' >"${T}/root/boot/ostree/x/vmlinuz"
  printf 'initrd' >"${T}/root/boot/ostree/x/initramfs.img"
  printf '# GRUB Environment Block\n' >"${T}/root/boot/grub2/grubenv"
  printf 'title OS\nversion 1\noptions root=UUID=x rw quiet\nlinux /boot/ostree/x/vmlinuz\ninitrd /boot/ostree/x/initramfs.img\n' \
    >"${T}/root/boot/loader/entries/ostree-1.conf"
  cd "${T}/cwd"
  run "${MEDIUM}/add-live-entry.sh" albacore:gnome "${T}/root" "${T}/esp"
  [ "$status" -eq 0 ]
  grep -q '^saved_entry=medium-live$' "${T}/root/boot/grub2/grubenv"
  # bootupd's grub.cfg ignores saved_entry: the default is in custom.cfg, once.
  [ "$(grep -c '^set default="medium-live"$' "${T}/root/boot/grub2/custom.cfg")" -eq 1 ]
  [ "$(stat -c %s "${T}/root/boot/grub2/grubenv")" -eq 1024 ]
  grep -q '^options root=UUID=x quiet ro tunaos.live$' "${T}/root/boot/loader/entries/medium-live.conf"
  # SELinux is enforcing in the live session too (run 45735319352).
  ! grep -q 'enforcing=' "${T}/root/boot/loader/entries/medium-live.conf"
  grep -q '^title OS Live (try or install)$' "${T}/root/boot/loader/entries/medium-live.conf"
  # MEDIUM_LIVE_KARGS adds arguments to the live entry only.
  rm "${T}/root/boot/loader/entries/medium-live.conf"
  MEDIUM_LIVE_KARGS="console=ttyS0,115200 loglevel=6" run "${MEDIUM}/add-live-entry.sh" albacore:gnome "${T}/root" "${T}/esp"
  [ "$status" -eq 0 ]
  grep -q '^options root=UUID=x quiet ro tunaos.live console=ttyS0,115200 loglevel=6$' "${T}/root/boot/loader/entries/medium-live.conf"
  ! grep -q 'console=ttyS0' "${T}/root/boot/loader/entries/ostree-1.conf"
  [ "$(grep -c '^set default="medium-live"$' "${T}/root/boot/grub2/custom.cfg")" -eq 1 ]
  [ "$(cat "${T}/esp/EFI/tunaos-live/vmlinuz")" = kernel ]
  [ "$(cat "${T}/esp/EFI/tunaos-live/initramfs.img")" = initrd ]
  # Nothing lands in the working directory.
  [ -z "$(find "${T}/cwd" -mindepth 1)" ]
  rm -rf "${T}"
}

@test "add-live-entry writes the systemd-boot live entry and loader.conf on a real tree" {
  T="$(mktemp -d)"
  mkdir -p "${T}/root/tmp" "${T}/esp/loader/entries" "${T}/cwd"
  printf 'timeout 0\n' >"${T}/esp/loader/loader.conf"
  printf 'title OS\noptions root=UUID=x rw\nlinux /EFI/Linux/x/vmlinuz\ninitrd /EFI/Linux/x/initrd\n' \
    >"${T}/esp/loader/entries/os.conf"
  cd "${T}/cwd"
  run "${MEDIUM}/add-live-entry.sh" tromso:kde "${T}/root" "${T}/esp"
  [ "$status" -eq 0 ]
  grep -q '^default medium-live.conf$' "${T}/esp/loader/loader.conf"
  grep -q '^timeout 5$' "${T}/esp/loader/loader.conf"
  grep -q 'ro tunaos.live$' "${T}/esp/loader/entries/medium-live.conf"
  [ -s "${T}/esp/EFI/Linux/medium-live/live.initrd" ]
  # An entry that names its root keeps that one root.
  [ "$(grep -o 'root=' "${T}/esp/loader/entries/medium-live.conf" | wc -l)" -eq 1 ]
  # Compressed: systemd-boot joins initrds with no padding, and the kernel
  # takes a plain cpio only at a 4-byte boundary (run 45897897992).
  gzip -t "${T}/esp/EFI/Linux/medium-live/live.initrd"
  gzip -dc "${T}/esp/EFI/Linux/medium-live/live.initrd" | cpio -t --quiet | grep -qx 'usr/lib/composefs/setup-root-conf.toml'
  # A BuildStream image has no dracut, so its initramfs has no medium-sr0:
  # the live initrd carries the loop attach of a CD boot (run 45923277131).
  # Owned by root, as the kernel creates them in the initramfs.
  gzip -dc "${T}/esp/EFI/Linux/medium-live/live.initrd" | cpio -tv --quiet >"${T}/live.list"
  for f in usr/libexec/medium-sr0.sh usr/lib/systemd/system/medium-sr0@.service usr/lib/udev/rules.d/61-medium-sr0.rules; do
    grep -Eq " root +root .* ${f}\$" "${T}/live.list"
  done
  grep -Eq '^-rwxr-xr-x .* usr/libexec/medium-sr0.sh$' "${T}/live.list"
  # The live initrd is a path on the ESP and comes after the image's own.
  [ "$(grep '^initrd ' "${T}/esp/loader/entries/medium-live.conf" | tail -1)" = "initrd /EFI/Linux/medium-live/live.initrd" ]
  ! grep -q "${T}" "${T}/esp/loader/entries/medium-live.conf"
  [ -z "$(find "${T}/cwd" -mindepth 1)" ]
  rm -rf "${T}"
}

@test "add-live-entry names the root of a bootc systemd-boot entry that has none" {
  # bootc writes no root= (gpt-auto finds it). A CD boot has no
  # LoaderDevicePartUUID, so nothing mounted /sysroot (run 45897897992).
  T="$(mktemp -d)"
  mkdir -p "${T}/root/tmp" "${T}/esp/loader/entries" "${T}/cwd"
  printf 'timeout 0\n' >"${T}/esp/loader/loader.conf"
  printf 'title OS\noptions composefs=abc rw\nlinux /EFI/Linux/x/vmlinuz\ninitrd /EFI/Linux/x/initrd\n' \
    >"${T}/esp/loader/entries/os.conf"
  cd "${T}/cwd"
  MEDIUM_ROOT_UUID=1234-abcd run "${MEDIUM}/add-live-entry.sh" tromso:kde "${T}/root" "${T}/esp"
  [ "$status" -eq 0 ]
  grep -q '^options composefs=abc ro tunaos.live root=UUID=1234-abcd' "${T}/esp/loader/entries/medium-live.conf"
  ! grep -q 'root=' "${T}/esp/loader/entries/os.conf"
  # No UUID to name (not a mount, no override): stop, do not ship a CD that cannot boot.
  rm "${T}/esp/loader/entries/medium-live.conf"
  run "${MEDIUM}/add-live-entry.sh" tromso:kde "${T}/root" "${T}/esp"
  [ "$status" -ne 0 ]
  rm -rf "${T}"
}

@test "medium_var_dir finds the var directory of the deployment" {
  T="$(mktemp -d)"
  source "${MEDIUM}/medium-paths.sh"
  # A plain root: /var is ROOT/var.
  [ "$(medium_var_dir "${T}")" = "${T}/var" ]
  # ostree: the sysroot's own var is not what the system sees.
  mkdir -p "${T}/var" "${T}/ostree/deploy/default/var"
  [ "$(medium_var_dir "${T}")" = "${T}/ostree/deploy/default/var" ]
  # Two deployments: refuse, do not pick one.
  mkdir -p "${T}/state/deploy/abc/var"
  run medium_var_dir "${T}"
  [ "$status" -ne 0 ]
  rm -rf "${T}"
}

@test "place-sysext puts the image where the booted ostree system reads it" {
  T="$(mktemp -d)"
  mkdir -p "${T}/root/ostree/deploy/default/var"
  printf 'raw' >"${T}/sysext.raw"
  run "${MEDIUM}/sysext/place-sysext.sh" "${T}/root" "${T}/sysext.raw"
  [ "$status" -eq 0 ]
  [ -f "${T}/root/ostree/deploy/default/var/lib/extensions/medium-sysinstall.raw" ]
  [ ! -e "${T}/root/var/lib/extensions" ]
  rm -rf "${T}"
}

@test "the sysext carries the SELinux label of each path (run 45709421932)" {
  # An unlabeled sysext made /usr/lib64 unlabeled_t in the merged /usr, and
  # confined services could not load a library with enforcing=1.
  T="$(mktemp -d)"
  mkdir -p "${T}/usr/lib64/medium-sysinstall" "${T}/usr/libexec/medium-sysinstall" "${T}/usr/lib/extension-release.d"
  : >"${T}/usr/lib64/medium-sysinstall/libsystemd-shared-medium-sysinstall.so"
  : >"${T}/usr/libexec/medium-sysinstall/systemd-sysinstall"
  run "${MEDIUM}/sysext/selinux-pseudo.sh" "${T}"
  [ "$status" -eq 0 ]
  [[ "$output" == *"/usr x security.selinux=system_u:object_r:usr_t:s0"* ]]
  [[ "$output" == *"/usr/lib64 x security.selinux=system_u:object_r:lib_t:s0"* ]]
  [[ "$output" == *"/usr/lib64/medium-sysinstall/libsystemd-shared-medium-sysinstall.so x security.selinux=system_u:object_r:lib_t:s0"* ]]
  [[ "$output" == *"/usr/libexec/medium-sysinstall/systemd-sysinstall x security.selinux=system_u:object_r:bin_t:s0"* ]]
  [[ "$output" == *"/usr/lib/extension-release.d x security.selinux=system_u:object_r:lib_t:s0"* ]]
  # Every path of the tree has a line.
  [ "$(printf '%s\n' "$output" | wc -l)" -eq "$(cd "${T}" && find . -mindepth 1 | wc -l)" ]
  # The pack step uses the definitions and refuses an image without xattrs.
  grep -q -- '-pf /tmp/labels.pseudo' "${MEDIUM}/sysext/build-sysext.sh"
  grep -q 'Number of xattr ids' "${MEDIUM}/sysext/build-sysext.sh"
  rm -rf "${T}"
}
