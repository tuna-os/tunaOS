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
		grep -q -- "--commit=${rt} flathub" "${LOG}"
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

@test "xdg autostart runs the launcher and carries no OnlyShowIn" {
	for d in kde cosmic xfce niri; do
		PATH="${SHIMS}:${PATH}" "${FE}/${d}/install.sh" "${ROOT}"
		app="$(sed -n 's/^APP_ID=//p' "${FE}/${d}/pin.env")"
		f="${D}/deploy/abc.0/etc/xdg/autostart/org.tunaos.installer-live.desktop"
		grep -qE "^Exec=/usr/libexec/medium-live-installer( --once)? -- flatpak run ${app}\$" "$f"
		run grep -q OnlyShowIn "$f"
		[ "$status" -ne 0 ]
		[ "$d" != kde ] || grep -qx 'X-KDE-autostart-phase=2' "$f"
	done
}

# --- live session: dispatcher contract and the boot hooks --------------------
#
# stage DESKTOP: run the dispatcher into a plain scratch root, as the payload
# stage of Containerfile.live does. Sets STAGE.
stage() {
	STAGE="${WORK}/stage-$1"
	mkdir -p "${STAGE}"
	PATH="${SHIMS}:${PATH}" run "${FE}/install-frontend.sh" "$1" "${STAGE}"
	[ "$status" -eq 0 ] || {
		echo "$output" >&2
		false
	}
}

# image DM_UNIT EXECSTART: a root that starts DM_UNIT through the alias, laid
# out as the published images are. Sets R.
image() {
	R="${WORK}/image"
	rm -rf "${R}"
	mkdir -p "${R}/etc/systemd/system/graphical.target.wants" "${R}/usr/lib/systemd/system" \
		"${R}/usr/bin" "${R}/etc/greetd" "${R}/etc/pam.d" "${R}/var/home/liveuser"
	printf '[Service]\nExecStart=%s\n' "$2" >"${R}/usr/lib/systemd/system/$1"
	ln -s "/usr/lib/systemd/system/$1" "${R}/etc/systemd/system/display-manager.service"
	: >"${R}/etc/pam.d/greetd"
	: >"${R}/etc/pam.d/greetd-greeter"
}

have() {
	local b
	for b in "$@"; do
		printf '#!/bin/sh\n' >"${R}/usr/bin/${b}"
		chmod +x "${R}/usr/bin/${b}"
	done
}

# hook DESKTOP: run the staged boot hook against R for liveuser.
hook() {
	MEDIUM_LIVE_ROOT="${R}" MEDIUM_LIVE_HOME=/var/home/liveuser \
		MEDIUM_LIVE_LIB="${STAGE}/usr/lib/medium-live/greeter.sh" \
		PATH="${SHIMS}:${PATH}" run "${STAGE}/usr/lib/medium-live/live-setup.d/50-$1-session" liveuser
}

toml_ok() {
	python3 -c 'import sys, tomllib; c = tomllib.load(open(sys.argv[1], "rb")); assert c["initial_session"]["user"] == "liveuser" and c["general"]["source_profile"] is False' "$1"
}

@test "the dispatcher accepts every native desktop in a plain staging root" {
	for d in kde cosmic niri xfce; do
		stage "$d"
		[[ $output == *"install-frontend: ${d} ready"* ]]
		[ "$(cat "${STAGE}/usr/share/medium-live/stamp.d/${d}")" = native ]
		list="${STAGE}/usr/share/medium-live/payload.d/${d}.list"
		grep -qx /etc/xdg/autostart/org.tunaos.installer-live.desktop "${list}"
		grep -qx /usr/libexec/medium-live-installer "${list}"
		grep -qx "/var/lib/flatpak/app/$(sed -n 's/^APP_ID=//p' "${FE}/${d}/pin.env")" "${list}"
		[ "$(sort -u "${list}" | wc -l)" -eq "$(wc -l <"${list}")" ]
	done
}

