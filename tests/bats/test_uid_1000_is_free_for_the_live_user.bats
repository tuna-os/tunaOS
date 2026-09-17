#!/usr/bin/env bats
# UID 1000 must be free in every image a live ISO is built from.
#
# tacklebox's embedded live baseline creates the live user with an
# unconditional `--uid 1000`. If the base image already has an account there,
# the ISO job dies before producing anything:
#
#   >>> [customize] (1/2) baseline.sh
#   useradd: UID 1000 is not unique
#   Error: live customize for <cell>: ... exit status 4
#
# tunaOS fixed this for its OWN scripts in customize-live.sh (ask for 1000
# only when free), but that runs as script 2/2 — after the baseline — and
# tacklebox offers no pre-baseline hook. So the account has to be gone from
# the image.
#
# Two bases ship one. Both were read out of the real image, not assumed:
#
#   ubuntu:x:1000:1000:Ubuntu:/home/ubuntu:/bin/bash        (docker.io ubuntu)
#   alarm:x:1000:1000::/home/alarm:/bin/bash                (ghcr.io/tuna-os/archlinuxarm)
#
# The Arch ARM one is why marlin fails on arm64 and not amd64: the x86_64
# Arch base has no such account.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  WORKAROUNDS="${REPO_ROOT}/build_scripts/01-workarounds.sh"
}

@test "the stock Ubuntu cloud account is removed" {
  run grep -E 'id -u ubuntu' "$WORKAROUNDS"
  [ "$status" -eq 0 ]
  run grep -E 'userdel .*ubuntu' "$WORKAROUNDS"
  [ "$status" -eq 0 ]
}

@test "the stock Arch Linux ARM account is removed" {
  run grep -E 'id -u alarm' "$WORKAROUNDS"
  [ "$status" -eq 0 ]
  run grep -E 'userdel .*alarm' "$WORKAROUNDS"
  [ "$status" -eq 0 ]
}

# Both removals are narrow on purpose: a base that renumbers the account, or
# an operator who repurposed the name, must be left alone rather than silently
# altered. Assert the UID equality guard, not just the userdel.
@test "each removal is guarded on the account still being exactly 1000" {
  for u in ubuntu alarm; do
    run bash -c "grep -E '\"\\\$\\(id -u $u 2>/dev/null \\|\\| echo -\\)\" == \"1000\"' '$WORKAROUNDS'"
    [ "$status" -eq 0 ] || {
      echo "the $u removal is not guarded on UID 1000" >&2
      return 1
    }
  done
}

# The diagnostic used to live inside the Ubuntu branch, so the identical
# failure on Arch ARM was never reported and had to be traced back from an ISO
# job by hand. It must sit outside every per-base block, so the NEXT base that
# ships an account at 1000 says so in the build that causes it.
@test "the UID 1000 warning is not trapped inside one base's branch" {
  # The warning must not be indented — an indented copy is inside an if-block.
  run grep -E '^if getent passwd 1000' "$WORKAROUNDS"
  [ "$status" -eq 0 ]
  run grep -E '^\s+if getent passwd 1000' "$WORKAROUNDS"
  [ "$status" -ne 0 ]
}

# EXECUTED. The guard is a string comparison against `id -u`, and a grep
# cannot tell a correct comparison from an inverted one.
@test "the guard fires at UID 1000 and stays silent otherwise" {
  stub="$(mktemp -d)"
  cat >"${stub}/id" <<EOF
#!/bin/sh
# \$1 is -u, \$2 is the account name
[ "\$2" = "alarm" ] && { echo "\${FAKE_UID}"; exit 0; }
exit 1
EOF
  chmod +x "${stub}/id"

  # The guard, verbatim in shape from 01-workarounds.sh.
  guard='if [[ "$(id -u alarm 2>/dev/null || echo -)" == "1000" ]]; then echo FIRE; fi'

  run env PATH="${stub}:$PATH" FAKE_UID=1000 bash -c "$guard"
  [ "$output" = "FIRE" ]

  run env PATH="${stub}:$PATH" FAKE_UID=1001 bash -c "$guard"
  [ -z "$output" ]

  rm -rf "$stub"
}
