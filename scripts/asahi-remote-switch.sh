#!/usr/bin/env bash
# scripts/asahi-remote-switch.sh — switch a live Asahi/bootc host to a new
# image over SSH, reboot it, and report whether the switch stuck.
#
# WHY THIS EXISTS (tunaOS#780)
#
# The only two ways to exercise a real m1n1/Apple-Silicon boot chain are a
# rented Scaleway Mac mini M2 Pro (Tier 2 — ephemeral, real per-hour billing)
# or a standing personal machine reachable over Tailscale (Tier 3 — James's
# M1 Air, "jamess-macbook-air"). Neither can be provisioned or enrolled from
# here: Tier 2 needs a funded Scaleway account, Tier 3 needs physical hands
# on a specific laptop. See docs/ASAHI-HARDWARE-TIERS.md for the full
# picture; this script is the one piece both tiers need in common — safely
# iterating `bootc switch` against whichever host is already up.
#
# ALWAYS DRIVEN FROM OUTSIDE THE TARGET, OVER SSH — NEVER LOCALLY
#
# This script reboots its target. A process cannot survive the reboot of the
# machine it is running on — a "run this locally on the box under test" mode
# would die the instant `systemctl reboot` fires, before it ever reached the
# post-reboot verification it exists to do. So there is deliberately no local
# mode: this always runs from a second machine (a GitHub-hosted runner, or
# any other host with SSH reach) against ASAHI_HW_HOST over the network. For
# Tier 2 that also means the Scaleway rental never needs to be registered as
# a GitHub Actions self-hosted runner at all — a scoped SSH connection out to
# it is a smaller blast radius than letting arbitrary workflow code execute
# on it, and it is the rental's whole reason to exist for this one job, not a
# standing credential.
#
# THE RULE THIS SCRIPT EXISTS TO ENFORCE
#
# Neither hardware tier has a keyboard next to it during a test run. A Mac
# whose bootloader payload (<ESP>/m1n1/boot.bin) gets rewritten with garbage
# has no recovery path without physical access — "brick risk, no physical
# access" is the exact phrase from the issue that created this tier. This
# repo already ships a systemd oneshot, asahi-bootbin-sync.service
# (build_scripts/asahi/install-bootbin-sync.sh), that rewrites boot.bin on
# EVERY boot when it detects the running kernel/DTB/m1n1 content changed —
# correct behaviour on a machine someone can walk over to, actively
# dangerous on one nobody can. So, before ever touching bootc:
#
#   1. asahi-bootbin-sync.service is masked, unconditionally, every run.
#      Masking a unit that does not exist yet (a fresh Fedora Asahi Remix
#      install, before its first TunaOS `bootc switch`) is a harmless no-op —
#      systemd creates the mask symlink regardless, so there is nothing to
#      special-case for "first switch on this host" vs. "hundredth".
#   2. Every command this script is about to run remotely is checked against
#      DANGEROUS_PATTERNS before it is sent — belt-and-suspenders against a
#      future edit accidentally reintroducing a firmware-writing call even
#      if the mask above were somehow bypassed.
#
# WHAT "SUCCESS" ACTUALLY MEANS HERE
#
# `bootc switch`/`bootc upgrade` stage a new deployment; they do not prove it
# boots. bootc's own boot-counting mechanism is what decides that — if the
# staged deployment never reaches its "boot complete" confirmation within the
# configured number of tries, the bootloader falls back to the previous
# deployment on its own. (The issue calls this "greenboot auto-rollback";
# TunaOS does not ship the literal greenboot package, bootc's own mechanism
# is what is actually doing the work, and the fallback is a real distinction
# worth keeping — see the exit codes below.) This script does not implement
# any recovery logic itself — it only switches, reboots, waits, and reports
# which of bootc's own outcomes happened.
#
# USAGE
#
#   scripts/asahi-remote-switch.sh <image-ref>
#
#   # Tier 3 — over Tailscale to a standing machine:
#   ASAHI_HW_HOST=jamess-macbook-air.example.ts.net ASAHI_HW_USER=james \
#     scripts/asahi-remote-switch.sh ghcr.io/tuna-os/bonito:gnome-asahi
#
#   # Tier 2 — from a GitHub-hosted runner, over the rental's Tailscale/public
#   # address (set as a repo/environment secret once the rental exists):
#   ASAHI_HW_HOST="$ASAHI_HW_TIER2_HOST" ASAHI_HW_USER=root \
#     scripts/asahi-remote-switch.sh ghcr.io/tuna-os/bonito:gnome-asahi
#
# ENVIRONMENT
#
#   ASAHI_HW_HOST            Target hostname (Tailscale MagicDNS name, public
#                            IP, or any resolvable host). Required.
#   ASAHI_HW_USER             SSH user (default: root — bootc switch/reboot
#                            both need root either way; sudo prompting over a
#                            one-shot non-interactive SSH command is exactly
#                            the kind of thing that hangs silently in CI, so
#                            this script assumes the SSH user can run these
#                            commands directly rather than shelling out to
#                            sudo itself).
#   ASAHI_HW_SSH_PORT        default 22
#   ASAHI_HW_REBOOT_TIMEOUT  Seconds to wait for the host to come back after
#                            reboot before giving up (default 420 — Apple
#                            Silicon's boot chain through m1n1/U-Boot is not
#                            instant, and this has to cover a POST-to-SSH
#                            round trip, not just an OS boot).
#
# EXIT CODES
#
#   0  switched cleanly — the host rebooted into the requested image
#   1  generic failure (see stderr)
#   2  usage/precondition error (bad args, ssh not found)
#   3  confirmed rollback — bootc's own boot-counting reverted to the
#      previous deployment. The HOST SURVIVED; the candidate image is bad.
#      This is a genuinely useful, non-broken result, not a script failure.
#   4  host did not come back within ASAHI_HW_REBOOT_TIMEOUT — the one
#      outcome that needs a human (or the Tier 2 provisioning flow) to check
#      on the machine directly. bootc's rollback covers "new deployment
#      didn't confirm"; it does not cover "new deployment hung the boot
#      before bootc's own health check could even run".
#   5  could not reach the host before attempting anything (initial SSH
#      connectivity check failed) — nothing was touched.
#   77 missing local dependency (ssh)

