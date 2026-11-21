#!/usr/bin/env bats
# tunaOS#4859: a TunaOS image has only the Flatpak remotes tunaos.toml
# configures.
#
# bonito enabled flatpak-add-fedora-repos.service (Fedora's flatpak package),
# which added the `fedora` and `fedora-testing` remotes on first boot.
# 40-services.sh masks it on every base, and
# build_scripts/checks/verify-flatpak-remotes.sh stops the build when the unit
# is enabled, another enabled unit runs `flatpak remote-add`, or a remotes.d
# drop-in names a remote outside {flathub, tuna-os}. The check runs here
# against fixture roots shaped like the measured bonito image
# (ghcr.io/tuna-os/bonito 4da19013091a: the preset link, the two drop-ins).
#
# Falsification: delete the mask from 40-services.sh, and the fixture built
# from its unit-policy lines keeps the preset link, so the check fails. Leave
# a fedora, a fedora-testing or a Fedora-filtered flathub drop-in, or enable a
# second remote-add unit, and the check exits non-zero with
# TUNAOS_FLATPAK_REMOTES_FAIL.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CHECK="${REPO_ROOT}/build_scripts/checks/verify-flatpak-remotes.sh"
FEDORA_UNIT="flatpak-add-fedora-repos.service"

setup() {
	ROOT="${BATS_TEST_TMPDIR}/root"
	mkdir -p "${ROOT}/usr/lib/systemd/system" "${ROOT}/etc/systemd/system/multi-user.target.wants" \
		"${ROOT}/etc/flatpak/remotes.d" "${ROOT}/usr/share/flatpak/remotes.d"
	# The unit Fedora's flatpak-1.18.4-1.fc44 ships, and its preset link.
	cat >"${ROOT}/usr/lib/systemd/system/${FEDORA_UNIT}" <<'EOF'
[Unit]
Description=Add Fedora flatpak repositories

[Service]
Type=oneshot
ExecStart=/usr/bin/flatpak remote-add --system --if-not-exists --title "Fedora Flatpaks" fedora oci+https://registry.fedoraproject.org

[Install]
WantedBy=multi-user.target
EOF
	ln -s "/usr/lib/systemd/system/${FEDORA_UNIT}" \
		"${ROOT}/etc/systemd/system/multi-user.target.wants/${FEDORA_UNIT}"
	printf '[Flatpak Repo]\nTitle=Flathub\nUrl=https://dl.flathub.org/repo/\n' \
		>"${ROOT}/etc/flatpak/remotes.d/flathub.flatpakrepo"
	printf '[Flatpak Repo]\nTitle=TunaOS Flatpaks\nUrl=oci+https://tunaos.org/flatpak\n' \
		>"${ROOT}/etc/flatpak/remotes.d/tuna-os.flatpakrepo"
	export TUNAOS_FLATPAK_CHECK_ROOT="${ROOT}"
	export TUNAOS_IDENTITY_ENV="${REPO_ROOT}/build_scripts/lib/identity.env"
}

# What 40-services.sh does to the unit, applied to the fixture root: every
# systemctl line of the script that names the Fedora unit.
apply_unit_policy() {
	local line
	while IFS= read -r line; do
		[[ "${line}" == "systemctl mask ${FEDORA_UNIT}" ]] || {
			echo "unexpected policy line: ${line}" >&2
			return 1
		}
		ln -sf /dev/null "${ROOT}/etc/systemd/system/${FEDORA_UNIT}"
	done < <(grep -E "^[[:space:]]*systemctl .*${FEDORA_UNIT}" "${REPO_ROOT}/build_scripts/40-services.sh" | sed 's/^[[:space:]]*//')
}

@test "the measured bonito image fails the check as it was" {
	run "${CHECK}"
	[ "$status" -ne 0 ]
	[[ "$output" == *"${FEDORA_UNIT} is enabled"* ]]
	[[ "$output" == *TUNAOS_FLATPAK_REMOTES_FAIL* ]]
}

