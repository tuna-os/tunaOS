#!/usr/bin/env bats
# tuna-desktop#989 / run 41230684089: a GDM-created Marlin admin was in wheel,
# but sudo refused "user NOT in sudoers". Arch's wheel grant is commented out.
# Assert policy in the final layer shared by every variant, not a per-distro
# hook: Gentoo's headless base skips 40-services.sh.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
DROPIN="${REPO_ROOT}/system_files/etc/sudoers.d/10-tunaos-wheel"
FINAL="${REPO_ROOT}/Containerfile.final"

@test "wheel grant is exactly password-required sudo with no extra rules" {
	printf '%%wheel ALL=(ALL:ALL) ALL\n' >"${BATS_TEST_TMPDIR}/expected"
	cmp "$DROPIN" "${BATS_TEST_TMPDIR}/expected"
}

@test "the actual drop-in parses with visudo" {
	command -v visudo >/dev/null 2>&1 || skip "visudo not installed on this host"
	run visudo -cf "$DROPIN"
	[ "$status" -eq 0 ]
}

@test "the common final layer installs the grant root-owned and 0440" {
	grep -qxF 'COPY --chown=0:0 --chmod=0440 system_files/etc/sudoers.d/10-tunaos-wheel /etc/sudoers.d/10-tunaos-wheel' "$FINAL"
}

@test "the final layer checks both the drop-in and complete sudoers" {
	grep -qF 'visudo -cf /etc/sudoers.d/10-tunaos-wheel &&' "$FINAL"
	grep -qE '^[[:space:]]+visudo -c$' "$FINAL"
	# A rejected sudoers must fail this RUN, not be suppressed.
	! grep -qE 'visudo.*(\|\|[[:space:]]*true|;[[:space:]]*true)' "$FINAL"
}

@test "openSUSE vendor sudoers permissions are tightened before the full check" {
	grep -qF '[ ! -f /etc/sudoers ] && [ -f /usr/etc/sudoers ]' "$FINAL"
	grep -qF 'chmod 0440 /usr/etc/sudoers;' "$FINAL"
}

@test "every variant shares the final layer after rechunking" {
	# The single engine is called with different base Containerfiles, but always
	# builds Containerfile.final after chunkah. No per-variant copy is needed.
	grep -qF -- '--file "Containerfile.final"' "${REPO_ROOT}/scripts/build-image-inner.sh"
}
