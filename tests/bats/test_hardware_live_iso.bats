#!/usr/bin/env bats
# Live ISOs for hardware-profile flavors: scripts/lib/hardware-live.sh and
# scripts/x13s-live-inputs.sh (tunaOS#3368, tuna-os/tacklebox#388).
#
# WHY: a hardware flavor such as bonito:gnome-x13s needs boot media made for
# its machine. build-iso-tacklebox.sh used to build the generic ISO for any
# flavor, which for the X13s is media that cannot boot it. The route now
# comes from the flavor's hardware profile, never from its name, and a
# profile without a live path fails instead of falling back.
#
# Falsification: make tunaos_live_iso_route print "generic" for t2, match
# the route on the flavor name, drop --network=none from the image runs, or
# take the loader from a URL that ignores the kernel-core key, and a test
# here fails.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

setup() {
	# shellcheck source=../../scripts/lib/hardware-live.sh
	. "${REPO_ROOT}/scripts/lib/hardware-live.sh"
}

@test "flavor hardware comes from the generated hardware profiles" {
	[ "$(tunaos_flavor_hardware bonito gnome-x13s)" = x13s ]
	[ "$(tunaos_flavor_hardware marlin gnome-x13s)" = x13s ]
	[ "$(tunaos_flavor_hardware bonito gnome)" = "" ]
	[ "$(tunaos_flavor_hardware yellowfin gnome)" = "" ]
}

@test "the route follows the profile, not the flavor name" {
	local profiles="${BATS_TEST_TMPDIR}/profiles.json"
	echo '{"flavors":{"bonito":{"laptop":{"hardware":"x13s"},"gnome-x13s":{}}}}' >"$profiles"
	[ "$(TUNAOS_HARDWARE_PROFILES_JSON="$profiles" tunaos_flavor_hardware bonito laptop)" = x13s ]
	[ "$(TUNAOS_HARDWARE_PROFILES_JSON="$profiles" tunaos_flavor_hardware bonito gnome-x13s)" = "" ]
}

@test "generic flavors keep the generic route on every platform" {
	[ "$(tunaos_live_iso_route "" linux/amd64)" = generic ]
	[ "$(tunaos_live_iso_route "" linux/arm64)" = generic ]
}

@test "the X13s profile routes to the X13s live path on arm64 only" {
	[ "$(tunaos_live_iso_route x13s linux/arm64)" = x13s ]
	run tunaos_live_iso_route x13s linux/amd64
	[ "$status" -ne 0 ]
	[[ "$output" == *"hardware profile 'x13s' has no live ISO path on linux/amd64"* ]]
}

@test "every other hardware profile fails loudly instead of building the generic ISO" {
	local profile
	for profile in $(jq -r '.profiles | keys[]' "${REPO_ROOT}/build_scripts/lib/hardware-profiles.json"); do
		[ "$profile" = x13s ] && continue
		run tunaos_live_iso_route "$profile" linux/amd64
		[ "$status" -ne 0 ]
		[[ "$output" == *"hardware profile '${profile}' has no live ISO path"* ]]
	done
}

@test "the boot gate waits for the X13s barrier, not the desktop, on X13s media" {
	[ "$(tunaos_live_iso_boot_marker generic)" = 'TUNAOS_LIVE_READY|TBOX_LIVE_READY' ]
	[ "$(tunaos_live_iso_boot_marker x13s)" = 'Tacklebox: X13s external root blocked' ]
	run tunaos_live_iso_boot_marker t2
	[ "$status" -ne 0 ]
}

@test "build-iso-tacklebox.sh decides the route before it pulls the image" {
	local script="${REPO_ROOT}/scripts/build-iso-tacklebox.sh"
	local route pull
	route=$(grep -n 'LIVE_ROUTE="$(tunaos_live_iso_route' "$script" | head -1 | cut -d: -f1)
	pull=$(grep -nE '^[^#]*podman pull' "$script" | head -1 | cut -d: -f1)
	[ -n "$route" ]
	[ -n "$pull" ]
	[ "$route" -lt "$pull" ]
	grep -q 'tunaos_flavor_hardware "$VARIANT" "$FLAVOR"' "$script"
	grep -q -- '--x13s-live "${X13S_INPUTS}/manifest.json"' "$script"
}

# ── scripts/x13s-live-inputs.sh with stub podman and curl ──────────────────

KEYID="dbfcf71c6d9f90a6"

