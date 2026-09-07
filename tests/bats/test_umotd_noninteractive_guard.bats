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

# The guard block, retargeted at a scratch root so it can actually be RUN.
# Grepping the source cannot tell you the block works; these tests execute it.
run_guard_on() {
	local root="$1"
	sed -n '/^_tunaos_guarded=0$/,/^unset _tunaos_guarded/p' "$SERVICES" |
		sed "s|/etc/profile.d/|${root}/etc/profile.d/|g" >"${root}/guard.sh"
	bash -euo pipefail "${root}/guard.sh"
}

# The guard text the build prepends.
profile_file() {
	sed -n "/cat <<'GUARD_EOF'/,/^GUARD_EOF$/p" "$SERVICES" | sed '1d;$d'
}

@test "both the old and the new upstream banner names are covered" {
	# Upstream is renaming this file: ghcr.io/projectbluefin/common shipped
	# umotd.sh and now ships uwelcome.sh. A fix keyed to one name silently
	# no-ops on images built from the other, which is the whole failure mode
	# this guard exists to prevent. uwelcome.sh has the same defect and
	# upstream knows the shape of it — its own comment says the portal lookup
	# "can stall the prompt when the portal cannot start" — but it guards
	# only against root and double greetings, not against having no terminal.
	grep -q '/etc/profile.d/umotd.sh /etc/profile.d/uwelcome.sh' "$SERVICES"
}

@test "the guard is prepended, so upstream's own logic survives" {
	# uwelcome.sh carries real behaviour (a root guard, a double-greeting
	# guard, a config migration). Replacing the file wholesale would delete
	# it; only the interactive test should be added.
	local root
	root="${BATS_TEST_TMPDIR}/prepend"
	mkdir -p "${root}/etc/profile.d"
	printf '#!/usr/bin/env bash\n\nif [ -z "${UW_SHOWN-}" ]; then UW_SHOWN=1; uwelcome; fi\n' \
		>"${root}/etc/profile.d/uwelcome.sh"
	run_guard_on "$root"
	grep -q 'UW_SHOWN' "${root}/etc/profile.d/uwelcome.sh"
	# Shebang stays on line 1; the guard goes after it, not before.
	head -n1 "${root}/etc/profile.d/uwelcome.sh" | grep -q '^#!'
	# Non-interactive: banner skipped, and the rest of profile.d still runs.
	run env -u UW_SHOWN bash -c "uwelcome(){ echo BANNER; }; . '${root}/etc/profile.d/uwelcome.sh'; echo END"
	[ "$status" -eq 0 ]
	[[ "$output" != *BANNER* ]]
	[[ "$output" == *END* ]]
}

@test "guarding twice changes nothing" {
	local root
	root="${BATS_TEST_TMPDIR}/idem"
	mkdir -p "${root}/etc/profile.d"
	printf '#!/usr/bin/env bash\n\numotd\n' >"${root}/etc/profile.d/umotd.sh"
	run_guard_on "$root"
	local first
	first="$(cat "${root}/etc/profile.d/umotd.sh")"
	run_guard_on "$root"
	[ "$first" = "$(cat "${root}/etc/profile.d/umotd.sh")" ]
}

@test "a future rename is reported, not silently skipped" {
	# The one failure this guard cannot fix by itself. If upstream renames the
	# file again the loop matches nothing, and that must be visible in the
	# build log rather than passing quietly.
	local root
	root="${BATS_TEST_TMPDIR}/renamed"
	mkdir -p "${root}/etc/profile.d"
	printf '#!/usr/bin/env bash\nusomethingelse\n' >"${root}/etc/profile.d/usomethingelse.sh"
	run run_guard_on "$root"
	[ "$status" -eq 0 ]
	[[ "$output" == *"no ublue login-banner script found"* ]]
	# ...and an ALREADY-guarded file must not trip that same note.
	local root2
	root2="${BATS_TEST_TMPDIR}/already"
	mkdir -p "${root2}/etc/profile.d"
	printf '#!/usr/bin/env bash\numotd\n' >"${root2}/etc/profile.d/umotd.sh"
	run_guard_on "$root2"
	run run_guard_on "$root2"
	[[ "$output" != *"no ublue login-banner script found"* ]]
}

