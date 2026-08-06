#!/usr/bin/env bash
# containers-policy.sh — make sure /etc/containers/policy.json is one THIS
# image's skopeo can actually load, WITHOUT changing what it permits.
#
# WHY THIS EXISTS
#
# gurnard:pantheon reached the install and died there:
#
#   + skopeo copy containers-storage:ghcr.io/tuna-os/gurnard:pantheon oci:...
#   level=fatal msg="Error loading trust policy: invalid policy in
#     \"/etc/containers/policy.json\": Unknown key \"keyPaths\""
#
# The policy comes from projectbluefin/common's /system_files/shared, which
# every apt Containerfile COPYs. `keyPaths` (the plural, array form of a
# sigstore key reference) landed in containers/image 5.28 = skopeo 1.14.
# Ubuntu noble ships skopeo 1.13.3 and rejects the whole file; Debian trixie's
# is newer, which is the only reason flounder:kde passes the identical COPY.
#
# WHAT THE POLICY ACTUALLY CONTAINS — read off the image, not assumed:
#
#   default:                      reject
#   transports.docker:            RedHat GPG requirements, a sigstoreSigned
#                                 entry for quay.io/toolbx-images using the
#                                 SINGULAR keyPath, a sigstoreSigned entry for
#                                 ghcr.io/ublue-os using the PLURAL keyPaths,
#                                 and "" -> insecureAcceptAnything
#   containers-storage, oci, dir,
#   oci-archive, docker-archive,
#   docker-daemon, atomic,
#   tarball:                      "" -> insecureAcceptAnything
#
# So the default REJECTS and the transports block carries every permit —
# including the containers-storage one the bootc install path depends on.
# Deleting that block, which an earlier version of this script did, leaves a
# policy that parses and refuses everything:
#
#   level=fatal msg="Source image rejected: Running image
#     containers-storage:[...]ghcr.io/tuna-os/gurnard:pantheon@... is rejected
#     by policy."
#
# Exactly one requirement object in the file is unparseable, so the repair is
# correspondingly small, and it is applied as a ladder of decreasing fidelity
# with every step logged:
#
#   1. Rewrite `keyPaths: [a, b]` to `keyPath: a`. Old skopeo understands the
#      singular form, so sigstore verification SURVIVES — the only loss is the
#      backup key. Nothing is permitted that was not permitted before.
#   2. If it still will not load, drop signature-requiring objects
#      (sigstoreSigned / signedBy) and any scope left empty. Permits and the
#      default are never touched, so this loosens verification for those
#      scopes and nothing else.
#   3. If it still will not load, FAIL THE BUILD. Falling back to
#      insecureAcceptAnything here would turn a reject-by-default policy into
#      an accept-everything one on the strength of a guess, which is precisely
#      the reasoning that produced step 2's bug.
#
# A missing policy is a different problem with a different answer: openSUSE's
# base ships none and bootc install fails with "no policy.json file found".
# That one gets the permissive default, as it always has.
#
# USAGE
#   containers-policy.sh
#
# TUNAOS_SYSROOT prefixes every path (tests); TUNAOS_SKOPEO names the binary.

set -euo pipefail
printf "::group:: === containers policy ===\n"

R="${TUNAOS_SYSROOT:-}"
SKOPEO="${TUNAOS_SKOPEO:-skopeo}"
POLICY="${R}/etc/containers/policy.json"

if ! command -v "$SKOPEO" >/dev/null 2>&1; then
	echo "note: no skopeo on this image — nothing to validate"
	printf "::endgroup::\n"
	exit 0
fi

if [[ ! -s "$POLICY" ]]; then
	echo "no ${POLICY} — writing a permissive default"
	mkdir -p "$(dirname "$POLICY")"
	printf '{ "default": [ { "type": "insecureAcceptAnything" } ] }\n' >"$POLICY"
fi

# `copy` reads the policy before it touches either end, so a copy between two
# paths that do not exist reports the policy error and nothing else. Offline,
# no side effects, and independent of WHICH key is the unsupported one.
policy_loads() {
	local out
	out="$("$SKOPEO" copy "dir:${R}/nonexistent-policy-probe-src" \
		"dir:${R}/nonexistent-policy-probe-dst" 2>&1 || true)"
	! grep -q 'Error loading trust policy' <<<"$out"
}

if policy_loads; then
	echo "policy.json loads with $("$SKOPEO" --version 2>/dev/null || echo skopeo)"
	printf "::endgroup::\n"
	exit 0
fi

echo "WARNING: ${POLICY} cannot be parsed by this image's skopeo." >&2
echo "         Until it can, EVERY skopeo operation on this image fails," >&2
echo "         including the one bootc install uses." >&2

if ! command -v jq >/dev/null 2>&1; then
	echo "ERROR: no jq available to repair the policy." >&2
	exit 1
fi

apply() {
	local filter="$1" label="$2" tmp
	tmp="$(mktemp)"
	if jq "$filter" "$POLICY" >"$tmp" 2>/dev/null; then
		mv "$tmp" "$POLICY"
		echo "         ${label}" >&2
	else
		rm -f "$tmp"
	fi
}

# Step 1 — plural key reference to singular. Keeps the requirement, and with
# it the verification; loses only the alternate key.
apply 'walk(if type == "object" and has("keyPaths") and (has("keyPath") | not)
             then (. + {keyPath: .keyPaths[0]} | del(.keyPaths))
             else . end)' \
	"rewrote keyPaths[] to keyPath (verification kept, backup key dropped)"

if policy_loads; then
	echo "policy.json now loads."
	cat "$POLICY"
	printf "::endgroup::\n"
	exit 0
fi

# Step 2 — give up on the signature requirements themselves, but never on the
# permits or the default.
apply '.transports |= with_entries(
         .value |= with_entries(
           .value |= map(select(.type != "sigstoreSigned" and .type != "signedBy"))
         )
         | .value |= with_entries(select(.value | length > 0))
       )
       | .transports |= with_entries(select(.value | length > 0))' \
	"dropped sigstoreSigned/signedBy requirements; permits and default untouched"

if ! policy_loads; then
	echo "ERROR: ${POLICY} still does not load. Not weakening it further —" >&2
	echo "       an accept-everything fallback on a reject-by-default policy" >&2
	echo "       is not a repair." >&2
	cat "$POLICY" >&2
	exit 1
fi
echo "policy.json now loads."
cat "$POLICY"
printf "::endgroup::\n"