@test "cosmic, niri and xfce stage a boot hook; the build writes no greeter or niri config" {
	for d in cosmic niri xfce; do
		stage "$d"
		[ -x "${STAGE}/usr/lib/medium-live/live-setup.d/50-${d}-session" ]
		cmp "${FE}/live-greeter.sh" "${STAGE}/usr/lib/medium-live/greeter.sh"
		grep -qx "/usr/lib/medium-live/live-setup.d/50-${d}-session" "${STAGE}/usr/share/medium-live/payload.d/${d}.list"
		grep -qx /usr/lib/medium-live/greeter.sh "${STAGE}/usr/share/medium-live/payload.d/${d}.list"
		run find "${STAGE}" \( -path '*/greetd/*' -o -path '*/lightdm/*' -o -name config.kdl -o -path '*/pam.d/*' \)
		[ -z "$output" ]
	done
	# KDE: medium-live-setup owns the SDDM autologin, so there is no hook.
	stage kde
	[ ! -e "${STAGE}/usr/lib/medium-live/live-setup.d" ]
}

@test "cosmic: autologin goes to the file cosmic-greeter.service gives greetd" {
	# bonito:cosmic 6793503c795a: the alias names cosmic-greeter.service and
	# greetd.service is disabled.
	stage cosmic
	image cosmic-greeter.service 'greetd --config /etc/greetd/cosmic-greeter.toml'
	have cosmic-session start-cosmic
	printf '[terminal]\nvt = "1"\n\n[general]\nservice = "cosmic-greeter"\n\n[default_session]\ncommand = "cosmic-greeter-start"\nuser = "cosmic-greeter"\n' >"${R}/etc/greetd/cosmic-greeter.toml"
	printf '[default_session]\ncommand = "agreety --cmd /bin/sh"\nuser = "greetd"\n' >"${R}/etc/greetd/config.toml"
	before="$(sha256sum <"${R}/etc/greetd/config.toml")"
	hook cosmic
	[ "$status" -eq 0 ]
	toml_ok "${R}/etc/greetd/cosmic-greeter.toml"
	[ "$(grep -c 'command = "systemd-cat -t medium-live-session env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin cosmic-session"' "${R}/etc/greetd/cosmic-greeter.toml")" -eq 2 ]
	run grep -c start-cosmic "${R}/etc/greetd/cosmic-greeter.toml"
	[ "$output" = 0 ]
	[ "$(sha256sum <"${R}/etc/greetd/config.toml")" = "${before}" ]
}

@test "niri: greetd autologin, and the start line once in the config niri loads" {
	# bonito:niri a2dcc3b1d7e3: greetd.service, /usr/share/niri/config.kdl only.
	stage niri
	image greetd.service greetd
	have niri-session
	mkdir -p "${R}/usr/share/niri"
	printf 'spawn-at-startup "waybar"\n' >"${R}/usr/share/niri/config.kdl"
	printf '[general]\nservice = "greetd-spawn"\n\n[default_session]\ncommand = "dms-greeter --command niri"\nuser = "greeter"\n' >"${R}/etc/greetd/config.toml"
	hook niri
	[ "$status" -eq 0 ]
	hook niri
	[ "$status" -eq 0 ]
	toml_ok "${R}/etc/greetd/config.toml"
	grep -q 'usr/bin niri-session"$' "${R}/etc/greetd/config.toml"
	c="${R}/var/home/liveuser/.config/niri/config.kdl"
	grep -qx 'spawn-at-startup "waybar"' "$c"
	[ "$(grep -c 'medium-live-installer' "$c")" -eq 1 ]
	grep -qx 'spawn-at-startup "/usr/libexec/medium-live-installer" "--once" "--" "flatpak" "run" "org.tunaos.InstallerNiri"' "$c"
	# /usr is read-only on a booted medium: the image default stays as it is.
	[ "$(cat "${R}/usr/share/niri/config.kdl")" = 'spawn-at-startup "waybar"' ]
	grep -q -- ' --once -- flatpak run org.tunaos.InstallerNiri$' "${STAGE}/etc/xdg/autostart/org.tunaos.installer-live.desktop"
}