@test "the guard lives where every variant runs it" {
	# 40-services.sh is one of only three build scripts invoked by ALL six
	# Containerfiles (arch, el10, ubuntu, debian, opensuse, gentoo). A fix in
	# 01-workarounds.sh would have reached el10 and ubuntu only — Arch, the
	# variant the bug was measured on, does not run it.
	grep -q 'profile.d/umotd.sh' "$SERVICES"
	# ...and in the base stage, ahead of the per-desktop stages. Nothing they
	# lay down touches /etc/profile.d, so the guard survives them.
	! grep -rq 'profile\.d' "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
	local n=0 cf
	for cf in arch el10 ubuntu debian opensuse gentoo; do
		grep -q 'build_scripts/40-services.sh' "${REPO_ROOT}/Containerfile.${cf}" && n=$((n + 1))
	done
	[ "$n" -eq 6 ]
}

@test "the guard is REACHED on every path, not merely invoked" {
	# The test above is necessary and was not sufficient. 40-services.sh has
	# three package-manager paths and the first two END IN `exit 0`:
	# apt, then pacman/zypper/emerge, then dnf falls through to the file's end.
	# Placed at the end, this guard ran on dnf/RPM images ONLY -- silently
	# never on Arch, the variant the umotd hang was measured on.
	#
	# Caught by a real `just build marlin niri`: zero mentions of profile.d
	# anywhere in the build log, and an unguarded umotd.sh in the finished
	# image. Being invoked by every Containerfile is not being reached.
	local guard first_exit
	guard=$(grep -n '_tunaos_guarded=0' "$SERVICES" | head -1 | cut -d: -f1)
	first_exit=$(grep -n 'exit 0' "$SERVICES" | grep -v '^[0-9]*:#' | head -1 | cut -d: -f1)
	[ -n "$guard" ]
	[ -n "$first_exit" ]
	# Must come before the first early exit, or some family never runs it.
	[ "$guard" -lt "$first_exit" ]
}

@test "the guard runs at top level, not inside a package-manager branch" {
	# Indented => nested in one of the per-family `if` blocks, which is the
	# same defect wearing a different hat.
	local line
	line=$(grep -n '_tunaos_guarded=0' "$SERVICES" | head -1 | cut -d: -f1)
	run sed -n "${line}p" "$SERVICES"
	[ "$output" = "_tunaos_guarded=0" ]
}

# The guard alone, followed by a payload standing in for the banner call.
guarded_stub() {
	local f="${BATS_TEST_TMPDIR}/stub.sh"
	{ profile_file; echo 'echo BANNER'; } >"$f"
	printf '%s' "$f"
}

@test "a non-interactive login shell draws nothing" {
	run bash -c ". '$(guarded_stub)'; echo END"
	[ "$status" -eq 0 ]
	[[ "$output" != *BANNER* ]]
	# ...and the rest of /etc/profile.d still runs: `return` must leave the
	# sourcing shell alive, not abort the profile chain.
	[[ "$output" == *END* ]]
}

@test "an interactive login shell still draws the banner" {
	# Guarding must not silently delete the feature.
	run bash -ic ". '$(guarded_stub)'; echo END"
	[[ "$output" == *BANNER* ]]
	[[ "$output" == *END* ]]
}

@test "the guard is POSIX shell, not bash-only" {
	# /etc/profile.d is sourced by dash on the Debian and Ubuntu variants. A
	# [[ ]] test there is a syntax error, which would break every login shell
	# on those images rather than just the banner.
	local f
	f="$(guarded_stub)"
	! grep -q '\[\[' "$f"
	if command -v dash >/dev/null 2>&1; then
		run dash -c ". '$f'; echo END"
		[ "$status" -eq 0 ]
		[[ "$output" != *BANNER* ]]
		[[ "$output" == *END* ]]
	fi
}

@test "a path that is not there is left alone" {
	# Not every variant ships a banner; touching a missing path would create a
	# stray profile.d entry calling a binary that does not exist.
	grep -q '\[\[ -f "\$_f" \]\] || continue' "$SERVICES"
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
