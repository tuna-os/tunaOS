#!/usr/bin/env bash
# Build gnome-setup from the pinned upstream commit plus the patch series
# (frontends/gnome-setup/apply-and-build) into OUTDIR/gnome-setup, a destdir
# tree. Runs in the throwaway payload stage of Containerfile.live on a Fedora
# builder: the GTK -devel packages are missing on several cell bases.
#
# Usage: frontends/gnome/build.sh OUTDIR
#
# Evidence for the recipe: Utah's medium builds the same way
# (utah iso/raw/Containerfile, stage gnome-setup). The patch series uses
# translated strings in blueprint closures, which needs blueprint-compiler
# 0.20 or newer; Fedora 43 ships 0.18, so build v0.22.2 from its tag commit
# (git ls-remote of refs/tags/v0.22.2^{} gives this hash, 2026-11-25).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:?usage: build.sh OUTDIR}"
BP_REPO=https://gitlab.gnome.org/GNOME/blueprint-compiler.git
BP_REF=ed35ac74de0c1bb1f5e852410b97edd1f08904c9

dnf -y install --setopt=install_weak_deps=False \
	git cargo rust meson ninja-build gcc gettext gettext-devel desktop-file-utils python3-gobject \
	glib2-devel gtk4-devel libadwaita-devel gnome-desktop4-devel appstream-devel

# fetch_commit DIR COMMIT REPO...: one commit into a new repository, from the
# first REPO that has it. The commit hash is the identity, so a mirror gives
# the same bytes. gitlab.gnome.org was down for hours (503, runs 45665062075
# and 45678211992).
fetch_commit() {
	local dir="$1" commit="$2" try repo
	shift 2
	git init -q "${dir}"
	for try in 1 2 3; do
		for repo in "$@"; do
			if git -C "${dir}" fetch -q --depth 1 "${repo}" "${commit}"; then
				git -C "${dir}" checkout -q FETCH_HEAD
				[[ "$(git -C "${dir}" rev-parse HEAD)" = "${commit}" ]]
				return
			fi
		done
		sleep $((try * 20))
	done
	return 1
}
bp="$(mktemp -d)"
fetch_commit "${bp}" "${BP_REF}" "${BP_REPO}" https://github.com/GNOME/blueprint-compiler.git
[[ "$(git -C "${bp}" rev-parse HEAD)" = "${BP_REF}" ]]
meson setup "${bp}/build" "${bp}" --prefix=/usr
meson install -C "${bp}/build"

# The source tree must outlive apply-and-build: `meson install` regenerates
# the build files from it. Without --source the script clones into a
# temporary directory and removes it on exit; the first real build then
# stopped in `meson install` with "Neither source directory
# '/tmp/tmp.fHEQ9nnGWB/src' nor build directory '.' contain a build file
# meson.build" (bihar, 2026-11-25). The fetch names the pinned commit, so a
# new upstream commit cannot stop the build either.
# shellcheck disable=SC1091
source "${HERE}/../gnome-setup/PIN"
src="${OUT}/gnome-setup-src"
fetch_commit "${src}" "${GNOME_SETUP_PIN}" "${GNOME_SETUP_UPSTREAM}" https://github.com/hanthor/gnome-setup.git

# GNOME_SETUP_COMPAT names a compat set from ../gnome-setup/compat for one
# cell (build-live-image.sh reads compat/for-cell; Containerfile.live passes
# it). Empty for every other cell, which builds the plain series.
compat=()
[[ -z "${GNOME_SETUP_COMPAT:-}" ]] || compat=(--compat "${GNOME_SETUP_COMPAT}")
# --libdir=lib keeps pages.conf at /usr/lib/gnome-setup on every base.
"${HERE}/../gnome-setup/apply-and-build" --source "${src}" --build-dir "${OUT}/meson-build" "${compat[@]}" -- \
	--prefix=/usr --libdir=lib --buildtype=release \
	-Dlive-marker-path=/run/tunaos/live -Dpost-wizard-command=
install -d "${OUT}/gnome-setup"
meson install -C "${OUT}/meson-build" --destdir "${OUT}/gnome-setup"
if [[ -n "${GNOME_SETUP_COMPAT:-}" ]]; then
	"${HERE}/../gnome-setup/compat/check-ui" "${OUT}/gnome-setup"
	# Containerfile.live checks this marker against the GTK of the image.
	install -D -m 0644 /dev/stdin "${OUT}/gnome-setup/usr/share/medium-live/gnome-setup-compat" <<<"${GNOME_SETUP_COMPAT}"
fi
echo "gnome-setup built into ${OUT}/gnome-setup${GNOME_SETUP_COMPAT:+ (compat ${GNOME_SETUP_COMPAT})}"