@test "niri: a user config from /etc/skel is kept and gets the line" {
	stage niri
	image greetd.service greetd
	have niri-session
	mkdir -p "${R}/var/home/liveuser/.config/niri" "${R}/usr/share/niri"
	printf '// from skel\n' >"${R}/var/home/liveuser/.config/niri/config.kdl"
	printf '// image default\n' >"${R}/usr/share/niri/config.kdl"
	hook niri
	[ "$status" -eq 0 ]
	grep -qx '// from skel' "${R}/var/home/liveuser/.config/niri/config.kdl"
	grep -q medium-live-installer "${R}/var/home/liveuser/.config/niri/config.kdl"
	[ "$(cat "${R}/usr/share/niri/config.kdl")" = '// image default' ]
}

@test "niri: no config anywhere stops the boot setup" {
	stage niri
	image greetd.service greetd
	have niri-session
	before="$(tree_hash "${R}")"
	hook niri
	[ "$status" -ne 0 ]
	[[ $output == *"no niri config.kdl"* ]]
	[ "$(tree_hash "${R}")" = "${before}" ]
}

@test "xfce: LightDM autologin into the X11 session the image ships" {
	# bonito:xfce c94c945d8b4c: the alias names lightdm.service, gdm.service
	# is in graphical.target.wants, the session is xsessions/xfce.desktop.
	stage xfce
	image lightdm.service /usr/sbin/lightdm
	ln -s /usr/lib/systemd/system/gdm.service "${R}/etc/systemd/system/graphical.target.wants/gdm.service"
	mkdir -p "${R}/usr/share/xsessions"
	: >"${R}/usr/share/xsessions/xfce.desktop"
	printf '#!/bin/sh\necho "$0 $*" >>"%s"\n' "${LOG}" >"${SHIMS}/groupadd"
	cp "${SHIMS}/groupadd" "${SHIMS}/usermod"
	chmod +x "${SHIMS}/groupadd" "${SHIMS}/usermod"
	hook xfce
	[ "$status" -eq 0 ]
	[[ $output == *"WARNING: graphical.target also wants gdm.service"* ]]
	f="${R}/etc/lightdm/lightdm.conf.d/90-medium-live-autologin.conf"
	grep -qx 'autologin-user=liveuser' "$f"
	grep -qx 'autologin-session=xfce' "$f"
	grep -q 'usermod -aG autologin liveuser' "${LOG}"
	# greetd is installed but is not the display manager: leave it alone.
	[ ! -e "${R}/etc/greetd/config.toml" ]
}

@test "xfce: LightDM with no xfce session file stops the boot setup" {
	stage xfce
	image lightdm.service /usr/sbin/lightdm
	hook xfce
	[ "$status" -ne 0 ]
	[[ $output == *"no xfce session"* ]]
	[ ! -e "${R}/etc/lightdm" ]
}

@test "xfce: greetd starts the Wayland session through the compositor it finds" {
	stage xfce
	image greetd.service greetd
	have xfwl4 startxfce4 dbus-run-session
	hook xfce
	[ "$status" -eq 0 ]
	toml_ok "${R}/etc/greetd/config.toml"
	grep -q 'usr/bin SMITHAY_USE_LEGACY=1 dbus-run-session startxfce4 --wayland xfwl4"$' "${R}/etc/greetd/config.toml"
	image greetd.service greetd
	have labwc startxfce4 dbus-run-session
	hook xfce
	[ "$status" -eq 0 ]
	grep -q 'usr/bin dbus-run-session startxfce4 --wayland labwc"$' "${R}/etc/greetd/config.toml"
}

@test "xfce: greetd with no Wayland compositor stops the boot setup" {
	stage xfce
	image greetd.service greetd
	have startxfce4 dbus-run-session
	hook xfce
	[ "$status" -ne 0 ]
	[[ $output == *"no Wayland compositor"* ]]
}