@test "40-services.sh masks the Fedora unit and the check passes" {
	apply_unit_policy
	[ -L "${ROOT}/etc/systemd/system/${FEDORA_UNIT}" ]
	run "${CHECK}"
	[ "$status" -eq 0 ]
	[[ "$output" == *"TUNAOS_FLATPAK_REMOTES_OK fedora-unit=masked remotes=flathub,tuna-os"* ]]
	[ "$(cat "${ROOT}/usr/share/tunaos/flatpak-remotes.expected")" = "$(printf 'flathub\thttps://dl.flathub.org/repo/\ntuna-os\toci+https://tunaos.org/flatpak')" ]
}

@test "a base without the unit passes as not-found" {
	rm "${ROOT}/usr/lib/systemd/system/${FEDORA_UNIT}" "${ROOT}/etc/systemd/system/multi-user.target.wants/${FEDORA_UNIT}"
	run "${CHECK}"
	[ "$status" -eq 0 ]
	[[ "$output" == *"fedora-unit=not-found"* ]]
}

@test "a fedora or fedora-testing drop-in fails the check" {
	apply_unit_policy
	for name in fedora fedora-testing; do
		printf '[Flatpak Repo]\nUrl=oci+https://registry.fedoraproject.org\n' \
			>"${ROOT}/usr/share/flatpak/remotes.d/${name}.flatpakrepo"
		run "${CHECK}"
		[ "$status" -ne 0 ]
		[[ "$output" == *"adds remote '${name}'"* ]]
		rm "${ROOT}/usr/share/flatpak/remotes.d/${name}.flatpakrepo"
	done
}

@test "flathub at another URL fails the check" {
	apply_unit_policy
	printf '[Flatpak Repo]\nUrl=https://flathub.example/repo/\n' >"${ROOT}/etc/flatpak/remotes.d/flathub.flatpakrepo"
	run "${CHECK}"
	[ "$status" -ne 0 ]
	[[ "$output" == *"points flathub at https://flathub.example/repo/"* ]]
}

@test "another enabled unit that runs flatpak remote-add fails the check" {
	apply_unit_policy
	printf '[Service]\nExecStart=/usr/bin/flatpak remote-add --system other https://other.example/repo\n' \
		>"${ROOT}/usr/lib/systemd/system/vendor-remote.service"
	ln -s /usr/lib/systemd/system/vendor-remote.service "${ROOT}/etc/systemd/system/multi-user.target.wants/vendor-remote.service"
	run "${CHECK}"
	[ "$status" -ne 0 ]
	[[ "$output" == *"vendor-remote.service runs 'flatpak remote-add' and is enabled"* ]]
}

@test "with no [flatpak_preinstall] remote_url, a tuna-os drop-in fails the check" {
	apply_unit_policy
	sed 's/^TUNAOS_FLATPAK_REMOTE_URL=.*/TUNAOS_FLATPAK_REMOTE_URL=/' "${TUNAOS_IDENTITY_ENV}" >"${BATS_TEST_TMPDIR}/identity.env"
	TUNAOS_IDENTITY_ENV="${BATS_TEST_TMPDIR}/identity.env" run "${CHECK}"
	[ "$status" -ne 0 ]
	[[ "$output" == *"adds remote 'tuna-os'"* ]]
}

@test "the build runs the check in the base and desktop stages" {
	grep -qxF '/run/context/build_scripts/checks/verify-flatpak-remotes.sh' "${REPO_ROOT}/build_scripts/99-cleanup.sh"
	grep -qxF '"$(dirname "${BASH_SOURCE[0]}")/../checks/verify-flatpak-remotes.sh"' "${REPO_ROOT}/build_scripts/desktop/tuna-flatpak-remote.sh"
	# Every desktop manifest runs that hook, so every desktop stage runs the check.
	for manifest in "${REPO_ROOT}"/manifests/desktops/*.yaml; do
		grep -q '"tuna-flatpak-remote.sh"' "${manifest}" || {
			echo "${manifest} does not run tuna-flatpak-remote.sh" >&2
			return 1
		}
	done
}
