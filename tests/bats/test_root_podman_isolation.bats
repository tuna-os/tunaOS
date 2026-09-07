#!/usr/bin/env bats
# Root-context scripts must never touch the invoking user's podman stores.
#
# WHY: scripts/iso-e2e.sh is run under `sudo -E` (Justfile and CI both do it),
# which preserves HOME and XDG_RUNTIME_DIR. It makes a host-side `podman image
# exists` probe, and with those preserved, root's podman writes into the USER's
# stores. MEASURED three times in one session:
#
#   /run/user/1000/containers/overlay-layers/mountpoints.json  -> root-owned
#   Error: loading primary layer store data: ... permission denied
#
# after which the user's rootless podman cannot start at all, and the next
# `just build` dies with "unable to copy from source ... trying to reuse blob".
#
# The harness itself never notices -- it runs as root and finishes fine. The
# damage only surfaces the next time the user builds something, which is what
# made this take three occurrences to pin down.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "iso-e2e.sh pins the root context before doing anything" {
	local script="${REPO_ROOT}/scripts/iso-e2e.sh"
	grep -q 'export HOME="${TUNAOS_ROOT_HOME:-/root}"' "$script"
	grep -q 'unset XDG_RUNTIME_DIR XDG_DATA_HOME XDG_CONFIG_HOME' "$script"
	# Guarded on being root: the same script run unprivileged must keep using
	# the caller's own environment.
	grep -B2 'export HOME="${TUNAOS_ROOT_HOME:-/root}"' "$script" |
		grep -q 'EUID -eq 0'
}

@test "the guard runs before the host-side podman probe it protects" {
	# Placed after the probe it would be decorative. This is the same
	# reachability trap as the umotd guard, which sat after an early exit and
	# silently never ran on Arch.
	local script="${REPO_ROOT}/scripts/iso-e2e.sh"
	local guard probe
	guard=$(grep -n 'unset XDG_RUNTIME_DIR XDG_DATA_HOME XDG_CONFIG_HOME' "$script" | head -1 | cut -d: -f1)
	probe=$(grep -nE '^[^#]*\bpodman image exists\b' "$script" | head -1 | cut -d: -f1)
	[ -n "$guard" ]
	[ -n "$probe" ]
	[ "$guard" -lt "$probe" ]
}

@test "every root-context script that runs podman pins the same variables" {
	# build-iso-tacklebox.sh already did; iso-e2e.sh needed its own copy, the
	# same way live-overlay.yml needed its own copy of the HOME pin.
	local s
	for s in iso-e2e build-iso-tacklebox; do
		grep -q 'XDG_RUNTIME_DIR' "${REPO_ROOT}/scripts/${s}.sh"
	done
}

@test "the guard actually stops podman from using the caller's runtime dir" {
	# Execute the block rather than grepping it: extract it, run it as root
	# would, and confirm the variables are gone from the resulting environment.
	local script="${REPO_ROOT}/scripts/iso-e2e.sh"
	local block="${BATS_TEST_TMPDIR}/guard.sh"
	# EUID is readonly in bash, so the `if` cannot be faked -- extract the
	# BODY and run that. What is under test is the body's effect on the
	# environment, not bash's ability to compare integers.
	sed -n '/^if \[\[ \$EUID -eq 0 \]\]; then$/,/^fi$/p' "$script" |
		sed '1d;$d' >"$block"
	[ -s "$block" ]
	run env XDG_RUNTIME_DIR=/run/user/1000 XDG_DATA_HOME=/home/u/.local/share \
		HOME=/home/u bash -c "
			. '$block'
			echo \"HOME=\$HOME RUNTIME=\${XDG_RUNTIME_DIR:-<unset>} DATA=\${XDG_DATA_HOME:-<unset>}\""
	[ "$status" -eq 0 ]
	[[ "$output" == *"HOME=/root"* ]]
	[[ "$output" == *"RUNTIME=<unset>"* ]]
	[[ "$output" == *"DATA=<unset>"* ]]
}
