#!/bin/bash
# Free UID 1000 so a live ISO can be built from this image.
#
# tacklebox's CustomizeLive prepends its own embedded src/live/baseline.sh,
# which creates the live user with an unconditional `--uid 1000`. When the
# base image already has an account there, the ISO job dies before it produces
# anything:
#
#   >>> [customize] (1/2) baseline.sh
#   useradd: UID 1000 is not unique
#   Error: live customize for <cell>: ... exit status 4
#
# tunaOS fixed this in its OWN live-iso/common/src/customize-live.sh, by
# asking for 1000 only when it is free. That script runs as (2/2), after the
# baseline, and tacklebox offers no pre-baseline hook -- so the account has to
# be gone from the image itself.
#
# WHY THIS IS ITS OWN SCRIPT
#
# The removals first lived in 01-workarounds.sh. Only Containerfile.el10 and
# Containerfile.ubuntu run that script, so the Arch branch inside it could
# never execute and marlin's arm64 ISO kept failing on the exact message the
# branch was written to prevent (run 35194190546, job 105123809614). A fix in
# a file the failing base does not run is not a fix. This script takes no
# lib.sh distro flags and no build context, so ANY Containerfile can call it
# with one line.
#
# Removals are deliberately narrow. Only an account still carrying the stock
# name AND still at exactly UID 1000 is removed, so a base that renumbers it,
# one that drops it, or an operator who repurposed the name is left alone
# rather than silently altered.

set -euo pipefail
printf "::group:: === free-uid-1000 ===\n"

# name:where-it-comes-from. Both were read out of the real published layer,
# not assumed:
#   ubuntu:x:1000:1000:Ubuntu:/home/ubuntu:/bin/bash   docker.io/library/ubuntu
#   alarm:x:1000:1000::/home/alarm:/bin/bash           ghcr.io/tuna-os/archlinuxarm
#
# archlinuxarm keeps `alarm` on purpose ("alarm/root users stay (standard
# ALARM accounts)" in build-archlinuxarm-base.yml), which is right for a base
# image and wrong for an ISO built downstream of it. It is also why marlin
# fails on arm64 only: the x86_64 Arch base ships no such account.
for stock in "ubuntu:the stock cloud account" "alarm:the stock Arch Linux ARM account"; do
	account="${stock%%:*}"
	label="${stock#*:}"

	[[ "$(id -u "${account}" 2>/dev/null || echo -)" == "1000" ]] || continue

	echo "removing ${label} '${account}' (UID 1000)"
	# --remove deletes /home/<account>. bootc images make /home a symlink to
	# a var/home that can be empty in the container layer, so that half may
	# legitimately fail; the account removal is what has to succeed.
	userdel --remove "${account}" 2>/dev/null || userdel "${account}"

	# An if-block, not `A && B || C`: shellcheck's SC2015 is an INFO finding,
	# and tests/bats/test_build_scripts.bats runs shellcheck with only SC1091
	# excluded, so info findings fail the gate.
	if getent group "${account}" >/dev/null; then
		groupdel "${account}" 2>/dev/null || true
	fi

	# cloud-init's sudoers drop-in names the account just deleted, which
	# leaves a rule for a user that no longer exists. Removed only when it
	# actually mentions the account: on a base that repurposed the file for
	# something else, deleting it would revoke unrelated sudo.
	if grep -q "\\b${account}\\b" /etc/sudoers.d/90-cloud-init-users 2>/dev/null; then
		rm -f /etc/sudoers.d/90-cloud-init-users
	fi
done

# Not fatal, but named where it can be seen. If UID 1000 is still taken, the
# live ISO build WILL fail later in tacklebox's baseline.sh -- a message that
# arrives an hour downstream, in another repo's code, with no mention of this
# image. Whatever base ships an account at 1000 next, this says so in the
# build that causes it rather than in the ISO job.
if getent passwd 1000 >/dev/null; then
	echo "WARNING: UID 1000 is still taken; the live ISO build will fail:"
	getent passwd 1000
fi

printf "::endgroup::\n"
