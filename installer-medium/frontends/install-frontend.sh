#!/usr/bin/env bash
# Dispatch the live-session installer frontend for one desktop (tunaOS#4905).
#
# Usage: installer-medium/frontends/install-frontend.sh DESKTOP ROOT [--dry-run]
#
# DESKTOP is one of gnome, tuna, kde, cosmic, niri, xfce, pantheon. ROOT is a
# staging tree (never /): Containerfile.live copies it over the live image.
# The script installs the shared launcher, then runs
# frontends/DESKTOP/install.sh ROOT and checks that the result meets the
# contract in frontends/README.md. An unknown desktop fails; there is no
# default. With --dry-run it prints the plan, touches nothing, and only warns
# about a missing per-desktop script.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP="${1:?usage: install-frontend.sh DESKTOP ROOT [--dry-run]}"
ROOT="${2:?usage: install-frontend.sh DESKTOP ROOT [--dry-run]}"
DRY_RUN="${3:-}"
FRONTENDS="${MEDIUM_FRONTENDS_DIR:-${HERE}}"

case "${DESKTOP}" in
gnome | tuna | kde | cosmic | niri | xfce | pantheon) ;;
*)
	echo "install-frontend: unknown desktop '${DESKTOP}' (gnome tuna kde cosmic niri xfce pantheon)" >&2
	exit 1
	;;
esac
[[ "${ROOT}" == /* && "${ROOT}" != / ]] || {
	echo "install-frontend: ROOT must be an absolute staging path other than /, got '${ROOT}'" >&2
	exit 1
}

script="${FRONTENDS}/${DESKTOP}/install.sh"
echo "install-frontend: ${DESKTOP} -> ${ROOT} (${script})"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	[[ -x "${script}" ]] || echo "install-frontend: WARNING ${script} is missing (dry run continues)" >&2
	echo "install -m 0755 medium-live-installer ${ROOT}/usr/libexec/medium-live-installer"
	echo "MEDIUM_FRONTENDS=${FRONTENDS} ${script} ${ROOT}"
	exit 0
fi
[[ -x "${script}" ]] || {
	echo "install-frontend: ${script} is missing or not executable" >&2
	exit 1
}
[[ -d "${ROOT}" ]] || {
	echo "install-frontend: ROOT ${ROOT} is not a directory" >&2
	exit 1
}

install -D -m 0755 "${HERE}/medium-live-installer" "${ROOT}/usr/libexec/medium-live-installer"
install -d "${ROOT}/usr/lib/medium-live" "${ROOT}/usr/share/medium-live/payload.d"
printf '%s\n' "${DESKTOP}" >"${ROOT}/usr/lib/medium-live/desktop"
MEDIUM_FRONTENDS="${FRONTENDS}" "${script}" "${ROOT}"

# Contract checks: a frontend that installs but never autostarts shows no
# installer, and nothing else would say so until a person looked at the screen.
autostart="${ROOT}/etc/xdg/autostart/org.tunaos.installer-live.desktop"
fail() {
	echo "install-frontend: ${DESKTOP}: contract violation: $*" >&2
	exit 1
}
[[ -f "${autostart}" ]] || fail "no autostart entry at /etc/xdg/autostart/org.tunaos.installer-live.desktop"
grep -q '^Exec=/usr/libexec/medium-live-installer ' "${autostart}" || fail "autostart Exec does not use /usr/libexec/medium-live-installer"
[[ -s "${ROOT}/usr/share/medium-live/payload.d/${DESKTOP}.list" ]] || fail "empty or missing payload list"
stamp="${ROOT}/usr/share/medium-live/stamp.d/${DESKTOP}"
[[ -f "${stamp}" ]] || fail "no readiness stamp declaration (fe_stamp native|launcher)"
case "$(<"${stamp}")" in
native) ;;
launcher) grep -q -- '--stamp ' "${autostart}" || fail "stamp is 'launcher' but the autostart Exec has no --stamp" ;;
*) fail "stamp declaration must be native or launcher" ;;
esac
# The launcher itself is part of the payload.
printf '%s\n' /usr/libexec/medium-live-installer /usr/lib/medium-live/desktop >>"${ROOT}/usr/share/medium-live/payload.d/${DESKTOP}.list"
sort -u -o "${ROOT}/usr/share/medium-live/payload.d/${DESKTOP}.list" "${ROOT}/usr/share/medium-live/payload.d/${DESKTOP}.list"
echo "install-frontend: ${DESKTOP} ready ($(wc -l <"${ROOT}/usr/share/medium-live/payload.d/${DESKTOP}.list") payload paths)"
