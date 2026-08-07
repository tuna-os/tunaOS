#!/usr/bin/env bats
# tunaos-live-ready.service emits the guest's addresses and TCP listeners.
#
# This is the fact that explained a failure four LUKS cells had in common.
# grouper:kde reported an EMPTY address list beside a healthy "0.0.0.0:22"
# listener, which is the entire mechanism behind "Connection timed out during
# banner exchange": QEMU user-mode networking accepts the connection host-side
# and then has no guest address to deliver it to. sshd was never at fault.
#
# The diagnostic lives in THIS unit, not in e2e-runtime-checks.sh where it
# started. That script runs from tunaos-desktop-contract.service on
# graphical.target, so grouper:xfce — which fails in exactly this way — never
# ran it and its serial recorded nothing at all. A diagnostic that goes quiet
# on the worst failures is worse than none, because its silence reads as
# "nothing to report". This unit is WantedBy=multi-user.target and fired even
# in that cell.
#
# There are two copies of the unit and they have ALREADY drifted once (they
# disagree about how they reach the serial console). So the ExecStart sets are
# pinned in step here rather than trusted to review.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
LIVE_UNIT="${REPO_ROOT}/live-iso/common/src/tunaos-live-ready.service"
IMAGE_UNIT="${REPO_ROOT}/system_files/usr/lib/systemd/system/tunaos-live-ready.service"

# The ExecStart command lines, with systemd's `\\` -> `\` unescaping applied,
# so what we execute is what the shell would actually receive.
net_commands() {
	sed -n 's/^ExecStart=\/bin\/sh -c //p' "$1" |
		grep 'TUNAOS_LIVE_NET' |
		sed 's/\\\\/\\/g'
}

# Run one extracted command with PATH set to $2, stripping the surrounding
# single quotes systemd would have removed.
run_cmd() {
	local cmd="$1" path="$2"
	cmd="${cmd#\'}"
	cmd="${cmd%\'}"
	PATH="$path" sh -c "$cmd"
}

setup() {
	STUBS="$BATS_TEST_TMPDIR/stubs"
	mkdir -p "$STUBS"
	# Keep the coreutils the pipelines need reachable.
	REAL_PATH="$STUBS:/usr/bin:/bin"

	# A PATH carrying exactly the tools the pipelines need and nothing else, so
	# the "tool is missing" case is produced deliberately rather than depending
	# on this machine happening to lack ip(8)/ss(8). Without linking sh itself
	# the test fails on `sh: command not found`, which proves nothing about the
	# unit.
	MINIMAL="$BATS_TEST_TMPDIR/minimal"
	mkdir -p "$MINIMAL"
	local t src
	for t in sh tr cut sort; do
		src="$(command -v "$t")"
		[ -n "$src" ] || skip "$t not available to build the minimal PATH"
		ln -sf "$src" "$MINIMAL/$t"
	done
}

@test "both unit copies emit the TUNAOS_LIVE_NET marker" {
	run net_commands "$LIVE_UNIT"
	[ "$status" -eq 0 ]
	[ -n "$output" ]
	run net_commands "$IMAGE_UNIT"
	[ "$status" -eq 0 ]
	[ -n "$output" ]
}

# The two files legitimately differ on StandardOutput/TTYPath. They must NOT
# differ on what they emit: that is how a marker ends up present on one boot
# path and missing on the other, which is the failure this whole diagnostic
# exists to avoid.
@test "the two copies emit the identical diagnostic commands" {
	local live image
	live="$(net_commands "$LIVE_UNIT")"
	image="$(net_commands "$IMAGE_UNIT")"
	[ "$live" = "$image" ]
}

@test "reports the guest's address and listeners when ip and ss exist" {
	cat >"$STUBS/ip" <<-'EOF'
		#!/bin/sh
		echo "2: enp0s3    inet 10.0.2.15/24 brd 10.0.2.255 scope global enp0s3"
	EOF
	cat >"$STUBS/ss" <<-'EOF'
		#!/bin/sh
		echo "LISTEN 0      128          0.0.0.0:22        0.0.0.0:*"
	EOF
	chmod +x "$STUBS/ip" "$STUBS/ss"

	local out=""
	while IFS= read -r c; do
		out="${out}$(run_cmd "$c" "$REAL_PATH")"$'\n'
	done < <(net_commands "$LIVE_UNIT")

	[[ "$out" == *"TUNAOS_LIVE_NET ipv4="* ]]
	[[ "$out" == *"10.0.2.15/24"* ]]
	[[ "$out" == *"TUNAOS_LIVE_NET listeners="* ]]
	[[ "$out" == *"0.0.0.0:22"* ]]
}

# The failing signature itself: an address list that is empty while a listener
# is present. This is what grouper:kde actually produced, and the assertion
# that the emission can express it at all.
@test "an address-less guest renders as an empty ipv4 list, not a missing line" {
	cat >"$STUBS/ip" <<-'EOF'
		#!/bin/sh
		exit 0
	EOF
	cat >"$STUBS/ss" <<-'EOF'
		#!/bin/sh
		echo "LISTEN 0      128          0.0.0.0:22        0.0.0.0:*"
	EOF
	chmod +x "$STUBS/ip" "$STUBS/ss"

	local out=""
	while IFS= read -r c; do
		out="${out}$(run_cmd "$c" "$REAL_PATH")"$'\n'
	done < <(net_commands "$LIVE_UNIT")

	# The line is still emitted — silence would be indistinguishable from the
	# unit not having run, which is the ambiguity that cost us grouper:xfce.
	[[ "$out" == *"TUNAOS_LIVE_NET ipv4="* ]]
	[[ "$out" == *"0.0.0.0:22"* ]]
}

# "nothing is listening" is the conclusion these lines exist to support, so
# saying it because the tool was absent would be a wrong diagnosis stated
# confidently.
@test "missing ip(8)/ss(8) say so rather than rendering empty" {
	# Positive control, and not a formality. The sibling test file for
	# e2e-runtime-checks.sh had this exact assertion pass vacuously: its PATH
	# included /usr/bin, so `command -v ss` found the host's real iproute2 and
	# the else-branch never ran. It passed on hosts without iproute2 and failed
	# on GitHub's runners, which have it.
	#
	# The mirror-image vacuity is just as easy: a PATH that resolves NOTHING
	# would make every `command -v` fail and satisfy both assertions for the
	# wrong reason. Proving a planted utility IS found on $MINIMAL, while ip and
	# ss are not, makes the two absences below a real negative.
	PATH="$MINIMAL" sh -c 'command -v tr' >/dev/null
	! PATH="$MINIMAL" sh -c 'command -v ip' >/dev/null 2>&1
	! PATH="$MINIMAL" sh -c 'command -v ss' >/dev/null 2>&1

	local out=""
	while IFS= read -r c; do
		out="${out}$(run_cmd "$c" "$MINIMAL")"$'\n'
	done < <(net_commands "$LIVE_UNIT")

	[[ "$out" == *"ip-unavailable"* ]]
	[[ "$out" == *"ss-unavailable"* ]]
}