make_stubs() {
	local bin="${BATS_TEST_TMPDIR}/bin"
	mkdir -p "$bin"
	cat >"${bin}/podman" <<-EOF
		#!/usr/bin/env bash
		# Stub podman run: record the call, then do what the image script would.
		printf '%s\n' "\$*" >>"${BATS_TEST_TMPDIR}/podman.log"
		out=""
		while (("\$#")); do
		  if [[ "\$1" == -v ]]; then out="\${2%%:/out}"; shift 2; continue; fi
		  if [[ "\$1" == -c ]]; then script="\$2"; break; fi
		  shift
		done
		if [[ "\$script" == *image.txt* ]]; then
		  printf 'shim' >"\$out/shimaa64.efi"
		  printf 'grubgrub' >"\$out/grubaa64.efi"
		  {
		    echo "kver=7.3.4-200.fc44.aarch64"
		    echo "version=7.3.4"
		    echo "release=200.fc44"
		    echo "srpm=kernel-7.3.4-200.fc44.src.rpm"
		    echo "keyid=${KEYID}"
		    echo "kernel_sha256=$(printf '%064d' 0)"
		    echo "fedora=44"
		    echo "shim=/usr/lib/efi/shim/16.1-7/EFI/fedora/shimaa64.efi"
		    echo "shim_package=shim-aa64-16.1-7.aarch64"
		    echo "grub=/usr/lib/efi/grub2/1:2.12-66.fc44/EFI/fedora/grubaa64.efi"
		    echo "grub_package=grub2-efi-aa64-2.12-66.fc44.aarch64"
		  } >"\$out/image.txt"
		else
		  [[ -f "\$out/loader.rpm" ]] || exit 9
		  printf 'loader-bytes' >"\$out/vmlinuz-dtbloader.efi"
		  printf 'Header SHA256 digest: OK\n' >"\$out/rpmkeys.txt"
		fi
	EOF
	cat >"${bin}/curl" <<-EOF
		#!/usr/bin/env bash
		printf '%s\n' "\$*" >>"${BATS_TEST_TMPDIR}/curl.log"
		while (("\$#")); do [[ "\$1" == -o ]] && { printf 'rpm' >"\$2"; exit 0; }; shift; done
		exit 1
	EOF
	chmod +x "${bin}/podman" "${bin}/curl"
	PATH="${bin}:${PATH}"
}

IMAGE="ghcr.io/tuna-os/bonito@sha256:$(printf '%064d' 1)"

@test "x13s-live-inputs refuses an image that is not sha256-pinned" {
	make_stubs
	run bash "${REPO_ROOT}/scripts/x13s-live-inputs.sh" ghcr.io/tuna-os/bonito:gnome-x13s "${BATS_TEST_TMPDIR}/out"
	[ "$status" -ne 0 ]
	[[ "$output" == *"not a sha256-pinned image reference"* ]]
	[ ! -e "${BATS_TEST_TMPDIR}/podman.log" ]
}

@test "x13s-live-inputs pins every input it writes into the manifest" {
	make_stubs
	local out="${BATS_TEST_TMPDIR}/out"
	run bash "${REPO_ROOT}/scripts/x13s-live-inputs.sh" "$IMAGE" "$out"
	[ "$status" -eq 0 ]

	# The loader is the exact kernel build, from the tree of kernel-core's key.
	grep -qx -- "-fsSL --retry 3 --retry-delay 5 -o ${out}/loader.rpm https://kojipkgs.fedoraproject.org/packages/kernel/7.3.4/200.fc44/data/signed/6d9f90a6/aarch64/kernel-uki-dtbloader-7.3.4-200.fc44.aarch64.rpm" \
		"${BATS_TEST_TMPDIR}/curl.log"
	# The image runs twice, pinned, and never with network.
	[ "$(grep -c -- "--network=none" "${BATS_TEST_TMPDIR}/podman.log")" -eq 2 ]
	[ "$(grep -c -- "$IMAGE" "${BATS_TEST_TMPDIR}/podman.log")" -eq 2 ]
	[ ! -e "${out}/loader.rpm" ]

	local m="${out}/manifest.json"
	[ "$(jq -r .mode "$m")" = fedora-arm64-dtbloader ]
	[ "$(jq -r .board "$m")" = lenovo,thinkpad-x13s ]
	[ "$(jq -r .kernel_release "$m")" = 7.3.4-200.fc44.aarch64 ]
	local name file
	for name in shim grub loader preparation_receipt; do
		file="${out}/$(jq -r ".${name}.path" "$m")"
		[ -f "$file" ]
		[ "$(jq -r ".${name}.size" "$m")" = "$(stat -c %s "$file")" ]
		[ "$(jq -r ".${name}.sha256" "$m")" = "$(sha256sum "$file" | cut -d' ' -f1)" ]
	done
	local r="${out}/preparation-receipt.json"
	[ "$(jq -r .image "$r")" = "$IMAGE" ]
	[ "$(jq -r .loader.source_rpm "$r")" = kernel-7.3.4-200.fc44.src.rpm ]
	[ "$(jq -r .kernel.signing_key_id "$r")" = "$KEYID" ]
	[ "$(jq -r .loader.rpm_sha256 "$r")" = "$(printf 'rpm' | sha256sum | cut -d' ' -f1)" ]
	[[ "$(jq -r .loader.checksig "$r")" == *"Header SHA256 digest: OK"* ]]
}

@test "x13s-live-inputs fails when the image observation is incomplete" {
	make_stubs
	sed -i '/echo "keyid=/d' "${BATS_TEST_TMPDIR}/bin/podman"
	run bash "${REPO_ROOT}/scripts/x13s-live-inputs.sh" "$IMAGE" "${BATS_TEST_TMPDIR}/out"
	[ "$status" -ne 0 ]
	[[ "$output" == *"the image observation has no keyid"* ]]
	[ ! -e "${BATS_TEST_TMPDIR}/curl.log" ]
}

@test "x13s-live-inputs verifies the loader inside the image" {
	local script="${REPO_ROOT}/scripts/x13s-live-inputs.sh"
	grep -q 'define "_pkgverify_level all" --checksig' "$script"
	grep -q 'RPM-GPG-KEY-fedora-${fedora}-primary' "$script"
	grep -q '"kernel-uki-dtbloader $version $release aarch64 $srpm"' "$script"
	grep -q '\[ "$signer" = "$keyid" \]' "$script"
}
