#!/usr/bin/env bash
# shellcheck disable=SC2154
# Shared installer for one native frontend on the medium (tunaOS#4905, ADR 0018).
#
# IDENTICAL COPY in each of installer-medium/frontends/{kde,cosmic,niri,xfce}/.
# tests/bats/test-installer-medium-frontends.bats fails when the copies drift.
# Each desktop's install.sh sets fe_desktop, fe_extra_env and fe_autostart, then
# calls fe_main. This file is sourced, never run.
#
# Contract (installer-medium/frontends/FRONTENDS-ASSUMPTIONS.md has the reading):
#   install.sh ROOT [--dry-run]
# ROOT is the mounted medium root. --dry-run prints the plan and changes
# nothing: no network, no flatpak, no writes.

fe_say() { printf 'frontend[%s]: %s\n' "${fe_desktop}" "$*"; }
fe_die() {
	printf 'frontend[%s]: error: %s\n' "${fe_desktop:-?}" "$*" >&2
	exit 1
}

# The three sockets fishermand serves for the frontends (docs/FISHERMAND.md in
# tuna-os/fisherman). The sandbox gets each path by name, not through
# --filesystem=host, which does not cover /run.
fe_sockets=(
	/run/systemd/io.systemd.SysInstall
	/run/systemd/io.systemd.CryptEnroll
	/run/systemd/io.systemd.Shutdown
	/run/fisherman/io.tunaos.Fisherman
)

# The frontends are live-only: the entry runs only on a tunaos.live boot, the
# same idiom the live/ drop-ins use (ConditionKernelCommandLine=tunaos.live).
fe_live_guard='grep -qw tunaos.live /proc/cmdline'

# --- pin file ---------------------------------------------------------------

# fe_pin_get FILE KEY: the value of KEY=VALUE, or empty.
fe_pin_get() {
	sed -n "s/^${2}=//p" "$1" | head -n 1
}

