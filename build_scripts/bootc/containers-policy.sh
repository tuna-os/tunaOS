#!/usr/bin/env bash
# containers-policy.sh — make sure /etc/containers/policy.json is one THIS
# image's skopeo can actually load.
#
# WHY THIS EXISTS
#
# gurnard:pantheon reached the install and died there:
#
#   + skopeo copy containers-storage:ghcr.io/tuna-os/gurnard:pantheon oci:...
#   level=fatal msg="Error loading trust policy: invalid policy in
#     \"/etc/containers/policy.json\": Unknown key \"keyPaths\""
#   fisherman: fatal: bootc install: exporting image to OCI layout
#
# The policy comes from projectbluefin/common's /system_files/shared, which
# every apt Containerfile COPYs. It pins sigstore requirements for the
# ghcr.io/ublue-os prefix, and `keyPaths` is a sigstoreSigned field added in
# containers/image 5.28 (skopeo 1.14). Ubuntu noble ships skopeo 1.13.3, which
# predates it; Debian trixie ships a newer one, which is why flounder:kde
# passes the identical COPY and gurnard does not.
#
# A policy that fails to parse does not fail open OR closed — skopeo refuses
# EVERY operation, so nothing on the image can copy an image at all. There is
# therefore no verification to preserve here: dropping the entries this skopeo
# cannot read strictly increases what works and weakens no check that was
# running. The `default` requirement is never touched.
#
# The transports block is dropped WHOLE rather than surgically, because which
# key is unsupported depends on the skopeo version and guessing wrong leaves an
# equally unloadable file. What was removed is printed, loudly, so a reader of
# the build log sees the trade rather than discovering it later.
#
# If the policy still will not load afterwards, this fails the build. A silent
# fallback here is how the problem reached a 20-minute matrix cell in the first
# place.
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

# openSUSE's base ships no policy at all and bootc install fails with "no
# policy.json file found". Same file, same failure mode, so it is handled here
# too rather than inline in one Containerfile.
if [[ ! -s "$POLICY" ]]; then
	echo "no ${POLICY} — writing a permissive default"
	mkdir -p "$(dirname "$POLICY")"
	printf '{ "default": [ { "type": "insecureAcceptAnything" } ] }\n' >"$POLICY"
fi

# Does skopeo load it? `copy` reads the policy before it touches either end, so
# a copy between two paths that do not exist reports the policy error and
# nothing else. Offline, no side effects, and independent of which key is the
# unsupported one.
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
echo "         Every skopeo operation on this image fails until it is fixed," >&2
echo "         including the bootc install path. Dropping its transports block:" >&2
if command -v jq >/dev/null 2>&1; then
	jq -r '.transports // {} | keys[]?' "$POLICY" 2>/dev/null |
		sed 's/^/           transport: /' >&2 || true
	tmp="$(mktemp)"
	jq 'del(.transports)' "$POLICY" >"$tmp" 2>/dev/null && mv "$tmp" "$POLICY" || {
		rm -f "$tmp"
		printf '{ "default": [ { "type": "insecureAcceptAnything" } ] }\n' >"$POLICY"
	}
else
	echo "           (no jq — replacing the whole policy with the default)" >&2
	printf '{ "default": [ { "type": "insecureAcceptAnything" } ] }\n' >"$POLICY"
fi

if ! policy_loads; then
	echo "ERROR: ${POLICY} still does not load after dropping transports." >&2
	cat "$POLICY" >&2
	exit 1
fi
echo "policy.json now loads."
cat "$POLICY"
printf "::endgroup::\n"
