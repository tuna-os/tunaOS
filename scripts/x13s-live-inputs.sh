#!/usr/bin/env bash
# scripts/x13s-live-inputs.sh — stage the inputs of an experimental Lenovo
# ThinkPad X13s live ISO for `tacklebox build --x13s-live`
# (tuna-os/tacklebox#388, tunaOS#3368).
#
# Usage: scripts/x13s-live-inputs.sh <image@sha256:digest> <out-dir>
#
# Writes into <out-dir>:
#   shimaa64.efi, grubaa64.efi  Fedora shim and GRUB, copied from the image
#   vmlinuz-dtbloader.efi       Fedora's kernel-uki-dtbloader loader for the
#                               image's own kernel build
#   preparation-receipt.json    what this script checked, and how
#   manifest.json               the liveboot.Manifest that tacklebox reads
#
# Every input is pinned. Nothing comes from an unpinned download:
#   - The image is a sha256 reference, and runs with no network.
#   - shim and GRUB are the image's files, owned by RPMs in the image.
#   - The loader RPM is the exact version-release of the image's kernel-core,
#     from the Koji tree signed by the key that signed kernel-core. rpmkeys
#     checks its signature and digests against the Fedora key in the image,
#     and its SOURCERPM must equal the SOURCERPM of kernel-core.
#   - tacklebox then requires the loader's .linux bytes to equal the image's
#     vmlinuz, byte for byte.
#
# Runs as root on an aarch64 host, from build-iso-tacklebox.sh.

set -euo pipefail

IMAGE="${1:?usage: $0 <image@sha256:digest> <out-dir>}"
OUT="${2:?usage: $0 <image@sha256:digest> <out-dir>}"
KOJI="${TUNAOS_KOJI_PACKAGES_URL:-https://kojipkgs.fedoraproject.org/packages}"

if [[ ! "$IMAGE" =~ @sha256:[0-9a-f]{64}$ ]]; then
	echo "ERROR: x13s-live-inputs: ${IMAGE} is not a sha256-pinned image reference" >&2
	exit 1
fi
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

run_image() {
	# --log-driver=k8s-file: the runner images lack journald for conmon
	# (tunaOS#1893). --network=none: the image never fetches anything here.
	podman run --rm --network=none --log-driver=k8s-file --security-opt label=disable \
		-v "${OUT}:/out" --entrypoint /bin/sh "$IMAGE" -c "$1" x13s-live-inputs "${@:2}"
}

# ── 1. Observe the image ────────────────────────────────────────────────────
# shellcheck disable=SC2016 # expanded by the image's shell
run_image '
set -eu
fail() { echo "x13s-live-inputs: $*" >&2; exit 1; }
set -- /usr/lib/modules/*/vmlinuz
[ "$#" -eq 1 ] && [ -f "$1" ] || fail "the image must hold exactly one kernel"
vmlinuz=$1
kver=$(basename "$(dirname "$vmlinuz")")
q() { rpm -qf --qf "$1" "$vmlinuz"; }
[ "$(q "%{NAME} %{ARCH}")" = "kernel-core aarch64" ] || fail "$vmlinuz is not from an aarch64 kernel-core"
keyid=$(q "%{RSAHEADER:pgpsig}" | sed -n "s/.*Key ID \([0-9a-f]\{16\}\).*/\1/p")
# rpm -ql lists /boot/efi copies first; bootc images keep only /usr/lib/efi.
first_file() { while read -r f; do [ -f "$f" ] && { echo "$f"; return; }; done; }
shim=$(rpm -ql shim-aa64 | grep "/EFI/fedora/shimaa64\.efi$" | first_file)
grub=$(rpm -ql grub2-efi-aa64 | grep "/EFI/fedora/grubaa64\.efi$" | first_file)
[ -f "$shim" ] || fail "shim-aa64 has no shimaa64.efi"
[ -f "$grub" ] || fail "grub2-efi-aa64 has no grubaa64.efi"
cp "$shim" /out/shimaa64.efi
cp "$grub" /out/grubaa64.efi
. /etc/os-release
{
  echo "kver=$kver"
  echo "version=$(q "%{VERSION}")"
  echo "release=$(q "%{RELEASE}")"
  echo "srpm=$(q "%{SOURCERPM}")"
  echo "keyid=$keyid"
  echo "kernel_sha256=$(sha256sum "$vmlinuz" | cut -d" " -f1)"
  echo "fedora=$VERSION_ID"
  echo "shim=$shim"
  echo "shim_package=$(rpm -qf "$shim")"
  echo "grub=$grub"
  echo "grub_package=$(rpm -qf "$grub")"
} > /out/image.txt
'

declare -A obs=()
while IFS='=' read -r key value; do
	[[ -n "$key" ]] && obs[$key]="$value"
done <"${OUT}/image.txt"
rm -f "${OUT}/image.txt"
for key in kver version release srpm keyid kernel_sha256 fedora shim shim_package grub grub_package; do
	if [[ -z "${obs[$key]:-}" ]]; then
		echo "ERROR: x13s-live-inputs: the image observation has no ${key}" >&2
		exit 1
	fi
done