# fe_pin_check FILE: fail on anything that is not an immutable pin. A tag, a
# branch name or "latest" can move under a build; a digest or commit cannot.
fe_pin_check() {
	local pin="$1" bad=0 key value arch line
	[[ -f ${pin} ]] || fe_die "no pin file ${pin}"
	while IFS= read -r line; do
		[[ -z ${line} || ${line} == \#* ]] && continue
		if [[ ! ${line} =~ ^[A-Z][A-Za-z0-9_]*=[^[:space:]\"\'\$\`]*$ ]]; then
			echo "pin: ${pin}: not a plain KEY=VALUE line: ${line}" >&2
			bad=1
		fi
	done <"${pin}"
	value="$(fe_pin_get "${pin}" APP_ID)"
	[[ ${value} =~ ^org\.tunaos\.Installer[A-Za-z]+$ ]] || {
		echo "pin: APP_ID is not an org.tunaos.Installer* id: '${value}'" >&2
		bad=1
	}
	# A registry repository with no tag and no digest: the digest is its own key.
	value="$(fe_pin_get "${pin}" OCI_REPO)"
	[[ ${value} =~ ^[a-z0-9.-]+/[a-z0-9._/-]+$ ]] || {
		echo "pin: OCI_REPO must be a bare repository (no :tag, no @digest): '${value}'" >&2
		bad=1
	}
	for arch in x86_64 aarch64; do
		key="OCI_DIGEST_${arch}"
		value="$(fe_pin_get "${pin}" "${key}")"
		[[ ${value} =~ ^sha256:[0-9a-f]{64}$ ]] || {
			echo "pin: ${key} is not sha256:<64 hex> (a tag floats): '${value}'" >&2
			bad=1
		}
		key="RUNTIME_COMMIT_${arch}"
		value="$(fe_pin_get "${pin}" "${key}")"
		[[ ${value} =~ ^[0-9a-f]{64}$ ]] || {
			echo "pin: ${key} is not a 64 hex ostree commit: '${value}'" >&2
			bad=1
		}
	done
	value="$(fe_pin_get "${pin}" SOURCE_COMMIT)"
	[[ ${value} =~ ^[0-9a-f]{40}$ ]] || {
		echo "pin: SOURCE_COMMIT is not a 40 hex git commit: '${value}'" >&2
		bad=1
	}
	value="$(fe_pin_get "${pin}" RUNTIME_REF)"
	[[ ${value} =~ ^[A-Za-z0-9._]+//[0-9][0-9A-Za-z._-]*$ ]] || {
		echo "pin: RUNTIME_REF needs a numbered branch (NAME//6.11), not master or latest: '${value}'" >&2
		bad=1
	}
	value="$(fe_pin_get "${pin}" GL_REF)"
	if [[ -n ${value} ]]; then
		[[ ${value} =~ ^org\.freedesktop\.Platform\.GL\.default//[0-9][0-9A-Za-z._-]*$ ]] || {
			echo "pin: GL_REF needs a numbered branch of org.freedesktop.Platform.GL.default: '${value}'" >&2
			bad=1
		}
		for arch in x86_64 aarch64; do
			value="$(fe_pin_get "${pin}" "GL_COMMIT_${arch}")"
			[[ ${value} =~ ^[0-9a-f]{64}$ ]] || {
				echo "pin: GL_COMMIT_${arch} is not a 64 hex ostree commit: '${value}'" >&2
				bad=1
			}
		done
	fi
	value="$(fe_pin_get "${pin}" DAEMON_CLIENT_IN_DIGEST)"
	[[ ${value} == yes || ${value} == no ]] || {
		echo "pin: DAEMON_CLIENT_IN_DIGEST must be yes or no: '${value}'" >&2
		bad=1
	}
	return "${bad}"
}

# --- where things go on the medium -------------------------------------------

# fe_one_of NAME GLOB...: the single existing directory among the globs.
fe_one_of() {
	local -a hits=()
	local g d
	for g in "$@"; do
		for d in ${g}; do
			[[ -d ${d} ]] && hits+=("${d}")
		done
	done
	if ((${#hits[@]} > 1)); then
		fe_die "more than one candidate: ${hits[*]} (set TUNA_FRONTEND_VAR, TUNA_FRONTEND_ETC, TUNA_FRONTEND_USR)"
	fi
	((${#hits[@]} == 1)) && printf '%s\n' "${hits[0]}"
	return 0
}

# fe_resolve ROOT: set fe_var, fe_etc, fe_usr (fe_usr may be empty).
# bootc install to-disk leaves the deployment below ROOT, so ROOT/etc is not the
# booted /etc. Three layouts are tried; a plain tree (a deployment root, a
# fixture) is the fallback.
fe_resolve() {
	local root="$1"
	fe_var="${TUNA_FRONTEND_VAR:-}"
	fe_etc="${TUNA_FRONTEND_ETC:-}"
	fe_usr="${TUNA_FRONTEND_USR:-}"
	if [[ -z ${fe_etc} ]]; then
		fe_etc="$(fe_one_of "${root}"/ostree/deploy/*/deploy/*/etc "${root}"/state/deploy/*/etc)"
		fe_etc="${fe_etc:-${root}/etc}"
	fi
	if [[ -z ${fe_var} ]]; then
		fe_var="$(fe_one_of "${root}"/ostree/deploy/*/var "${root}"/state/deploy/*/var)"
		fe_var="${fe_var:-${root}/var}"
	fi
	if [[ -z ${fe_usr} ]]; then
		fe_usr="$(fe_one_of "${root}"/ostree/deploy/*/deploy/*/usr)"
		[[ -n ${fe_usr} ]] || { [[ -d "${root}/usr" ]] && fe_usr="${root}/usr"; }
	fi
	return 0
}

# --- the steps --------------------------------------------------------------

# fe_override_text: the flatpak override keyfile, byte for byte. Written
# directly (no flatpak binary, no root) so a test can assert it.
fe_override_text() {
	local s env
	printf '[Context]\nfilesystems='
	for s in "${fe_sockets[@]}"; do printf '%s;' "${s}"; done
	printf '\n\n[Environment]\n'
	for env in TUNA_INSTALLER_BACKEND=daemon "${fe_extra_env[@]}"; do
		printf '%s\n' "${env}"
	done
}

fe_receipt_text() {
	printf 'app_id=%s\noci=%s@%s\nsource_commit=%s\ndaemon_client_in_digest=%s\nbackend=daemon\n' \
		"${fe_app}" "${fe_repo}" "${fe_digest}" "${fe_source}" "${fe_has_client}"
}

fe_plan() {
	local s
	fe_say "plan for ${fe_app} (${fe_arch}) into ${fe_root}"
	fe_say "  var=${fe_var} etc=${fe_etc} usr=${fe_usr:-<none>}"
	fe_say "  fetch    skopeo copy docker://${fe_repo}@${fe_digest} -> oci dir"
	fe_say "  import   flatpak build-import-bundle --oci -> local repo, verify digest ${fe_digest}"
	fe_say "  install  flatpak install --system --no-deps ${fe_app} into ${fe_var}/lib/flatpak"
	fe_say "  runtime  flatpak install --commit=${fe_rt_commit} ${fe_rt_ref} into the same store"
	[[ -z ${fe_gl_ref} ]] || fe_say "  runtime  flatpak install --commit=${fe_gl_commit} ${fe_gl_ref} (Mesa)"
	for s in "${fe_sockets[@]}"; do fe_say "  sandbox  filesystems += ${s}"; done
	fe_say "  env      TUNA_INSTALLER_BACKEND=daemon ${fe_extra_env[*]}"
	fe_say "  write    ${fe_var}/lib/flatpak/overrides/${fe_app}"
	fe_say "  write    ${fe_etc}/tuna-installer/frontend-receipt (not the readiness stamp)"
	fe_say "  autostart (live only: ${fe_live_guard})"
	fe_autostart plan
	if [[ ${fe_has_client} != yes ]]; then
		fe_say "  WARNING: the pinned digest predates the daemon client (SOURCE_COMMIT ${fe_source});"
		fe_say "           the backend switch is a no-op until the pin moves to a build that has it"
	fi
	fe_say "  EULA: none shipped (/usr/share/tuna-installer/eula.xml is a shared path)"
	fe_say "  readiness stamp: the frontend writes it at runtime; nothing is baked"
}

# fe_write PATH: stdin to PATH, or print the plan line in dry-run mode.
fe_write() {
	local path="$1"
	if ((fe_dry)); then
		fe_say "  (dry run) would write ${path}"
		cat >/dev/null
		return 0
	fi
	mkdir -p "$(dirname "${path}")"
	cat >"${path}"
}

# fe_write_xdg_autostart [EXTRA_KEY=VALUE...]: the freedesktop autostart entry.
# No OnlyShowIn=: systemd-xdg-autostart-generator evaluates it against
# $XDG_CURRENT_DESKTOP, which cosmic-session never exports, so the entry would
# be generated and skipped (live-iso/common/src/desktop-cosmic.sh has the run).
fe_write_xdg_autostart() {
	local path="${fe_etc}/xdg/autostart/org.tunaos.installer-live.desktop"
	{
		printf '[Desktop Entry]\nType=Application\n'
		printf 'Name=Install %s\n' "${TUNAOS_PROJECT_NAME:-TunaOS}"
		printf 'Exec=sh -c "%s && exec flatpak run %s"\n' "${fe_live_guard}" "${fe_app}"
		printf 'Icon=%s\n' "${fe_app}"
		if (($#)); then printf '%s\n' "$@"; fi
	} | fe_write "${path}"
}

fe_import() {
	local work="$1" ref="app/${fe_app}/${fe_arch}/master" oci have
	if [[ -n ${TUNA_FRONTEND_OCI_DIR:-} ]]; then
		oci="${TUNA_FRONTEND_OCI_DIR}"
	else
		oci="${work}/oci"
		# The digest reference is the pin: the registry cannot return other bytes.
		skopeo copy --quiet "docker://${fe_repo}@${fe_digest}" "oci:${oci}:${ref}"
	fi
	have="$(sed -n 's/.*"digest":"\(sha256:[0-9a-f]*\)".*/\1/p' "${oci}/index.json" | head -n 1)"
	[[ ${have} == "${fe_digest}" ]] ||
		fe_die "OCI layout holds ${have:-nothing}, the pin says ${fe_digest}"
	ostree init --repo="${work}/repo" --mode=archive-z2
	# The imported ostree commit is new (not the image's org.flatpak.commit
	# label), so the OCI digest above is the identity that is verified.
	flatpak build-import-bundle --oci "${work}/repo" "${oci}"
}

fe_install_flatpak() {
	local work="$1" store="${fe_var}/lib/flatpak"
	mkdir -p "${store}"
	# As root, flatpak writes the system installation directly; the variable
	# points it at the medium's /var instead of the build host's.
	export FLATPAK_SYSTEM_DIR="${store}"
	export FLATPAK_USER_DIR="${store}"
	local scope="${TUNA_FRONTEND_FLATPAK_SCOPE:---system}"
	flatpak remote-add "${scope}" --if-not-exists --no-gpg-verify tuna-frontend-local "file://${work}/repo"
	flatpak remote-add "${scope}" --if-not-exists flathub \
		"${TUNA_FRONTEND_FLATHUB_URL:-https://dl.flathub.org/repo/flathub.flatpakrepo}"
	flatpak install "${scope}" --noninteractive --no-deps --no-related \
		--arch="${fe_arch}" tuna-frontend-local "${fe_app}"
	# `flatpak install` has no --commit option (a real build stopped here with
	# "Unknown option --commit"). Install the runtime, then move it to the
	# pinned commit; `flatpak update --commit` is the documented way.
	flatpak install "${scope}" --noninteractive --no-related --arch="${fe_arch}" \
		flathub "${fe_rt_ref}"
	flatpak update "${scope}" --noninteractive --no-related --arch="${fe_arch}" \
		--commit="${fe_rt_commit}" "${fe_rt_ref}"
	# Mesa is an extension of the runtime, and --no-related leaves it out. A
	# Qt Quick or wgpu frontend then has no GL at all: on the first real boot
	# tuna-installer-kde aborted (status 134) before its first frame (bonito:kde
	# run 45610703034; `flatpak list` had the app and the runtime only).
	if [[ -n ${fe_gl_ref} ]]; then
		flatpak install "${scope}" --noninteractive --no-related --arch="${fe_arch}" \
			flathub "${fe_gl_ref}"
		flatpak update "${scope}" --noninteractive --no-related --arch="${fe_arch}" \
			--commit="${fe_gl_commit}" "${fe_gl_ref}"
	fi
	# The remote names a directory of this build: a medium that keeps it copies
	# it to each installed system, and the branding contract fails on it
	# ("system remotes [... tuna-frontend-local file:///tmp/...]", run
	# 45618116397). --force: the app stays installed.
	flatpak remote-delete "${scope}" --force tuna-frontend-local
}

fe_main() {
	local pin_file here
	here="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
	fe_root="" fe_dry=0
	while (($#)); do
		case "$1" in
		--dry-run) fe_dry=1 ;;
		--check-pin)
			fe_pin_check "${here}/pin.env"
			exit $?
			;;
		-h | --help)
			echo "usage: install.sh ROOT [--dry-run] | --check-pin"
			exit 0
			;;
		-*) fe_die "unknown option $1" ;;
		*)
			[[ -z ${fe_root} ]] || fe_die "one ROOT only"
			fe_root="$1"
			;;
		esac
		shift
	done
	[[ -n ${fe_root} ]] || fe_die "usage: install.sh ROOT [--dry-run]"
	pin_file="${here}/pin.env"
	fe_pin_check "${pin_file}" || fe_die "refusing a floating or malformed pin"
	fe_arch="${TUNA_FRONTEND_ARCH:-$(uname -m)}"
	case "${fe_arch}" in
	x86_64 | aarch64) ;;
	*) fe_die "no pinned artifact for ${fe_arch}" ;;
	esac
	fe_app="$(fe_pin_get "${pin_file}" APP_ID)"
	fe_repo="$(fe_pin_get "${pin_file}" OCI_REPO)"
	fe_digest="$(fe_pin_get "${pin_file}" "OCI_DIGEST_${fe_arch}")"
	fe_source="$(fe_pin_get "${pin_file}" SOURCE_COMMIT)"
	fe_has_client="$(fe_pin_get "${pin_file}" DAEMON_CLIENT_IN_DIGEST)"
	fe_rt_ref="$(fe_pin_get "${pin_file}" RUNTIME_REF)"
	fe_rt_commit="$(fe_pin_get "${pin_file}" "RUNTIME_COMMIT_${fe_arch}")"
	fe_gl_ref="$(fe_pin_get "${pin_file}" GL_REF)"
	fe_gl_commit="$(fe_pin_get "${pin_file}" "GL_COMMIT_${fe_arch}")"
	((fe_dry)) || [[ -d ${fe_root} ]] || fe_die "ROOT is not a directory: ${fe_root}"
	fe_resolve "${fe_root}"
	fe_plan
	if ((fe_dry)); then
		fe_say "dry run: nothing fetched, installed or written"
		return 0
	fi
	local work
	work="$(mktemp -d)"
	# shellcheck disable=SC2064
	trap "rm -rf '${work}'" EXIT
	fe_import "${work}"
	fe_install_flatpak "${work}"
	fe_override_text | fe_write "${fe_var}/lib/flatpak/overrides/${fe_app}"
	fe_receipt_text | fe_write "${fe_etc}/tuna-installer/frontend-receipt"
	fe_autostart write
	fe_say "installed ${fe_app}"
}
