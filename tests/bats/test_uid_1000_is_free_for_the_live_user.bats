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
#
# WHAT THE EARLIER VERSION OF THIS FILE MISSED
#
# It asserted that the removal existed in 01-workarounds.sh, and stopped
# there. Only Containerfile.el10 and Containerfile.ubuntu run that script, so
# the Arch branch was unreachable and marlin's arm64 ISO failed on the exact
# message the branch was written to prevent — with every test passing. Proving
# code exists is not proving it runs, so the reachability test below is the
# load-bearing one here.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  FREE_UID="${REPO_ROOT}/build_scripts/free-uid-1000.sh"
}

@test "both stock accounts are removed" {
  # On a non-comment line: the account names appear in this script's prose
  # too, and matching those would prove nothing.
  for u in ubuntu alarm; do
    run bash -c "grep -qE '^[^#]*\"${u}:' '$FREE_UID'"
    [ "$status" -eq 0 ] || {
      echo "no removal entry for the stock account '${u}'" >&2
      return 1
    }
  done
  run grep -E 'userdel .*--remove' "$FREE_UID"
  [ "$status" -eq 0 ]
}

# THE TEST THAT WOULD HAVE CAUGHT THE BUG.
#
# Every base whose cells build a live ISO has to REACH the removal. A
# Containerfile that never invokes it ships an image with UID 1000 taken, and
# the failure surfaces an hour later in another repository's code.
@test "every Containerfile that builds ISOs reaches the removal" {
  for cf in Containerfile.arch Containerfile.ubuntu Containerfile.el10; do
    path="${REPO_ROOT}/${cf}"
    [ -f "$path" ] || continue
    # Either directly, or via 01-workarounds.sh which calls it. The match
    # must be a real invocation: anchoring on a non-comment line matters,
    # because an early version of this test passed on a COMMENT that merely
    # mentioned the script by name.
    run bash -c "grep -qE '^[^#]*/run/context/build_scripts/(free-uid-1000|01-workarounds)\.sh' '$path'"
    [ "$status" -eq 0 ] || {
      echo "${cf} never runs free-uid-1000.sh, directly or through 01-workarounds.sh" >&2
      echo "UID 1000 will still be taken and the ISO job will fail in tacklebox" >&2
      return 1
    }
  done
}

# 01-workarounds.sh must delegate rather than keep a second copy. Two
# implementations drift, and the one that drifts is the one nobody is reading
# when the ISO breaks.
@test "01-workarounds.sh delegates instead of reimplementing the removal" {
  w="${REPO_ROOT}/build_scripts/01-workarounds.sh"
  run grep -F 'free-uid-1000.sh' "$w"
  [ "$status" -eq 0 ]
  run grep -E '^\s*userdel' "$w"
  [ "$status" -ne 0 ]
}

# The removal is narrow on purpose: a base that renumbers the account, or an
# operator who repurposed the name, must be left alone rather than silently
# altered. Assert the UID equality guard, not just the userdel.
@test "the removal is guarded on the account still being exactly 1000" {
  run grep -F '== "1000"' "$FREE_UID"
  [ "$status" -eq 0 ]
}

# The diagnostic used to live inside the Ubuntu branch, so the identical
# failure on Arch ARM was never reported and had to be traced back from an ISO
# job by hand. It must sit outside the removal loop, so the NEXT base that
# ships an account at 1000 says so in the build that causes it.
@test "the UID 1000 warning is not trapped inside the removal loop" {
  run grep -E '^if getent passwd 1000' "$FREE_UID"
  [ "$status" -eq 0 ]
  run grep -E '^[[:space:]]+if getent passwd 1000' "$FREE_UID"
  [ "$status" -ne 0 ]
}

# EXECUTED, against the real script. The loop and its guard are shell string
# handling, and a grep cannot tell a correct comparison from an inverted one.
@test "the script removes an account at 1000 and spares one at 1001" {
  stub="$(mktemp -d)"
  cat >"${stub}/id" <<EOF
#!/bin/sh
[ "\$2" = "alarm" ] && { echo "\${FAKE_UID}"; exit 0; }
exit 1
EOF
  cat >"${stub}/userdel" <<'EOF'
#!/bin/sh
echo "USERDEL $*"
EOF
  cat >"${stub}/getent" <<'EOF'
#!/bin/sh
exit 2
EOF
  chmod +x "${stub}/id" "${stub}/userdel" "${stub}/getent"

  run env PATH="${stub}:$PATH" FAKE_UID=1000 bash "$FREE_UID"
  [ "$status" -eq 0 ]
  [[ "$output" == *"USERDEL --remove alarm"* ]] || {
    echo "the account at UID 1000 was not removed: $output" >&2
    return 1
  }

  run env PATH="${stub}:$PATH" FAKE_UID=1001 bash "$FREE_UID"
  [ "$status" -eq 0 ]
  [[ "$output" != *"USERDEL"* ]] || {
    echo "an account at UID 1001 was removed: $output" >&2
    return 1
  }

  rm -rf "$stub"
}
