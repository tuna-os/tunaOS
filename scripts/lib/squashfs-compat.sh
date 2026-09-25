#!/usr/bin/env bash
# Squashfs compressor compatibility for live ISOs (tunaOS#2705).
#
# tacklebox writes every live squashfs (the rootfs and the offline store) with
# `-comp zstd`, and its recipe cannot choose another compressor. Arch Linux
# ARM's stock linux-aarch64 kernel is built with `# CONFIG_SQUASHFS_ZSTD is
# not set`, so a marlin arm64 live ISO could not mount its own root:
#
#   mount: /run/rootfsbase: fsconfig() failed: Filesystem uses "zstd"
#          compression. This is not supported.
#
# and the boot gate timed out every night. Until tacklebox takes a compressor
# in the recipe, a kernel known to lack zstd gets its squashfs images written
# with xz, which that kernel does support (CONFIG_SQUASHFS_XZ=y).
#
# tacklebox runs mksquashfs from a shell string under
# `sudo -u "$SUDO_USER" podman unshare`, and sudo resets PATH to secure_path.
# A PATH prepend never reaches it; /usr/local/bin does, because secure_path
# lists it before /usr/bin. So the wrapper goes there for the duration of the
# build and is removed afterwards. tunaos_iso_squashfs_compressors then reads
# the compressor back out of the finished ISO, so a tacklebox change that
# bypasses the wrapper fails the build instead of shipping an unbootable ISO.

# Kernels that cannot mount a zstd squashfs, matched two ways because an
# image may carry either signal: the pkgbase an Arch-family kernel writes to
# /usr/lib/modules/<kver>/pkgbase, and the <kver> directory name itself
# (Arch Linux ARM's reads 7.2.7-2-aarch64-ARCH in the failing boot).
TUNAOS_NO_SQUASHFS_ZSTD_PKGBASES=(linux-aarch64)
TUNAOS_NO_SQUASHFS_ZSTD_KVER_RE='-aarch64-ARCH$'

TUNAOS_MKSQUASHFS_SHIM="${TUNAOS_MKSQUASHFS_SHIM:-/usr/local/bin/mksquashfs}"
TUNAOS_MKSQUASHFS_SHIM_TAG="tunaos-squashfs-compat-shim (tunaOS#2705)"

# Succeeds when the kernel list (one pkgbase or module directory name per
# line, as tunaos_image_kernel_pkgbases prints it) names a kernel that cannot
# mount a zstd squashfs.
tunaos_pkgbase_lacks_squashfs_zstd() {
	local kernels="$1" k
	for k in "${TUNAOS_NO_SQUASHFS_ZSTD_PKGBASES[@]}"; do
		grep -qxF "$k" <<<"$kernels" && return 0
	done
	grep -qE -- "$TUNAOS_NO_SQUASHFS_ZSTD_KVER_RE" <<<"$kernels"
}

# Prints the image's kernel pkgbase files and module directory names. Any
# image whose kernel is not listed above prints names that match nothing,
# which means "zstd is fine".
tunaos_image_kernel_pkgbases() {
	local image="${1:?image required}"
	podman run --rm --log-driver=k8s-file --security-opt label=disable \
		--entrypoint /bin/sh "$image" \
		-c 'cat /usr/lib/modules/*/pkgbase 2>/dev/null; ls -1 /usr/lib/modules 2>/dev/null; true'
}

# Writes the wrapper. It rewrites `-comp zstd` to `-comp xz` and drops the
# zstd-only `-Xcompression-level N`; every other argument passes through.
tunaos_install_mksquashfs_xz_shim() {
	local real
	# TUNAOS_REAL_MKSQUASHFS lets tests point the wrapper at a stand-in.
	real="${TUNAOS_REAL_MKSQUASHFS:-$(PATH=/usr/sbin:/usr/bin:/sbin:/bin command -v mksquashfs)}" || {
		echo "ERROR: mksquashfs not found; cannot install the xz wrapper" >&2
		return 1
	}
	if [[ -e "$TUNAOS_MKSQUASHFS_SHIM" ]] &&
		! grep -qF "$TUNAOS_MKSQUASHFS_SHIM_TAG" "$TUNAOS_MKSQUASHFS_SHIM"; then
		echo "ERROR: ${TUNAOS_MKSQUASHFS_SHIM} exists and is not the tunaOS wrapper; refusing to replace it" >&2
		return 1
	fi
	install -d -m 0755 "$(dirname "$TUNAOS_MKSQUASHFS_SHIM")"
	cat >"$TUNAOS_MKSQUASHFS_SHIM" <<EOF
#!/usr/bin/env bash
# ${TUNAOS_MKSQUASHFS_SHIM_TAG}: installed by scripts/build-iso-tacklebox.sh
# for the length of one ISO build, then removed.
set -euo pipefail
args=()
comp=""
while ((\$#)); do
	case "\$1" in
	-comp)
		comp="\${2:-}"
		[[ "\$comp" == zstd ]] && comp=xz
		args+=(-comp "\$comp")
		shift 2 || shift
		;;
	-Xcompression-level)
		# zstd-only option; xz rejects it.
		shift 2 || shift
		;;
	*)
		args+=("\$1")
		shift
		;;
	esac
