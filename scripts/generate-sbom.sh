#!/usr/bin/env bash
# Generate an SPDX SBOM for a just-built image with syft, under a memory cap.
#
# Extracted verbatim from the `Generate SBOM` step of
# .github/workflows/reusable-build-image.yml (tunaOS#1987) so that the cap
# arithmetic, the floor clamp and the systemd-run fallback are reachable by
# tests/bats/test_generate_sbom.bats instead of only by a nightly build.
# Behaviour is unchanged; the caller still supplies every input through the
# environment and still decides whether a failure here is fatal.
#
# The workflow step still inlines this body rather than calling the file:
# swapping it for `run: scripts/generate-sbom.sh` needs the `workflows`
# permission, which the agent App does not hold. Until a maintainer makes
# that one-line change the two copies are kept identical by the drift guard
# in tests/bats/test_generate_sbom.bats, so the tests below are testing the
# code CI actually runs.
#
# Required environment:
#   SYFT_CMD                  path to (or name of) the syft binary
#   IMAGE_REGISTRY            registry host for the image to scan
#   IMAGE_NAME                image name
#   DEFAULT_TAG               tag prefix
#   SAFE_PLATFORM             platform suffix, e.g. linux_amd64
#   SYFT_MEMORY_RESERVE_MIB   MiB left for everything that is not syft
#   SYFT_MEMORY_FLOOR_MIB     lower bound on the cgroup cap
#
# Writes sbom-${IMAGE_NAME}-${DEFAULT_TAG}-${SAFE_PLATFORM}.spdx.json to CWD.
set -euo pipefail
IMAGE="${IMAGE_REGISTRY}/${IMAGE_NAME}:${DEFAULT_TAG}-${SAFE_PLATFORM}"
OUT="sbom-${IMAGE_NAME}-${DEFAULT_TAG}-${SAFE_PLATFORM}.spdx.json"

# Two bounds, because the two previous attempts each caught only one
# failure mode and the scan has now escaped both:
#
#   timeout-minutes: 20   enforced by the runner AGENT -- useless
#                         precisely when the agent is the casualty.
#                         On 08-14 (#1567) the step overran it by 51
#                         minutes and uploaded no logs at all.
#   timeout 18m           wall-clock, added by #1572. On the 08-16
#                         nightly the runner died at 7m56s, well
#                         inside it: "The runner has received a
#                         shutdown signal."
#
# Time was never the fault. Memory is: GOMEMLIMIT is advisory, so a
# large enough file inventory sails past 3GiB and takes the agent
# down with it. A cgroup cap makes the kernel kill syft instead --
# a real exit code, with logs, while the agent is still healthy.
# The wall-clock bound stays for the orthogonal case of a scan that
# is slow rather than hungry.
syft_cmd=( timeout --kill-after=30s 18m
           "$SYFT_CMD" "$IMAGE" --scope squashed -o spdx-json="$OUT" )

# Size the cap off the box we actually landed on, and say so, so a
# future exit 137 can be read against a real number instead of an
# assumption about hosted-runner sizing (#1567 recorded 7 GB; that
# is not what ubuntu-latest ships now, and the arm64 leg is a
# different image again).
mem_total_mib="$(free -m | awk '/^Mem:/ {print $2}')"
cap_mib=$(( mem_total_mib - SYFT_MEMORY_RESERVE_MIB ))
if [ "$cap_mib" -lt "$SYFT_MEMORY_FLOOR_MIB" ]; then
  cap_mib="$SYFT_MEMORY_FLOOR_MIB"
fi
echo "runner memory (MiB): total=${mem_total_mib} available=$(free -m | awk '/^Mem:/ {print $7}')"
echo "syft cgroup cap (MiB): ${cap_mib} (reserving ${SYFT_MEMORY_RESERVE_MIB} for the agent)"

if command -v systemd-run >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  sudo systemd-run --scope --quiet \
    --uid="$(id -u)" --gid="$(id -g)" \
    -p MemoryMax="${cap_mib}M" -p MemorySwapMax=0 \
    -- "${syft_cmd[@]}"
else
  # Never silently drop the guard: without it a hungry scan can
  # still take the agent, which is the failure this step exists to
  # stop being invisible.
  echo "::warning::systemd-run unavailable; syft is time-bounded but NOT memory-bounded"
  "${syft_cmd[@]}"
fi

jq -e '
  .spdxVersion | startswith("SPDX-")
' "$OUT" >/dev/null
jq -e '(.packages // []) | length > 0' "$OUT" >/dev/null
