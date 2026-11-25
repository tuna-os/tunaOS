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

bp="$(mktemp -d)"
git init -q "${bp}"
git -C "${bp}" fetch -q --depth 1 "${BP_REPO}" "${BP_REF}"
git -C "${bp}" checkout -q FETCH_HEAD
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
git init -q "${src}"
git -C "${src}" fetch -q --depth 1 "${GNOME_SETUP_UPSTREAM}" "${GNOME_SETUP_PIN}"
git -C "${src}" checkout -q FETCH_HEAD

# --libdir=lib keeps pages.conf at /usr/lib/gnome-setup on every base.
"${HERE}/../gnome-setup/apply-and-build" --source "${src}" --build-dir "${OUT}/meson-build" -- \
	--prefix=/usr --libdir=lib --buildtype=release \
	-Dlive-marker-path=/run/tunaos/live -Dpost-wizard-command=
install -d "${OUT}/gnome-setup"
meson install -C "${OUT}/meson-build" --destdir "${OUT}/gnome-setup"
echo "gnome-setup built into ${OUT}/gnome-setup"
