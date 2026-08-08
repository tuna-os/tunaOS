#!/usr/bin/env bats
# What run_install() decides once FISHERMAN_OVERRIDE is installed before the
# fisherman presence check (see test_fisherman_override_order.bats for the
# ordering itself, and why it moved).
#
# Installing first makes the guppy cells reachable, and it costs the generic
# path its trigger if the two are not separated. The old sequence was:
#
#   image has no fisherman?  ->  TBOX_E2E_IMAGE set?  ->  plain bootc install
#
# With the override landing first, "image has no fisherman" is never true
# afterwards, so a caller-named generic image would silently take the fisherman
# path instead — and recipe_image there resolves a *tunaOS* ref from
# VARIANT/FLAVOR, i.e. it would install something else entirely. So the image
# is probed once BEFORE the override, and that probe is what the generic-path
# decision reads.
#
# The block sits ~1650 lines into a function that needs QEMU, a guest and a
# real ssh, so these tests lift it out and run it against a stub guest: an ssh
# that answers the presence probe according to what the "image" shipped, and
# records what got installed onto it.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/iso-e2e.sh"

# The whole decision region, verbatim: from the comment that opens it down to
# (not including) the smoke-check section that follows. Anchored on text that
# predates this change, so reverting the code under test leaves a block that
# still extracts and still runs — otherwise every case here would "fail" on a
# mutant merely by finding nothing.
extract_block() {
	awk '/Generic \(non-tunaOS\) images ship no fisherman/{f=1} /Pre-install evidence/{f=0} f{print}' "$SCRIPT"
}

# Run that region against a stub guest.
#   $1 = 1 if the live image ships /usr/local/bin/fisherman, 0 if not
# Env: FISHERMAN_OVERRIDE, TBOX_E2E_IMAGE are read by the code under test.
run_block() {
	local has="$1" block
	block="$(extract_block)"
	[ -n "$block" ] || {
		echo "could not extract the fisherman decision block" >&2
		return 99
	}
	bash -c "
		set -uo pipefail
		HAS=$has
		LANDED=0
		# 0 simulates an install that reports success but leaves nothing
		# usable behind, clobbering whatever the image had — the only way to
		# reach the failure path with a fisherman-carrying image.
		LANDS=${OVERRIDE_LANDS:-1}
		GUEST_HOME=/home/liveuser
		GUEST_SCP_DEST=guest
		VARIANT=guppy
		FLAVOR=xfce
		# A guest, modelled: the probe answers for the image until something
		# installs a binary onto it, and then it answers for that.
		_ssh() {
			case \"\$*\" in
				*'command -v /usr/local/bin/fisherman'*)
					[[ \$HAS -eq 1 || \$LANDED -eq 1 ]] && return 0 || return 1 ;;
				*mkdir*) echo \"MKDIR \$*\" ;;
				# Any spelling of the install, not just the current flags:
				# a stub that only recognises today's exact command would
				# quietly model 'the binary never landed' if the flags change.
				*install*fisherman-override*/usr/local/bin/fisherman*)
					if [[ \$LANDS -eq 1 ]]; then LANDED=1; else HAS=0; fi
					echo \"INSTALLED \$*\" ;;
				*) : ;;
			esac
			return 0
		}
		_scp() { echo \"SCP \$*\"; }
		ssh_cmd=(_ssh)
		scp_cmd=(_scp)
		run_install_generic() { echo 'GENERIC BOOTC PATH'; return 0; }
		_block() {
$block
			echo 'REACHED THE FISHERMAN PATH'
		}
		_block
	"
}

override_file() {
	local f="$BATS_TEST_TMPDIR/fisherman-bin"
	printf '#!/bin/sh\n' >"$f"
	echo "$f"
}

@test "image without fisherman + override: reaches the fisherman path" {
	FISHERMAN_OVERRIDE="$(override_file)" TBOX_E2E_IMAGE= run run_block 0
	[ "$status" -eq 0 ]
	[[ "$output" == *"REACHED THE FISHERMAN PATH"* ]]
	[[ "$output" == *"INSTALLED"* ]]
	[[ "$output" != *"ERROR: fisherman not found on live image"* ]]
}

