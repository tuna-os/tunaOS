#!/usr/bin/env bats
# Every image a live ISO is built from needs an indexed kernel module tree.
#
# tacklebox picks the kernel by looking for the index, not the kernel:
#
#   for d in /usr/lib/modules/*/; do
#     [ -f "$d/modules.dep" ] || continue
#
# With no modules.dep it finds no kernel at all and stops:
#
#   no kernel found under /usr/lib/modules (looked for modules.dep):
#   7.2.6-1-aarch64-ARCH
#
# (marlin run 35215948753, job 105195304184.) The directory is right there in
# that error — the image has vmlinuz and initramfs.img, and it boots. Only the
# index is missing, and only the ISO build cares.
#
# WHY ONLY ARCH, AND ONLY ON aarch64
#
# depmod runs from build_scripts/26-packages-post.sh for every other variant.
# Containerfile.arch does not run that script. On x86_64 that was harmless:
# the base is docker.io/archlinux, `pacman -S linux` really installs a kernel,
# and pacman's own depmod hook writes the index. On aarch64 the base is
# ghcr.io/tuna-os/archlinuxarm, whose rootfs already ships linux-aarch64, so
# `pacman -S --needed` is a no-op, the hook never fires, and nothing ever
# indexes the tree.
#
# This is the third fix in one day whose home was a script the failing base
# does not run, so the assertion here is about REACH, not about the command
# existing somewhere in the repository.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
}

# SCOPE, stated honestly: this file asserts the fix for Containerfile.arch and
# does NOT demand that every base call depmod, because that is not the
# invariant and I have not verified it.
#
# Only Containerfile.el10 runs 26-packages-post.sh at all. debian, ubuntu,
# gentoo and opensuse each carry a comment saying they do not run it, and
# their ISOs build anyway: apt, emerge and zypper index the module tree from
# the kernel package's own post-install. Arch normally does too, through a
# pacman hook. The hook is what goes missing here, and only on aarch64, for
# the reason in the header.
#
# A test demanding an explicit depmod in every Containerfile would fail four
# bases that are working correctly, so it would be pressure to weaken it
# later. This asserts the narrow thing that is actually true.

# Arch is the base that actually broke, so pin it by name too. A future
# refactor that drops the call from this one Containerfile must fail here even
# if the loop above is ever loosened.
@test "Containerfile.arch runs depmod on a line that is not a comment" {
  run bash -c "grep -qE '^[^#]*\\bdepmod\\b' '${REPO_ROOT}/Containerfile.arch'"
  [ "$status" -eq 0 ]
}

# depmod must use the SAME kernel the rest of the step uses. The comment above
# that RUN explains why this step names the kernel once: an independent
# `find ... | tail -1` in build_scripts/overlay/cachyos.sh picked a different
# kernel per flavor and failed 5/5 cachyos Gates (tunaOS#1563). Indexing one
# kernel and building an initramfs for another would be the same bug.
@test "depmod uses the KVER the step already resolved" {
  run grep -E '^[[:space:]]*depmod "\$KVER"' "${REPO_ROOT}/Containerfile.arch"
  [ "$status" -eq 0 ]
}

# It must run BEFORE dracut: dracut resolves modules against the tree, and a
# later index would not help the initramfs it already built.
@test "depmod runs before dracut in that step" {
  d="$(grep -n '^[[:space:]]*depmod "\$KVER"' "${REPO_ROOT}/Containerfile.arch" | head -1 | cut -d: -f1)"
  k="$(grep -n '^[[:space:]]*dracut --force' "${REPO_ROOT}/Containerfile.arch" | head -1 | cut -d: -f1)"
  [ -n "$d" ] && [ -n "$k" ]
  [ "$d" -lt "$k" ] || {
    echo "depmod (line $d) must precede dracut (line $k)" >&2
    return 1
  }
}

# No `|| true`. A module tree that cannot be indexed is a broken image, and
# swallowing the error is what sends the real failure an hour downstream into
# another repository's code.
@test "the depmod failure is not swallowed" {
  line="$(grep -E '^[[:space:]]*depmod "\$KVER"' "${REPO_ROOT}/Containerfile.arch" | head -1)"
  [[ "$line" != *"|| true"* ]] || {
    echo "depmod failure is suppressed: $line" >&2
    return 1
  }
}