set -euo pipefail

IMAGE="${1:?usage: asahi-remote-switch.sh <image-ref>}"

HOST="${ASAHI_HW_HOST:?set ASAHI_HW_HOST=<tailnet-or-resolvable-hostname> — see the script header for why there is no local mode}"
USER_NAME="${ASAHI_HW_USER:-root}"
SSH_PORT="${ASAHI_HW_SSH_PORT:-22}"
REBOOT_TIMEOUT="${ASAHI_HW_REBOOT_TIMEOUT:-420}"

if ! command -v ssh >/dev/null 2>&1; then
	echo "ERROR: ssh not found on PATH." >&2
	exit 77
fi

# accept-new (not StrictHostKeyChecking=no): unlike iso-e2e.sh's throwaway
# QEMU guests, these are real, persistent, repeatedly-reconnected-to hosts —
# trust-on-first-use and then actually verify on every later connection is
# the right tradeoff here, not "never verify".
SSH_OPTS=(
	-o StrictHostKeyChecking=accept-new
	-o ConnectTimeout=10
	-o BatchMode=yes
	-p "$SSH_PORT"
)

# Patterns that must never appear in a command this script sends, on this
# host or any future copy-paste of it. update-m1n1 and asahi-fwupdate are the
# real m1n1/firmware-payload writers on Asahi userspace; m1n1-installer is the
# lower-level tool they wrap; a raw write under /boot/efi (where the ESP is
# mounted) is the generic catch-all for "something is about to dd/cp onto the
# boot partition directly, bypassing all of the above." See the module-level
# comment for why this class of command is unrecoverable on either hardware
# tier.
DANGEROUS_PATTERNS='update-m1n1|asahi-fwupdate|m1n1-installer|/boot/efi'

assert_safe_command() {
	local cmd="$1"
	if grep -qE "$DANGEROUS_PATTERNS" <<<"$cmd"; then
		echo "ERROR: refusing to run a command that touches m1n1/firmware on a hardware-tier host: $cmd" >&2
		echo "       This class of command is unrecoverable without physical access — see" >&2
		echo "       docs/ASAHI-HARDWARE-TIERS.md. If this really is intentional, it does not" >&2
		echo "       belong in this script; run it by hand, deliberately, watching the console." >&2
		exit 1
	fi
}

