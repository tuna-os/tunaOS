#!/usr/bin/env bash
# Build gate (tunaOS#4859): the image has only the Flatpak remotes TunaOS
# configures.
#
# Fedora's flatpak package enabled flatpak-add-fedora-repos.service, which
# added the `fedora` and `fedora-testing` remotes on first boot of bonito
# ("Add Fedora flatpak repositories" on the serial console). The configured
# remotes are:
#
#   tuna-os   [flatpak_preinstall] remote_url in tunaos.toml, through
#             TUNAOS_FLATPAK_REMOTE_URL in build_scripts/lib/identity.env
#             (desktop/tuna-flatpak-remote.sh). None when it is empty.
#   flathub   https://dl.flathub.org/repo/ (26-packages-post.sh and
#             desktop/tuna-flatpak-remote.sh).
#
# The check fails the build when:
#
#   - flatpak-add-fedora-repos.service is enabled (masked, disabled and
#     not-found pass);
#   - another enabled unit runs `flatpak remote-add`, the same leak from a
#     different package or base;
#   - a .flatpakrepo in /etc/flatpak/remotes.d or /usr/share/flatpak/remotes.d
#     names a remote outside the configured set, or flathub at another URL;
#   - `flatpak remotes --system`, when flatpak is installed, lists a remote
#     outside the configured set.
#
# On success it writes the remotes the image has, one `name<TAB>url` per line
# and sorted, to /usr/share/tunaos/flatpak-remotes.expected. The boot-time
# branding check compares `flatpak remotes --system` to that file, which
# catches a remote that a unit adds at boot.
#
# TUNAOS_FLATPAK_CHECK_ROOT points the file checks at a fixture root, and
# TUNAOS_IDENTITY_ENV at a fixture identity adapter. With a fixture root,
# systemctl and flatpak are not run: the unit checks read unit files.
set -euo pipefail

root="${TUNAOS_FLATPAK_CHECK_ROOT:-}"
identity_env="${TUNAOS_IDENTITY_ENV:-$(dirname "${BASH_SOURCE[0]}")/../lib/identity.env}"
flathub_url="https://dl.flathub.org/repo/"
fail=0

failure() {
	echo "ERROR: verify-flatpak-remotes: $*" >&2
	fail=1
}

if [[ ! -r "${identity_env}" ]]; then
	echo "ERROR: verify-flatpak-remotes: ${identity_env} is missing; run scripts/config.py generate-identity" >&2
	echo "TUNAOS_FLATPAK_REMOTES_FAIL"
	exit 1
fi
tuna_remote_url="$(bash -c 'source "$1" && printf %s "${TUNAOS_FLATPAK_REMOTE_URL:-}"' _ "${identity_env}")"
allowed="flathub"
[[ -n "${tuna_remote_url}" ]] && allowed+=" tuna-os"

# 1. Units. A unit is enabled when a .wants/ or .requires/ link names it and
# /etc does not mask it (a link to /dev/null). In a real image systemctl
# answers; a fixture root has no systemd, so read the links.
unit_state() {
	local unit="$1" link
	if [[ -z "${root}" ]]; then
		systemctl is-enabled "${unit}" 2>/dev/null || true
		return
	fi
	link="${root}/etc/systemd/system/${unit}"
	if [[ -L "${link}" && "$(readlink "${link}")" == /dev/null ]]; then
		echo masked
	elif compgen -G "${root}/etc/systemd/system/*.wants/${unit}" >/dev/null ||
		compgen -G "${root}/usr/lib/systemd/system/*.wants/${unit}" >/dev/null; then
		echo enabled
	elif [[ -e "${root}/usr/lib/systemd/system/${unit}" || -e "${root}/etc/systemd/system/${unit}" ]]; then
		echo disabled
	else
		echo not-found
	fi
}

state="$(unit_state flatpak-add-fedora-repos.service)"
case "${state:-not-found}" in
masked | masked-runtime | disabled | not-found) ;;
*) failure "flatpak-add-fedora-repos.service is ${state}; it adds the fedora remotes at boot (mask it in 40-services.sh)" ;;
esac

while IFS= read -r unit_file; do
	unit="${unit_file##*/}"
	[[ "${unit}" == flatpak-add-fedora-repos.service ]] && continue
	case "$(unit_state "${unit}")" in
	enabled | enabled-runtime)
		failure "${unit} runs 'flatpak remote-add' and is enabled: $(grep -h 'remote-add' "${unit_file}" | head -1)"
		;;
	esac
done < <(grep -l -E '^ExecStart(Pre|Post)?=.*flatpak[[:space:]]+remote-add' \
	"${root}"/usr/lib/systemd/system/*.service "${root}"/etc/systemd/system/*.service 2>/dev/null || true)

# 2. remotes.d drop-ins.
declare -A remote_url=()
for file in "${root}"/etc/flatpak/remotes.d/*.flatpakrepo "${root}"/usr/share/flatpak/remotes.d/*.flatpakrepo; do
	[[ -e "${file}" ]] || continue
	name="$(basename "${file}" .flatpakrepo)"
	url="$(sed -n 's/^Url=//p' "${file}" | head -1)"
	if [[ " ${allowed} " != *" ${name} "* ]]; then
		failure "${file} adds remote '${name}' (${url}); tunaos.toml configures only: ${allowed}"
	elif [[ "${name}" == flathub && "${url}" != "${flathub_url}" ]]; then
		failure "${file} points flathub at ${url}, not ${flathub_url}"
	elif [[ -z "${url}" ]]; then
		failure "${file} has no Url="
	fi
	remote_url["${name}"]="${url}"
done

# 3. What flatpak itself reports, including remotes a package wrote into the
# system repository config. Disabled remotes count: they are one command away.
if [[ -z "${root}" ]] && command -v flatpak >/dev/null 2>&1; then
	while IFS=$'\t' read -r name url; do
		[[ -n "${name}" ]] || continue
		if [[ " ${allowed} " != *" ${name} "* ]]; then
			failure "flatpak remotes --system lists '${name}' (${url}); tunaos.toml configures only: ${allowed}"
		fi
		remote_url["${name}"]="${url}"
	done < <(flatpak remotes --system --show-disabled --columns=name,url 2>/dev/null || true)
fi

if ((fail)); then
	echo "TUNAOS_FLATPAK_REMOTES_FAIL"
	exit 1
fi

expected="${root}/usr/share/tunaos/flatpak-remotes.expected"
mkdir -p "$(dirname "${expected}")"
for name in "${!remote_url[@]}"; do
	printf '%s\t%s\n' "${name}" "${remote_url[${name}]}"
done | sort >"${expected}"
echo "TUNAOS_FLATPAK_REMOTES_OK fedora-unit=${state:-not-found} remotes=$(cut -f1 "${expected}" | paste -sd, -)"
