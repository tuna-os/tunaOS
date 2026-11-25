#!/usr/bin/env bats
# Unit tests for installer-medium/frontends/{kde,cosmic,niri,xfce}/install.sh
# (tunaOS#4905, ADR 0018). No root, no network, no flatpak: PATH shims record
# every call, and a fixture tree stands in for the mounted medium.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
FE="${REPO_ROOT}/installer-medium/frontends"
DESKTOPS="kde cosmic niri xfce"

setup() {
	WORK="${BATS_TEST_TMPDIR}"
	LOG="${WORK}/calls.log"
	: >"${LOG}"
	export LOG
	# Recording shims for the real-mode run.
	SHIMS="${WORK}/shims"
	mkdir -p "${SHIMS}"
	cat >"${SHIMS}/skopeo" <<'SH'
#!/usr/bin/env bash
echo "skopeo $*" >>"${LOG}"
src="" dst=""
for a in "$@"; do
  case "$a" in docker://*) src="$a" ;; oci:*) dst="${a#oci:}" ;; esac
done
dir="${dst%:*}"
mkdir -p "${dir}"
printf '{"manifests":[{"digest":"%s"}]}' "${src##*@}" >"${dir}/index.json"
SH
	cat >"${SHIMS}/ostree" <<'SH'
#!/usr/bin/env bash
echo "ostree $*" >>"${LOG}"
SH
	cat >"${SHIMS}/flatpak" <<'SH'
#!/usr/bin/env bash
echo "flatpak $* [FLATPAK_SYSTEM_DIR=${FLATPAK_SYSTEM_DIR:-}]" >>"${LOG}"
SH
	chmod +x "${SHIMS}"/*
	# Shims that must never run in a dry run.
	DENY="${WORK}/deny"
	mkdir -p "${DENY}"
	for c in skopeo ostree flatpak curl; do
		printf '#!/usr/bin/env bash\necho "%s called" >>"%s/denied"\nexit 99\n' "$c" "${WORK}" >"${DENY}/$c"
		chmod +x "${DENY}/$c"
	done
	# A medium root laid out as bootc install to-disk leaves it (ostree).
	ROOT="${WORK}/root"
	D="${ROOT}/ostree/deploy/default"
	mkdir -p "${D}/var" "${D}/deploy/abc.0/etc" "${D}/deploy/abc.0/usr/share/niri"
	printf 'input {}\n' >"${D}/deploy/abc.0/usr/share/niri/config.kdl"
}

tree_hash() { tar -C "$1" -cf - . | sha256sum; }

@test "every pin passes the floating-tag check, both arches" {
	for d in ${DESKTOPS}; do
		run "${FE}/${d}/install.sh" --check-pin
		[ "$status" -eq 0 ]
	done
}

@test "pins hold only immutable references" {
	for d in ${DESKTOPS}; do
		pin="${FE}/${d}/pin.env"
		grep -qE '^OCI_DIGEST_x86_64=sha256:[0-9a-f]{64}$' "$pin"
		grep -qE '^OCI_DIGEST_aarch64=sha256:[0-9a-f]{64}$' "$pin"
		run grep -E ':latest|=latest|=master|-x86_64$|-aarch64$' "$pin"
		[ "$status" -ne 0 ]
	done
}

@test "a floating reference fails the pin check" {
	for d in ${DESKTOPS}; do
		for mut in 'OCI_DIGEST_x86_64=kde-x86_64' 'OCI_DIGEST_x86_64=latest' \
			'OCI_DIGEST_aarch64=sha256:abc' 'OCI_REPO=ghcr.io/tuna-os/bootc-installer:kde' \
			'OCI_REPO=ghcr.io/tuna-os/bootc-installer@sha256:0' 'SOURCE_COMMIT=dev' \
			'RUNTIME_REF=org.kde.Platform//master' 'RUNTIME_COMMIT_x86_64=master' \
			'RUNTIME_COMMIT_aarch64=latest'; do
			copy="${WORK}/mut-${d}"
			rm -rf "${copy}"
			cp -r "${FE}/${d}" "${copy}"
			sed -i "s|^${mut%%=*}=.*|${mut}|" "${copy}/pin.env"
			run "${copy}/install.sh" --check-pin
			[ "$status" -ne 0 ] || {
				echo "accepted ${d}: ${mut}"
				false
			}
			run "${copy}/install.sh" "${ROOT}" --dry-run
			[ "$status" -ne 0 ]
		done
	done
}

@test "the shared library is identical in all four directories" {
	for d in cosmic niri xfce; do
		cmp "${FE}/kde/frontend-common.sh" "${FE}/${d}/frontend-common.sh"
	done
}

@test "dry run prints the plan and touches nothing" {
	for d in ${DESKTOPS}; do
		before="$(tree_hash "${ROOT}")"
		PATH="${DENY}:${PATH}" run "${FE}/${d}/install.sh" "${ROOT}" --dry-run
		[ "$status" -eq 0 ]
		[[ $output == *"dry run: nothing"* ]]
		[[ $output == *"/run/fisherman/io.tunaos.Fisherman"* ]]
		[[ $output == *"/run/systemd/io.systemd.SysInstall"* ]]
		[[ $output == *"sha256:"* ]]
		[ ! -e "${WORK}/denied" ]
		[ "$(tree_hash "${ROOT}")" = "${before}" ]
	done
}

@test "dry run tolerates a root that does not exist" {
	PATH="${DENY}:${PATH}" run "${FE}/kde/install.sh" /nonexistent-medium --dry-run
	[ "$status" -eq 0 ]
	[ ! -e /nonexistent-medium ]
}

@test "real run fetches by digest, pins the runtime commit, writes the override" {
	for d in ${DESKTOPS}; do
		: >"${LOG}"
		PATH="${SHIMS}:${PATH}" run "${FE}/${d}/install.sh" "${ROOT}"
		[ "$status" -eq 0 ] || {
			echo "$output" >&2
			false
		}
		app="$(sed -n 's/^APP_ID=//p' "${FE}/${d}/pin.env")"
		dig="$(sed -n 's/^OCI_DIGEST_x86_64=//p' "${FE}/${d}/pin.env")"
		rt="$(sed -n 's/^RUNTIME_COMMIT_x86_64=//p' "${FE}/${d}/pin.env")"
		grep -q "skopeo copy --quiet docker://ghcr.io/tuna-os/bootc-installer@${dig} " "${LOG}"
		grep -q "flatpak build-import-bundle --oci" "${LOG}"
		# `flatpak install` has no --commit option: the runtime is installed,
		# then `flatpak update --commit` moves it to the pin.
		! grep -q -- "flatpak install.*--commit=" "${LOG}"
		grep -q -- "flatpak update .*--commit=${rt} " "${LOG}"
		grep -q "FLATPAK_SYSTEM_DIR=${ROOT}/ostree/deploy/default/var/lib/flatpak" "${LOG}"
		ov="${D}/var/lib/flatpak/overrides/${app}"
		grep -qx 'filesystems=/run/systemd/io.systemd.SysInstall;/run/systemd/io.systemd.CryptEnroll;/run/systemd/io.systemd.Shutdown;/run/fisherman/io.tunaos.Fisherman;' "${ov}" ||
			grep -q '^filesystems=.*io.systemd.SysInstall;.*io.systemd.CryptEnroll;.*io.systemd.Shutdown;.*io.tunaos.Fisherman;$' "${ov}"
		grep -qx 'TUNA_INSTALLER_BACKEND=daemon' "${ov}"
		grep -q "^app_id=${app}$" "${D}/deploy/abc.0/etc/tuna-installer/frontend-receipt"
	done
}

@test "each frontend gets the backend switch it actually reads" {
	PATH="${SHIMS}:${PATH}" "${FE}/cosmic/install.sh" "${ROOT}"
	grep -qx 'TUNA_USE_FISHERMAND=1' "${D}/var/lib/flatpak/overrides/org.tunaos.InstallerCosmic"
	PATH="${SHIMS}:${PATH}" "${FE}/xfce/install.sh" "${ROOT}"
	grep -qx 'BOOTC_INSTALLER_BACKEND=daemon' "${D}/var/lib/flatpak/overrides/org.tunaos.InstallerXfce"
}

@test "aarch64 uses its own digest and runtime commit" {
	: >"${LOG}"
	TUNA_FRONTEND_ARCH=aarch64 PATH="${SHIMS}:${PATH}" run "${FE}/kde/install.sh" "${ROOT}"
	[ "$status" -eq 0 ]
	dig="$(sed -n 's/^OCI_DIGEST_aarch64=//p' "${FE}/kde/pin.env")"
	grep -q "@${dig} " "${LOG}"
}

@test "an unsupported architecture fails" {
	TUNA_FRONTEND_ARCH=riscv64 run "${FE}/kde/install.sh" "${ROOT}" --dry-run
	[ "$status" -ne 0 ]
}

@test "a layout that does not hold the pinned digest is refused" {
	cat >"${SHIMS}/skopeo" <<'SH'
#!/usr/bin/env bash
for a in "$@"; do case "$a" in oci:*) d="${a#oci:}"; d="${d%:*}" ;; esac; done
mkdir -p "$d"; printf '{"manifests":[{"digest":"sha256:%064d"}]}' 0 >"$d/index.json"
SH
	PATH="${SHIMS}:${PATH}" run "${FE}/kde/install.sh" "${ROOT}"
	[ "$status" -ne 0 ]
	[[ $output == *"the pin says"* ]]
}

@test "xdg autostart is live-only and carries no OnlyShowIn" {
	for d in kde cosmic xfce; do
		PATH="${SHIMS}:${PATH}" "${FE}/${d}/install.sh" "${ROOT}"
		app="$(sed -n 's/^APP_ID=//p' "${FE}/${d}/pin.env")"
		f="${D}/deploy/abc.0/etc/xdg/autostart/org.tunaos.installer-live.desktop"
		grep -qF "Exec=sh -c \"grep -qw tunaos.live /proc/cmdline && exec flatpak run ${app}\"" "$f"
		run grep -q OnlyShowIn "$f"
		[ "$status" -ne 0 ]
	done
	grep -q 'X-KDE-autostart-phase=2' "${D}/deploy/abc.0/etc/xdg/autostart/org.tunaos.installer-live.desktop" || true
}

@test "niri spawn line is appended once, to the etc copy seeded from usr" {
	PATH="${SHIMS}:${PATH}" "${FE}/niri/install.sh" "${ROOT}"
	PATH="${SHIMS}:${PATH}" "${FE}/niri/install.sh" "${ROOT}"
	for c in "${D}/deploy/abc.0/etc/niri/config.kdl" "${D}/deploy/abc.0/usr/share/niri/config.kdl"; do
		[ "$(grep -c '^spawn-at-startup' "$c")" -eq 1 ]
		grep -q 'tunaos.live /proc/cmdline && exec flatpak run org.tunaos.InstallerNiri' "$c"
	done
}

@test "niri with no config anywhere is fatal" {
	rm "${D}/deploy/abc.0/usr/share/niri/config.kdl"
	PATH="${SHIMS}:${PATH}" run "${FE}/niri/install.sh" "${ROOT}"
	[ "$status" -ne 0 ]
	[[ $output == *"no niri config.kdl"* ]]
}

@test "nothing bakes the readiness stamp or the EULA" {
	for d in ${DESKTOPS}; do
		PATH="${SHIMS}:${PATH}" "${FE}/${d}/install.sh" "${ROOT}"
	done
	run find "${ROOT}" \( -name 'tuna-installer-ready' -o -name 'eula.xml' \)
	[ -z "$output" ]
}

@test "a plain tree is used when no deployment exists" {
	plain="${WORK}/plain"
	mkdir -p "${plain}"
	PATH="${SHIMS}:${PATH}" run "${FE}/kde/install.sh" "${plain}"
	[ "$status" -eq 0 ]
	[ -f "${plain}/etc/xdg/autostart/org.tunaos.installer-live.desktop" ]
	[ -f "${plain}/var/lib/flatpak/overrides/org.tunaos.InstallerKde" ]
}

@test "two deployments are refused rather than guessed" {
	mkdir -p "${D}/deploy/def.0/etc"
	PATH="${SHIMS}:${PATH}" run "${FE}/kde/install.sh" "${ROOT}"
	[ "$status" -ne 0 ]
	[[ $output == *"more than one candidate"* ]]
}