@test "image without fisherman + TBOX_E2E_IMAGE: the generic path still wins" {
	# The regression the pre-override probe exists to prevent. An override is
	# present too — the LUKS workflow always sets one — and it must not decide
	# this.
	FISHERMAN_OVERRIDE="$(override_file)" TBOX_E2E_IMAGE="quay.io/example/generic:latest" \
		run run_block 0
	[ "$status" -eq 0 ]
	[[ "$output" == *"GENERIC BOOTC PATH"* ]]
	[[ "$output" != *"REACHED THE FISHERMAN PATH"* ]]
	# And nothing was pushed onto a guest that is about to be installed by bootc.
	[[ "$output" != *"INSTALLED"* ]]
}

@test "image with fisherman + TBOX_E2E_IMAGE: unchanged, override applies" {
	# TBOX_E2E_IMAGE only ever diverted images that shipped no fisherman; a
	# tunaOS image that has one keeps the fisherman path and the override.
	FISHERMAN_OVERRIDE="$(override_file)" TBOX_E2E_IMAGE="quay.io/example/generic:latest" \
		run run_block 1
	[ "$status" -eq 0 ]
	[[ "$output" == *"REACHED THE FISHERMAN PATH"* ]]
	[[ "$output" == *"INSTALLED"* ]]
	[[ "$output" != *"GENERIC BOOTC PATH"* ]]
}

@test "an image shipping no fisherman is reported as a warning" {
	# The flatpak that carries fisherman carries the installer GUI, so this
	# also means the ISO has no installer a human could use. The cell proceeds
	# on the caller's binary, but must not imply it covered that.
	FISHERMAN_OVERRIDE="$(override_file)" TBOX_E2E_IMAGE= run run_block 0
	[[ "$output" == *"::warning::"* ]]
	[[ "$output" == *"installer flatpak is missing"* ]]
}

@test "an image that ships fisherman produces no such warning" {
	FISHERMAN_OVERRIDE="$(override_file)" TBOX_E2E_IMAGE= run run_block 1
	[[ "$output" != *"::warning::"* ]]
}

@test "no fisherman and no usable override: still the hard error" {
	FISHERMAN_OVERRIDE= TBOX_E2E_IMAGE= run run_block 0
	[ "$status" -eq 3 ]
	[[ "$output" == *"ERROR: fisherman not found on live image"* ]]
	[[ "$output" != *"REACHED THE FISHERMAN PATH"* ]]
}

@test "the failure still names TBOX_E2E_IMAGE when the caller set no image" {
	FISHERMAN_OVERRIDE= TBOX_E2E_IMAGE= run run_block 0
	[[ "$output" == *"TBOX_E2E_IMAGE is unset"* ]]
}

@test "the failure does not claim TBOX_E2E_IMAGE is unset when it is set" {
	# Now reachable only one way: the image had a fisherman and the override
	# clobbered it. With no fisherman and TBOX_E2E_IMAGE set, the generic path
	# takes the run instead — so printing "TBOX_E2E_IMAGE is unset" here is
	# simply false, in the message that gets read during triage.
	OVERRIDE_LANDS=0 FISHERMAN_OVERRIDE="$(override_file)" \
		TBOX_E2E_IMAGE="quay.io/example/generic:latest" run run_block 1
	[ "$status" -eq 3 ]
	[[ "$output" == *"ERROR: fisherman not found on live image"* ]]
	[[ "$output" != *"TBOX_E2E_IMAGE is unset"* ]]
	[[ "$output" == *"did not land"* ]]
}

@test "the override install creates /usr/local/bin before writing into it" {
	# `install -D` (and mkdir -p) refuse to create *through* a dangling
	# symlink, and on the ostree layout /usr/local points at a ../var/usrlocal
	# the image does not contain. That never mattered while the override only
	# replaced an existing binary; on an image that shipped none, it does.
	FISHERMAN_OVERRIDE="$(override_file)" TBOX_E2E_IMAGE= run run_block 0
	[ "$status" -eq 0 ]
	[[ "$output" == *"MKDIR"* ]]
	[[ "$output" == *'readlink -m /usr/local/bin'* ]]
	# mkdir first, then install.
	local mk in
	mk=$(printf '%s\n' "$output" | grep -n MKDIR | head -1 | cut -d: -f1)
	in=$(printf '%s\n' "$output" | grep -n INSTALLED | head -1 | cut -d: -f1)
	[ "$mk" -lt "$in" ]
}
