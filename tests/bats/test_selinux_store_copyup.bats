#!/usr/bin/env bats
# The SELinux policy-store copy-up in the nvidia overlay (tunaOS#1562).
#
# `semodule --install` died mid-build on 6+ nvidia cells on 2026-08-14 with:
#
#   semanage_commit_sandbox: Error while renaming .../tmp to .../active.
#     (Directory not empty).
#
# preceded, in an earlier RPM scriptlet, by:
#
#   semanage_rename: WARNING: rename(...active, ...previous) failed:
#     Invalid cross-device link, fall back to non-atomic semanage_copy_dir_flags()
#
# Those two messages are one mechanism, and the second explains the first.
# libsemanage commits by renaming active -> previous, then tmp -> active. On
# overlayfs, renaming a directory that lives in a LOWER layer fails EXDEV, so
# libsemanage falls back to COPYING active -> previous — which leaves active/
# in place. The next rename then lands on a populated directory and gets
# ENOTEMPTY. Whether a given flavor hits it depends only on whether that layer
# was rebuilt or served from --cache-from, which is why it read as random.
#
# The fix copies the store into the top layer first. These tests prove the
# mechanism rather than restating it, by running the overlay for real: the
# failure is reproduced, then the ACTUAL block from 20-nvidia.sh is extracted
# and run against the same fixture. So an edit that keeps the lines but breaks
# their order (dropping the `rm -rf` before the `mv`, say) fails here — a grep
# for the lines could not tell the difference.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
INSTALL_SH="${REPO_ROOT}/build_scripts/overlay/overrides/nvidia/20-nvidia.sh"

# Needs unprivileged user+mount namespaces and overlayfs-over-tmpfs. Available
# on GitHub-hosted ubuntu runners; skipped rather than failed anywhere it is
# not, so a constrained runner reports "skipped", not a fake regression.
setup() {
  if ! unshare -Ur --mount true 2>/dev/null; then
    skip "unprivileged user+mount namespaces unavailable"
  fi
}

# Runs a script inside a namespace with an overlay mounted at /mnt/merged,
# lower layer pre-populated with a policy store — i.e. the state a cached
# build layer leaves behind.
in_overlay() {
  local body="$1"
  unshare -Ur --mount bash -s <<EOF 2>&1
set -u
mount -t tmpfs tmpfs /mnt || exit 1
mkdir -p /mnt/lower/selinux/targeted/active/modules /mnt/upper /mnt/work /mnt/merged
echo kern > /mnt/lower/selinux/targeted/active/policy.kern
mount -t overlay overlay -o lowerdir=/mnt/lower,upperdir=/mnt/upper,workdir=/mnt/work /mnt/merged || exit 1
S=/mnt/merged/selinux/targeted
${body}
EOF
}

# libsemanage's commit order, with its documented fallback. Prints one line per
# rename so a failure names which one broke.
COMMIT_SANDBOX='
mkdir -p "$S/tmp/modules"; echo new > "$S/tmp/policy.kern"
python3 - "$S" <<'"'"'PY'"'"'
import os, sys, errno
S = sys.argv[1]
def rename(a, b):
    try:
        os.rename(f"{S}/{a}", f"{S}/{b}"); print(f"rename({a}->{b}): OK"); return True
    except OSError as e:
        print(f"rename({a}->{b}): {errno.errorcode[e.errno]}"); return False
if not rename("active", "previous"):
    print("fallback: non-atomic copy, active/ stays put")
rename("tmp", "active")
PY
'

# The real block, path-substituted onto the fixture. Extracted rather than
# retyped so the test cannot drift from the script it is defending — the same
# reason test_registry_ref.bats sed-patches the real _registry.sh.
copyup_block() {
  awk '/Force copy-up of \/etc\/selinux\/targeted/{f=1}
       f{print}
       f && /^\tfi$/{exit}' "$INSTALL_SH" \
    | sed 's#/etc/selinux/targeted#"$S"#g'
}

@test "the extracted copy-up block is not empty (the script still has one)" {
  run copyup_block
  [ "$status" -eq 0 ]
  [[ "$output" == *"cp -a"* ]]
  [[ "$output" == *'mv "$S".copyup "$S"'* ]]
}

@test "without the copy-up, libsemanage's commit reproduces the build failure" {
  run in_overlay "$COMMIT_SANDBOX"
  [ "$status" -eq 0 ]
  # Exactly the two messages from the build log, in order: the EXDEV that sends
  # libsemanage down the copy path, then the ENOTEMPTY that kills semodule.
  [[ "$output" == *"rename(active->previous): EXDEV"* ]]
  [[ "$output" == *"rename(tmp->active): ENOTEMPTY"* ]]
}

@test "with the copy-up from 20-nvidia.sh, both renames succeed" {
  run in_overlay "$(copyup_block)
${COMMIT_SANDBOX}"
  [ "$status" -eq 0 ]
  [[ "$output" == *"rename(active->previous): OK"* ]]
  [[ "$output" == *"rename(tmp->active): OK"* ]]
  [[ "$output" != *"ENOTEMPTY"* ]]
  [[ "$output" != *"EXDEV"* ]]
}

@test "the copy-up preserves the store rather than emptying it" {
  # A copy-up that lost the policy would turn a loud build failure into a
  # broken image, which is worse. Assert the payload survives the round trip.
  #
  # Guarded on the block being non-empty: with no copy-up in the script this
  # body degrades to a bare `cat`, which passes without proving anything.
  local block
  block="$(copyup_block)"
  [ -n "$block" ]
  run in_overlay "$block
cat \"\$S/active/policy.kern\"
ls \"\$S/active\""
  [ "$status" -eq 0 ]
  [[ "$output" == *"kern"* ]]
  [[ "$output" == *"modules"* ]]
}

@test "the copy-up runs before semodule, not after" {
  # Ordering is the entire fix: after the semodule call it would be a no-op.
  run awk '/Force copy-up of/{print NR; exit}' "$INSTALL_SH"
  local copyup_line="$output"
  run awk '/semodule --verbose --install/{print NR; exit}' "$INSTALL_SH"
  local semodule_line="$output"
  [ -n "$copyup_line" ]
  [ -n "$semodule_line" ]
  [ "$copyup_line" -lt "$semodule_line" ]
}
