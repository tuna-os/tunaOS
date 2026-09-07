#!/usr/bin/env bats
# The MOTD banner must never draw in a non-interactive shell.
#
# WHY THIS EXISTS: on a marlin:cosmic live ISO the desktop never appeared —
# black screen, zero failed units, nothing in the journal naming a cause.
# greetd's `source_profile` default runs the session command through a login
# shell; that sources /etc/profile.d/umotd.sh; the file ublue ships calls the
# `umotd` banner unconditionally, so it ran with no terminal draining its
# output and was left in `wait_woken`. The `exec cosmic-session` after it never
# ran. The same shape applies to `ssh host command` and to the greeter session
# on INSTALLED systems, which is why the fix is in the image build rather than
# in the live-only greetd adapters.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SERVICES="${REPO_ROOT}/build_scripts/40-services.sh"

# The replacement profile.d file the build writes.
profile_file() {
	sed -n "/cat >\/etc\/profile.d\/umotd.sh <<'UMOTD_EOF'/,/^UMOTD_EOF$/p" \
		"$SERVICES" | sed '1d;$d'
}

@test "the guard lives where every variant runs it" {
	# 40-services.sh is one of only three build scripts invoked by ALL six
	# Containerfiles (arch, el10, ubuntu, debian, opensuse, gentoo). A fix in
	# 01-workarounds.sh would have reached el10 and ubuntu only — Arch, the
	# variant the bug was measured on, does not run it.
	grep -q 'profile.d/umotd.sh' "$SERVICES"
	local n=0 cf
	for cf in arch el10 ubuntu debian opensuse gentoo; do
		grep -q 'build_scripts/40-services.sh' "${REPO_ROOT}/Containerfile.${cf}" && n=$((n + 1))
	done
	[ "$n" -eq 6 ]
}

@test "a non-interactive login shell draws nothing" {
	local f="${BATS_TEST_TMPDIR}/umotd.sh"
	profile_file >"$f"
	run bash -c "umotd() { echo BANNER; }; . '$f'; echo END"
	[ "$status" -eq 0 ]
	[[ "$output" != *BANNER* ]]
	# ...and the rest of /etc/profile.d still runs: `return` must leave the
	# sourcing shell alive, not abort the profile chain.
	[[ "$output" == *END* ]]
}

@test "an interactive login shell still draws the banner" {
	# Guarding must not silently delete the feature.
	local f="${BATS_TEST_TMPDIR}/umotd.sh"
	profile_file >"$f"
	run bash -ic "umotd() { echo BANNER; }; . '$f'; echo END"
	[[ "$output" == *BANNER* ]]
}

@test "the guard is POSIX shell, not bash-only" {
	# /etc/profile.d is sourced by dash on the Debian and Ubuntu variants. A
	# [[ ]] test there is a syntax error, which would break every login shell
	# on those images rather than just the banner.
	local f="${BATS_TEST_TMPDIR}/umotd.sh"
	profile_file >"$f"
	! grep -q '\[\[' "$f"
	if command -v dash >/dev/null 2>&1; then
		run dash -c "umotd() { echo BANNER; }; . '$f'; echo END"
		[ "$status" -eq 0 ]
		[[ "$output" != *BANNER* ]]
		[[ "$output" == *END* ]]
	fi
}

@test "rewriting the file is guarded on the file existing" {
	# Not every variant ships umotd; clobbering a path that is not there would
	# create a stray profile.d entry calling a missing binary.
	grep -q 'if \[\[ -f /etc/profile.d/umotd.sh \]\]; then' "$SERVICES"
}

@test "live greetd adapters keep source_profile = false" {
	# Defence in depth against the NEXT blocking profile script, not a second
	# copy of the umotd fix. Removing these should be a deliberate act.
	local d
	for d in cosmic niri xfce; do
		grep -q 'source_profile = false' \
			"${REPO_ROOT}/live-iso/common/src/desktop-${d}.sh"
	done
}