# ── 2. Fetch the loader RPM of that exact kernel build ──────────────────────
# Koji keeps every build, and data/signed/<key> holds the copies signed with
# that key. The short key ID is the last 8 hex digits of the 16-digit one.
rpm_name="kernel-uki-dtbloader-${obs[version]}-${obs[release]}.aarch64.rpm"
url="${KOJI}/kernel/${obs[version]}/${obs[release]}/data/signed/${obs[keyid]: -8}/aarch64/${rpm_name}"
echo "==> X13s loader: ${url}"
curl -fsSL --retry 3 --retry-delay 5 -o "${OUT}/loader.rpm" "$url"
rpm_sha256="$(sha256sum "${OUT}/loader.rpm" | cut -d' ' -f1)"

# ── 3. Verify it with the image's Fedora key and extract the loader ─────────
# shellcheck disable=SC2016 # expanded by the image's shell
run_image '
set -eu
fail() { echo "x13s-live-inputs: $*" >&2; exit 1; }
kver=$1 version=$2 release=$3 srpm=$4 keyid=$5 fedora=$6
rpm=/out/loader.rpm
db=$(mktemp -d)
rpmkeys --dbpath "$db" --import "/etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-${fedora}-primary" || fail "cannot import the Fedora ${fedora} key"
rpmkeys --dbpath "$db" --define "_pkgverify_level all" --checksig --verbose "$rpm" > /out/rpmkeys.txt 2>&1 \
  || { cat /out/rpmkeys.txt >&2; fail "the loader RPM signature or digest check failed"; }
[ "$(rpm -qp --nosignature --qf "%{NAME} %{VERSION} %{RELEASE} %{ARCH} %{SOURCERPM}" "$rpm")" = \
  "kernel-uki-dtbloader $version $release aarch64 $srpm" ] || fail "the loader RPM is not from $srpm"
signer=$(rpm -qp --nosignature --qf "%{RSAHEADER:pgpsig}" "$rpm" | sed -n "s/.*Key ID \([0-9a-f]\{16\}\).*/\1/p")
[ "$signer" = "$keyid" ] || fail "the loader RPM is signed by $signer, kernel-core by $keyid"
work=$(mktemp -d)
cd "$work"
rpm2cpio "$rpm" | cpio -idm --quiet "./lib/modules/$kver/vmlinuz-dtbloader.efi"
[ -f "./lib/modules/$kver/vmlinuz-dtbloader.efi" ] || fail "the loader RPM has no vmlinuz-dtbloader.efi for $kver"
cp "./lib/modules/$kver/vmlinuz-dtbloader.efi" /out/vmlinuz-dtbloader.efi
' "${obs[kver]}" "${obs[version]}" "${obs[release]}" "${obs[srpm]}" "${obs[keyid]}" "${obs[fedora]}"
rm -f "${OUT}/loader.rpm"

# ── 4. Write the preparation receipt and the manifest ───────────────────────
jq -n \
	--arg image "$IMAGE" \
	--arg kver "${obs[kver]}" \
	--arg srpm "${obs[srpm]}" \
	--arg keyid "${obs[keyid]}" \
	--arg kernel_sha256 "${obs[kernel_sha256]}" \
	--arg url "$url" \
	--arg rpm_sha256 "$rpm_sha256" \
	--arg rpm_name "$rpm_name" \
	--rawfile checksig "${OUT}/rpmkeys.txt" \
	--arg shim "${obs[shim]}" --arg shim_package "${obs[shim_package]}" \
	--arg grub "${obs[grub]}" --arg grub_package "${obs[grub_package]}" \
	--arg fedora "${obs[fedora]}" \
	'{
		schema: "tunaos/x13s-live-preparation/v1",
		image: $image,
		kernel: {release: $kver, source_rpm: $srpm, signing_key_id: $keyid, vmlinuz_sha256: $kernel_sha256},
		loader: {rpm: $rpm_name, url: $url, rpm_sha256: $rpm_sha256, source_rpm: $srpm,
			checksig_key: ("/etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-" + $fedora + "-primary in the image"),
			checksig: $checksig},
		shim: {path_in_image: $shim, package: $shim_package},
		grub: {path_in_image: $grub, package: $grub_package},
		note: "rpmkeys checked the loader RPM in the pinned image. shim and GRUB are the image files; their signatures were not checked here."
	}' >"${OUT}/preparation-receipt.json"
rm -f "${OUT}/rpmkeys.txt"

input() {
	jq -n --arg path "$1" --argjson size "$(stat -c %s "${OUT}/$1")" \
		--arg sha256 "$(sha256sum "${OUT}/$1" | cut -d' ' -f1)" \
		'{path: $path, size: $size, sha256: $sha256}'
}
jq -n \
	--arg kver "${obs[kver]}" \
	--arg kernel_sha256 "${obs[kernel_sha256]}" \
	--argjson shim "$(input shimaa64.efi)" \
	--argjson grub "$(input grubaa64.efi)" \
	--argjson loader "$(input vmlinuz-dtbloader.efi)" \
	--argjson receipt "$(input preparation-receipt.json)" \
	'{mode: "fedora-arm64-dtbloader", board: "lenovo,thinkpad-x13s", architecture: "arm64",
	  kernel_release: $kver, kernel_sha256: $kernel_sha256,
	  shim: $shim, grub: $grub, loader: $loader, preparation_receipt: $receipt}' >"${OUT}/manifest.json"
echo "==> X13s live inputs for ${obs[kver]}: ${OUT}/manifest.json"