done
echo "tunaos: mksquashfs using -comp \${comp:-default} (kernel lacks SQUASHFS_ZSTD, tunaOS#2705)" >&2
exec "${real}" "\${args[@]}"
EOF
	chmod 0755 "$TUNAOS_MKSQUASHFS_SHIM"
	echo "==> ${TUNAOS_MKSQUASHFS_SHIM}: squashfs images will use xz (tunaOS#2705)" >&2
}

tunaos_remove_mksquashfs_xz_shim() {
	if [[ -f "$TUNAOS_MKSQUASHFS_SHIM" ]] &&
		grep -qF "$TUNAOS_MKSQUASHFS_SHIM_TAG" "$TUNAOS_MKSQUASHFS_SHIM"; then
		rm -f "$TUNAOS_MKSQUASHFS_SHIM"
	fi
}

# Prints the compressor named in the squashfs superblock at a byte offset of
# a file: magic "hsqs" at +0, little-endian u16 compression id at +20.
tunaos_squashfs_compressor_at() {
	local file="${1:?file required}" offset="${2:-0}" magic id
	magic="$(dd if="$file" bs=1 skip="$offset" count=4 status=none)"
	[[ "$magic" == hsqs ]] || {
		echo "not-squashfs"
		return 0
	}
	id="$(dd if="$file" bs=1 skip="$((offset + 20))" count=2 status=none | od -An -tu2 --endian=little | tr -d ' ')"
	case "$id" in
	1) echo gzip ;;
	2) echo lzma ;;
	3) echo lzo ;;
	4) echo xz ;;
	5) echo lz4 ;;
	6) echo zstd ;;
	*) echo "unknown-${id}" ;;
	esac
}

# Prints "<compressor> <path>" for every squashfs image under /LiveOS in an
# ISO, read in place: xorriso reports each file's start block (2048-byte
# ISO blocks) and only the superblock is read, so nothing is extracted.
tunaos_iso_squashfs_compressors() {
	local iso="${1:?iso required}" line lba path
	while IFS= read -r line; do
		[[ "$line" == "File data lba:"* ]] || continue
		lba="$(awk -F',' '{gsub(/[^0-9]/, "", $2); print $2}' <<<"$line")"
		path="$(sed -E "s/^.*, *'(.*)'$/\1/" <<<"$line")"
		case "$path" in
		*.sfs | *.squashfs | *.squashfs.img | *.img) ;;
		*) continue ;;
		esac
		[[ -n "$lba" ]] || continue
		printf '%s %s\n' "$(tunaos_squashfs_compressor_at "$iso" "$((lba * 2048))")" "$path"
	done < <(xorriso -indev "$iso" -find /LiveOS -type f -exec report_lba -- 2>/dev/null)
}

# Fails when any squashfs image in the ISO uses a compressor the image's
# kernel cannot mount.
tunaos_assert_iso_squashfs_mountable() {
	local iso="${1:?iso required}" found=0 bad=0 comp path
	while read -r comp path; do
		[[ "$comp" == not-squashfs ]] && continue
		found=1
		echo "    ${path}: ${comp}" >&2
		if [[ "$comp" == zstd ]]; then
			echo "::error::${path} is zstd squashfs, which this image's kernel cannot mount (tunaOS#2705); the mksquashfs wrapper was bypassed" >&2
			bad=1
		fi
	done < <(tunaos_iso_squashfs_compressors "$iso")
	if [[ "$found" -eq 0 ]]; then
		echo "::error::found no squashfs image under /LiveOS in ${iso}; cannot confirm the compressor (tunaOS#2705)" >&2
		return 1
	fi
	return "$bad"
}
