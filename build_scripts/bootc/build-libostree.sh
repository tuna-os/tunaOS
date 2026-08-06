#!/usr/bin/env bash
# build-libostree.sh — give this base a libostree the prebuilt bootc can load.
#
# WHY THIS EXISTS
#
# gurnard:pantheon built, made an ISO, booted the live system, partitioned and
# LUKS-formatted the disk, and then died in `bootc install to-filesystem`:
#
#   bootc: /lib/x86_64-linux-gnu/libostree-1.so.1: version `LIBOSTREE_2025.2'
#          not found (required by bootc)
#   bootc: /lib/x86_64-linux-gnu/libostree-1.so.1: version `LIBOSTREE_2025.3'
#          not found (required by bootc)
#   fisherman: fatal: bootc install: bootc install to-filesystem (via
#          container): exit status 1
#
# (LUKS run 31067479874.) bootc is not compiled per variant: it is pulled as a
# prebuilt tree from ghcr.io/tuna-os/bootc-toolchain-<base>, built by
# toolchain/Containerfile.debian and dynamically linked against the libostree of
# the base it was built on. Containerfile.ubuntu pulls the *sid* toolchain — and
# sid is built with BUILD_OSTREE=0, i.e. it ships no libostree, because sid's
# packaged one already satisfies bootc.
#
# That holds for exactly one of the two releases Containerfile.ubuntu serves:
#
#   resolute (26.04, grouper)  libostree 2025.x+  -> loads bootc fine
#   noble    (24.04, gurnard)  libostree 2024.5   -> missing LIBOSTREE_2025.*
#
# So the toolchain that works for grouper cannot work for gurnard, and nothing
# in the build noticed: the image builds, lints and boots. Only `bootc install`
# actually executes bootc, 40 minutes downstream inside a VM.
#
# WHAT THIS DOES
#
# The same thing the toolchain does for Debian trixie (BUILD_OSTREE=1): builds
# libostree — plus composefs, which ostree needs for the composefs-backed
# sysroot and which noble does not package — from the Renovate-pinned source in
# image-versions.yaml, against THIS base image, and stages it into the toolchain
# tree so the variant build installs it alongside bootc.
#
# Two things are deliberate:
#
#   * The decision is a behavioural probe, not a release name or a version
#     comparison: install the base's packaged libostree and ask the bootc we are
#     actually going to ship whether it can load. A version table would have to
#     be re-derived every time either pin moves, and a release-name case would
#     silently do the wrong thing on the next Ubuntu. Anything that is not a
#     libostree problem fails here instead of being papered over with a build.
#
#   * libdir is the base's multiarch directory, i.e. exactly where the archive's
#     libostree would live. Combined with the equivs dummy in the variant build
#     (see Containerfile.ubuntu), that leaves one libostree in the image and no
#     ld.so precedence question — a second copy under /usr/lib would lose to the
#     archive's if the dummy ever stopped holding, and lose silently.
set -euo pipefail

OUTPUT_DIR="${OUTPUT_DIR:-/output}"
BOOTC_BIN="${BOOTC_BIN:-${OUTPUT_DIR}/usr/bin/bootc}"
VERSIONS_FILE="${VERSIONS_FILE:-/run/context/image-versions.yaml}"
SRC_DIR="${SRC_DIR:-/tmp/libostree-src}"

log() { echo "build-libostree: $*"; }

pin() {
	local key="$1" value
	value="$(grep -E "^[[:space:]]*${key}:" "$VERSIONS_FILE" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
	[[ -n "$value" ]] || {
		echo "ERROR: no '${key}:' pin in ${VERSIONS_FILE}" >&2
		exit 1
	}
	echo "$value"
}

[[ -x "$BOOTC_BIN" ]] || {
	echo "ERROR: no bootc at ${BOOTC_BIN} — the toolchain pull must run first." >&2
	exit 1
}

export DEBIAN_FRONTEND=noninteractive

# ── Probe: can the bootc we are shipping load this base's libostree? ──────────
apt-get update -y
apt-get install -y --no-install-recommends libostree-1-1

probe_out=""
if probe_out="$("$BOOTC_BIN" --version 2>&1)"; then
	log "packaged libostree loads bootc (${probe_out}) — nothing to build"
	exit 0
fi

if ! grep -q 'libostree' <<<"$probe_out"; then
	# Not our problem to fix, and building ostree would not fix it. Say so here
	# rather than let it surface as an install failure inside a VM.
	echo "ERROR: the prebuilt bootc does not run on this base, and libostree is not why:" >&2
	echo "$probe_out" >&2
	exit 1
fi

log "packaged libostree cannot load bootc, building from source:"
log "  ${probe_out}"

OSTREE_VERSION="${OSTREE_VERSION:-$(pin ostree)}"
COMPOSEFS_VERSION="${COMPOSEFS_VERSION:-$(pin composefs)}"

# Build deps mirror toolchain/Containerfile.debian's BUILD_OSTREE=1 list.
# ostree configures --with-curl (no libsoup) and --with-composefs; composefs
# builds with meson and needs libfsverity/libfuse3.
apt-get install -y --no-install-recommends \
	ca-certificates curl git build-essential pkg-config \
	libcurl4-openssl-dev libzstd-dev libssl-dev libarchive-dev \
	meson ninja-build python3 libfsverity-dev libfuse3-dev liblzma-dev \
	e2fslibs-dev libext2fs-dev libgpgme-dev autoconf automake libtool \
	libseccomp-dev libcap-dev libglib2.0-dev bison flex gettext

# dpkg-architecture arrives with build-essential's dpkg-dev, so this can only be
# asked after the install above.
LIBDIR="${LIBDIR:-/usr/lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)}"

log "ostree ${OSTREE_VERSION}, composefs ${COMPOSEFS_VERSION} -> ${LIBDIR}"

# composefs first: ostree's configure finds it through pkg-config, not the git
# submodule, so it has to be installed into the builder before ostree runs.
git clone --branch "$COMPOSEFS_VERSION" --depth 1 \
	https://github.com/containers/composefs.git "${SRC_DIR}/composefs"
(
	cd "${SRC_DIR}/composefs"
	meson setup build --prefix=/usr --libdir="$LIBDIR" \
		-Ddefault_library=shared -Dman=disabled
	meson compile -C build
	meson install -C build
	DESTDIR="$OUTPUT_DIR" meson install -C build
)
ldconfig

git clone --branch "$OSTREE_VERSION" --depth 1 --recurse-submodules \
	https://github.com/ostreedev/ostree.git "${SRC_DIR}/ostree"
(
	cd "${SRC_DIR}/ostree"
	env NOCONFIGURE=1 ./autogen.sh
	./configure --prefix=/usr --libdir="$LIBDIR" --sysconfdir=/etc \
		--with-curl --without-soup --with-dracut --with-composefs \
		--disable-introspection --disable-gtk-doc --disable-man
	make -j"$(nproc)"
	# Into / so the assertion below runs against what we just built (it
	# replaces the packaged lib the probe installed), and into the toolchain
	# tree so the variant build gets it.
	make install
	make install DESTDIR="$OUTPUT_DIR"
)
ldconfig

# Assert, rather than trust, that this was the fix. LD_BIND_NOW resolves every
# symbol at load instead of on first call, so a partial ABI match fails here.
if ! probe_out="$(LD_BIND_NOW=1 "$BOOTC_BIN" --version 2>&1)"; then
	echo "ERROR: bootc still does not load after building libostree ${OSTREE_VERSION}:" >&2
	echo "$probe_out" >&2
	exit 1
fi
log "bootc loads the source libostree: ${probe_out}"