@test "an unknown, masked or missing display manager fails; nothing is written" {
	for d in cosmic niri xfce; do
		stage "$d"
		# A display manager with no rule for this desktop (GDM is the trap:
		# AGENTS.md, "A detection default is a silent fallback").
		image gdm.service /usr/bin/gdm
		have cosmic-session niri-session startxfce4
		mkdir -p "${R}/usr/share/niri"
		: >"${R}/usr/share/niri/config.kdl"
		before="$(tree_hash "${R}")"
		hook "$d"
		[ "$status" -ne 0 ]
		[[ $output == *"gdm.service"* ]]
		[ "$(tree_hash "${R}")" = "${before}" ]
		# Masked.
		ln -sf /dev/null "${R}/etc/systemd/system/display-manager.service"
		hook "$d"
		[ "$status" -ne 0 ]
		[[ $output == *"masked"* ]]
		# No alias and nothing in graphical.target.wants.
		rm "${R}/etc/systemd/system/display-manager.service"
		hook "$d"
		[ "$status" -ne 0 ]
		[[ $output == *"cannot tell which display manager"* ]]
		# No alias and two candidates.
		: >"${R}/etc/systemd/system/graphical.target.wants/greetd.service"
		: >"${R}/etc/systemd/system/graphical.target.wants/lightdm.service"
		hook "$d"
		[ "$status" -ne 0 ]
		[[ $output == *"cannot tell which display manager"* ]]
	done
}

@test "a display manager with no alias is found in graphical.target.wants" {
	stage cosmic
	image greetd.service greetd
	have cosmic-session
	rm "${R}/etc/systemd/system/display-manager.service"
	: >"${R}/etc/systemd/system/graphical.target.wants/greetd.service"
	hook cosmic
	[ "$status" -eq 0 ]
	toml_ok "${R}/etc/greetd/config.toml"
}

@test "a greetd unit that does not start greetd is refused" {
	stage cosmic
	image cosmic-greeter.service /usr/bin/something-else
	have cosmic-session
	hook cosmic
	[ "$status" -ne 0 ]
	[[ $output == *"does not start greetd"* ]]
}

@test "greetd gets a PAM service only where the image has none" {
	stage cosmic
	image greetd.service greetd
	have cosmic-session
	hook cosmic
	[ ! -s "${R}/etc/pam.d/greetd" ]
	rm "${R}/etc/pam.d/greetd" "${R}/etc/pam.d/greetd-greeter"
	hook cosmic
	[ "$status" -eq 0 ]
	grep -q pam_permit.so "${R}/etc/pam.d/greetd"
	grep -q pam_permit.so "${R}/etc/pam.d/greetd-greeter"
}

@test "launcher --once starts one installer for two start paths" {
	printf 'root=x tunaos.live\n' >"${WORK}/cmdline"
	mkdir -p "${WORK}/run"
	L="${FE}/medium-live-installer"
	MEDIUM_CMDLINE="${WORK}/cmdline" XDG_RUNTIME_DIR="${WORK}/run" "$L" --once -- sh -c "touch '${WORK}/first'; sleep 5" 9>&- 3>&- &
	for _ in $(seq 1 50); do [ -e "${WORK}/first" ] && break || sleep 0.1; done
	[ -e "${WORK}/first" ]
	MEDIUM_CMDLINE="${WORK}/cmdline" XDG_RUNTIME_DIR="${WORK}/run" run "$L" --once -- touch "${WORK}/second"
	[ "$status" -eq 0 ]
	[[ $output == *"already runs"* ]]
	[ ! -e "${WORK}/second" ]
	# Without --once the launcher takes no lock.
	MEDIUM_CMDLINE="${WORK}/cmdline" XDG_RUNTIME_DIR="${WORK}/run" run "$L" -- touch "${WORK}/third"
	[ -e "${WORK}/third" ]
	kill %1 2>/dev/null || true
}

@test "medium-live-setup runs before each display manager it can configure" {
	unit="${REPO_ROOT}/installer-medium/live/usr/lib/systemd/system/medium-live-setup.service"
	grep -qx 'ConditionKernelCommandLine=tunaos.live' "${unit}"
	for u in display-manager gdm sddm lightdm greetd cosmic-greeter; do
		grep -E '^Before=' "${unit}" | grep -qw "${u}.service"
	done
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