# run <cmd-string>: execute one command on the target over SSH, after the
# safety check above. Always a single quoted string (not "$@") so the safety
# check sees exactly what will run, including any shell operators.
run() {
	local cmd="$1"
	assert_safe_command "$cmd"
	ssh "${SSH_OPTS[@]}" "${USER_NAME}@${HOST}" -- "$cmd"
}

# Same as run(), but never fails the script — for steps that are fine to no-op
# (masking a unit that may not exist yet on a fresh, pre-first-switch host).
run_best_effort() {
	run "$1" || true
}

ssh_reachable() {
	ssh "${SSH_OPTS[@]}" -o ConnectTimeout=5 "${USER_NAME}@${HOST}" -- true 2>/dev/null
}

echo "==> Target: ${USER_NAME}@${HOST}:${SSH_PORT}"

if ! ssh_reachable; then
	echo "ERROR: could not reach the host before attempting anything. Nothing was touched." >&2
	exit 5
fi

echo "==> Masking asahi-bootbin-sync.service (idempotent — safe if the unit does not exist yet)"
run_best_effort "systemctl mask asahi-bootbin-sync.service"

echo "==> Recording the currently-booted deployment"
PRE_STATUS="$(run "bootc status" 2>/dev/null || true)"
PRE_BOOTED="$(grep -A1 '^Booted image' <<<"$PRE_STATUS" | grep -oE 'Image:.*|image:.*' | head -1 || true)"
echo "    pre-switch booted: ${PRE_BOOTED:-<could not determine>}"

echo "==> Switching to ${IMAGE}"
run "bootc switch --retain ${IMAGE@Q}"

STAGED_STATUS="$(run "bootc status" 2>/dev/null || true)"
echo "$STAGED_STATUS" | sed 's/^/    /'

echo "==> Rebooting"
# systemctl reboot drops the SSH connection by design — a nonzero exit from
# run() here is expected, not a failure.
run "systemctl reboot" || true

echo "==> Waiting up to ${REBOOT_TIMEOUT}s for the host to come back"
deadline=$(($(date +%s) + REBOOT_TIMEOUT))
# Give the host a moment to actually go down before polling for it to come
# back — otherwise the first few checks can hit the still-shutting-down old
# boot and report "reachable" before the reboot has even started.
sleep 10
came_back=0
while (($(date +%s) < deadline)); do
	if ssh_reachable; then
		came_back=1
		break
	fi
	sleep 5
done

if [[ "$came_back" -ne 1 ]]; then
	echo "ERROR: host did not come back within ${REBOOT_TIMEOUT}s." >&2
	echo "       This needs a human (or the Tier 2 provisioning flow) to check on the machine" >&2
	echo "       directly — bootc's boot-counting rollback covers a deployment that fails to" >&2
	echo "       confirm, not one that hangs the boot before that check can run." >&2
	exit 4
fi

echo "==> Host is back. Confirming what actually booted."
# Re-mask on every run, not just before the switch: if the reboot landed on
# a TunaOS image for the first time, THIS is the first boot where the unit
# exists at all, and it runs before this script gets another chance to.
run_best_effort "systemctl mask asahi-bootbin-sync.service"

POST_STATUS="$(run "bootc status" 2>/dev/null || true)"
echo "$POST_STATUS" | sed 's/^/    /'
POST_BOOTED="$(grep -A1 '^Booted image' <<<"$POST_STATUS" | grep -oE 'Image:.*|image:.*' | head -1 || true)"

if grep -qF "$IMAGE" <<<"$POST_BOOTED"; then
	echo "==> SUCCESS: booted ${IMAGE}"
	exit 0
elif [[ -n "$PRE_BOOTED" && "$POST_BOOTED" == "$PRE_BOOTED" ]]; then
	echo "==> ROLLED BACK: bootc reverted to the pre-switch deployment on its own." >&2
	echo "    The host survived. ${IMAGE} did not confirm and is the thing to fix, not this run." >&2
	exit 3
else
	echo "==> UNEXPECTED: booted image does not match the target or the pre-switch state." >&2
	echo "    pre-switch:  ${PRE_BOOTED:-<unknown>}" >&2
	echo "    post-reboot: ${POST_BOOTED:-<unknown>}" >&2
	exit 1
fi
