#!/usr/bin/env bats
# One rule, applied to every check script systemd runs as part of the boot.
#
# A check that runs from a unit in the initial boot transaction cannot ask the
# manager whether the boot has finished. `systemctl is-system-running --wait`
# returns when the manager leaves `starting`; the manager leaves `starting`
# when the transaction drains; and the check's own job is one of the jobs
# holding that transaction open. The wait is on itself, and no bound makes it
# correct — a bound only decides how long the deadlock lasts before something
# kills it.
#
# This has now been found five times in this tree (docs/ci-troubleshooting.md
# rows 29, 33, 35, 42, 43). Row 42 fixed `e2e-runtime-checks.sh` and pinned it
# in test_graphical_target_assertion.bats — but that guard names ONE file, so
# `verify-base-contract.sh` kept the defect for another month with a guard for
# it sitting in the same test suite. Row 43 is that miss.
#
# Hence this file: it does not name the scripts. It DERIVES them, from the
# units the build actually writes, so instance six is covered before anyone
# knows it exists.

setup() {
	REPO_ROOT="$(cd "$(dirname "${BATS_TEST_FILENAME}")/../.." && pwd)"
}

# Every script installed into /usr/libexec/tunaos/ that some unit in this tree
# names in an ExecStart=. Printed as repo-relative paths, one per line.
#
# The two halves are matched on the libexec basename: build_scripts installs
# `install -Dm0755 <src> /usr/libexec/tunaos/<name>` and then writes a unit
# whose `ExecStart=[-]/usr/libexec/tunaos/<name> …` refers to it. A script
# that is installed but never run by a unit is not this rule's business.
in_unit_check_scripts() {
	local names name src flat

	names=$(grep -rhoE 'ExecStart=-?/usr/libexec/tunaos/[A-Za-z0-9_-]+' \
		"${REPO_ROOT}/build_scripts" "${REPO_ROOT}/system_files" 2>/dev/null |
		sed -E 's#.*/usr/libexec/tunaos/##' | sort -u)

	# The install is routinely split over two lines with a trailing backslash,
	# so join continuations before matching src to dst.
	flat=$(find "${REPO_ROOT}/build_scripts" -name '*.sh' -exec \
		sed -e ':a' -e '/\\$/{N;s/\\\n//;ta}' {} + 2>/dev/null)

	for name in $names; do
		# One libexec name can have several sources (verify-nvidia is
		# installed from a per-distro variant); the rule applies to all of
		# them.
		while read -r src; do
			[[ -n "$src" ]] || continue
			# "${_TD_CTX}/build_scripts/…" and /run/context/build_scripts/…
			# are the same file in this repo.
			src=$(sed -E 's#^.*/(build_scripts/)#\1#; s#"##g' <<<"$src")
			[[ "$src" == build_scripts/* && -f "${REPO_ROOT}/${src}" ]] && echo "$src"
		done < <(printf '%s\n' "$flat" |
			grep -oE "install -Dm0755[[:space:]]+[^[:space:]]+[[:space:]]+/usr/libexec/tunaos/${name}([[:space:]]|\$)" |
			awk '{ print $3 }')

		# Shipped as a file instead of installed by a build script.
		[[ -f "${REPO_ROOT}/system_files/usr/libexec/tunaos/${name}" ]] &&
			echo "system_files/usr/libexec/tunaos/${name}"
	done | sort -u
}

@test "the derivation finds the check scripts systemd runs during boot" {
	# A guard that silently derives an empty list is not a guard. These three
	# are the units' ExecStart targets today; the test below reads whatever
	# the derivation returns, so adding a fourth needs no edit here.
	local found
	found=$(in_unit_check_scripts)
	echo "derived: ${found}" >&2
	[ -n "$found" ]
	echo "$found" | grep -qx 'build_scripts/checks/verify-base-contract.sh'
	echo "$found" | grep -qx 'build_scripts/checks/e2e-runtime-checks.sh'
	echo "$found" | grep -qx 'build_scripts/checks/verify-desktop-experience.sh'
}

# Blank out whole-line comments, keeping the line count so reported numbers
# stay real. Explaining a deadlock in a comment must not read as committing
# one — which the fix for this very issue does, at length, in
# verify-base-contract.sh.
code_only() {
	sed -E 's/^[[:space:]]*#.*$//' "${REPO_ROOT}/$1"
}

@test "no boot-transaction check waits for the boot to finish" {
	local script failures=""
	for script in $(in_unit_check_scripts); do
		# `--wait` anywhere on an is-system-running command, however it is
		# spelled or ordered.
		if code_only "$script" |
			grep -nE 'is-system-running[^|;&]*--wait|--wait[^|;&]*is-system-running'; then
			failures+=" ${script}"
		fi
	done
	[ -z "$failures" ] || {
		echo "waits on a settle its own job blocks:${failures}" >&2
		false
	}
}

@test "no boot-transaction check polls for the boot to finish either" {
	# A retry loop around is-system-running is the same deadlock spelled by
	# hand: it cannot observe anything but `starting` until it gives up, so
	# it only converts an instant wrong answer into a slow one.
	local script failures=""
	for script in $(in_unit_check_scripts); do
		if code_only "$script" | grep -nE '(while|until|for).*is-system-running'; then
			failures+=" ${script}"
		fi
	done
	[ -z "$failures" ] || {
		echo "polls for a settle its own job blocks:${failures}" >&2
		false
	}
}

# ── The base contract's own verdict, both directions ────────────────────────
#
# These run the REAL script. Copying its predicate into the test would assert
# that the copy is right, and the defect being fixed here is precisely that
# nothing ever ran this contract to completion — on any cell, in either
# direction. A test that cannot reach the end of the script reproduces the
# bug rather than catching it.

# $1 = what `is-system-running` answers, $2… = failed unit names, if any.
run_base_contract() {
	local state="$1"
	shift
	local failed_lines=""
	local u
	for u in "$@"; do
		failed_lines+="${u} loaded failed failed Some unit"$'\n'
	done

	# is-system-running exits non-zero for every state but `running`, which is
	# why the script reads it with `|| true`. Reproduce that faithfully: a
	# stub that always exits 0 would hide a regression in the handling.
	eval "systemctl() {
		case \"\$1\" in
		is-system-running)
			[[ -n '${state}' ]] && echo '${state}'
			[[ '${state}' == running ]] && return 0
			return 1
			;;
		list-units) printf '%s' \"\${_TUNAOS_TEST_FAILED_UNITS}\" ;;
		esac
		return 0
	}"
	bootc() { return 0; }
	export -f systemctl bootc
	export _TUNAOS_TEST_FAILED_UNITS="${failed_lines}"

	run bash "${REPO_ROOT}/build_scripts/checks/verify-base-contract.sh" --runtime
}

@test "end to end: the measured base-cell sample (starting) reaches a verdict" {
	# `starting` is what a correct run produces on a base cell, because the
	# unit is a job in the transaction it would be asking about. Treating it
	# as a defect is what made `reason=system-state=starting` the only verdict
	# this contract ever emitted — a description of the check, not the image.
	run_base_contract starting
	[ "$status" -eq 0 ]
	[[ "$output" == *"TUNAOS_BASE_CONTRACT_OK"* ]]
	[[ "$output" == *"state=starting"* ]]
}

@test "end to end: every other healthy sample reaches the same verdict" {
	local state
	for state in running degraded initializing; do
		run_base_contract "$state"
		[ "$status" -eq 0 ]
		[[ "$output" == *"TUNAOS_BASE_CONTRACT_OK"* ]]
	done
}

@test "end to end: a genuinely broken boot still fails" {
	# Proof the fix did not soften this into a check that always passes.
	local state
	for state in maintenance stopping offline "" garbage; do
		run_base_contract "$state"
		[ "$status" -eq 1 ]
		[[ "$output" == *"TUNAOS_BASE_CONTRACT_FAIL"* ]]
		[[ "$output" == *"reason=system-state="* ]]
	done
}

@test "end to end: the bootc assertion below the sample is now reachable" {
	# It never ran on any cell: the wait above it was killed first. That is
	# what made the contract vacuous, so it is what has to be pinned.
	eval 'systemctl() { case "$1" in is-system-running) echo starting; return 1 ;; esac; return 0; }'
	bootc() { return 1; }
	export -f systemctl bootc
	export _TUNAOS_TEST_FAILED_UNITS=""

	run bash "${REPO_ROOT}/build_scripts/checks/verify-base-contract.sh" --runtime
	[ "$status" -eq 1 ]
	[[ "$output" == *"TUNAOS_BASE_CONTRACT_FAIL reason=bootc-status-failed"* ]]
}

@test "end to end: a degraded boot names the units that failed" {
	# `degraded` deliberately passes — which units a variant may fail is not
	# a boot gate's call — but a verdict nobody can act on is barely a
	# verdict. The names are evidence, never a reason to fail.
	run_base_contract degraded chronyd.service nfs-idmapd.service
	[ "$status" -eq 0 ]
	[[ "$output" == *"TUNAOS_BASE_CONTRACT_OK"* ]]
	[[ "$output" == *"failed-units=chronyd.service,nfs-idmapd.service"* ]]
}

@test "end to end: a clean boot says so rather than saying nothing" {
	run_base_contract running
	[ "$status" -eq 0 ]
	[[ "$output" == *"failed-units=none"* ]]
}

@test "the base contract classifies states exactly as the desktop one does" {
	# Rows 42 and 43 are one defect found twice. The two scripts having
	# drifted apart again would mean a third.
	local base desktop
	base=$(grep -oE 'running \| degraded \| initializing \| starting' \
		"${REPO_ROOT}/build_scripts/checks/verify-base-contract.sh" | head -1)
	desktop=$(grep -oE 'running \| degraded \| initializing \| starting' \
		"${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh" | head -1)
	[ -n "$base" ]
	[ "$base" = "$desktop" ]
}
