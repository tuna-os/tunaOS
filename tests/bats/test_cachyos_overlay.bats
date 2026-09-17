#!/usr/bin/env bats
# The cachyos overlay must end with exactly one kernel and an initramfs built
# for that kernel, named explicitly.
#
# Failure mode these tests pin (tunaOS#1563): cachyos.sh installed
# linux-cachyos on a parent that already ships stock `linux`, leaving two
# module trees, then wrote ONE initramfs to
#
#   "$(find /usr/lib/modules -maxdepth 1 -type d | grep -v '\.img' | tail -1)/initramfs.img"
#
# `find` without `sort` is readdir order, so the target was a per-image coin
# flip. Run 31766586852 flipped it both ways in one nightly — gnome/kde/cosmic
# wrote to /usr/lib/modules/7.1.8-arch1-3 (stock) and died in `bootc install`
# with "initramfs not found"; xfce/niri wrote to 7.1.8-1-cachyos and booted a
# kernel whose module tree disagreed, never reaching graphical.target. All five
# cachyos Gates failed while all five nvidia Gates passed, and the nvidia-arch
# overlay is the sibling that names its kernel explicitly.
#
# These are shape assertions on scripts that cannot be executed here (they run
# pacman against a live Arch root), matching the convention in
# test_nvidia_overlay.bats.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CACHYOS_SH="${REPO_ROOT}/build_scripts/overlay/cachyos.sh"
ARCH_CF="${REPO_ROOT}/Containerfile.arch"
NVIDIA_ARCH_SH="${REPO_ROOT}/build_scripts/overlay/overrides/nvidia-arch/20-nvidia.sh"

@test "cachyos.sh exists and is valid bash" {
  run bash -n "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

# ── the readdir gamble is gone ─────────────────────────────────────────────

@test "no find|tail -1 feeds an initramfs path in cachyos.sh" {
  # The precise defect: a command substitution whose result becomes the dracut
  # output path. Any reappearance is the bug coming back.
  #
  # ^[^#]* matches code only — cachyos.sh's own header quotes the old line
  # verbatim to explain what went wrong, and a test that cannot tell the
  # documentation from the defect would fail on the fix's own comment. Same
  # reason test_nvidia_overlay.bats anchors its dnf-config-manager check.
  run grep -nE '^[^#]*\$\(find /usr/lib/modules[^)]*\)/initramfs\.img' "$CACHYOS_SH"
  [ "$status" -ne 0 ]
  run grep -nE '^[^#]*find /usr/lib/modules.*tail -1.*initramfs' "$CACHYOS_SH"
  [ "$status" -ne 0 ]
  # The KVER selection line is allowed to end in `sort -V | tail -1`: it has
  # already filtered to *cachyos* dirs, so it is picking among candidates
  # rather than gambling across kernels. Only an initramfs PATH built that way
  # is the defect, which is why both patterns above require /initramfs.img.
}

@test "no find|tail -1 feeds an initramfs path in Containerfile.arch" {
  run grep -nE '^[^#]*\$\(find /usr/lib/modules[^)]*\)/initramfs\.img' "$ARCH_CF"
  [ "$status" -ne 0 ]
}

@test "the cachyos kernel is selected by name, not by version sort" {
  # sort -V puts the stock kernel LAST, so `sort -V | tail -1` would be a
  # deterministic wrong answer rather than a coin flip:
  #   $ printf '6.17.1-arch1-1\n6.17.1-2-cachyos\n' | sort -V | tail -1
  #   6.17.1-arch1-1
  # Prove that here rather than asserting it in a comment, so a future
  # "cleanup" to sort -V fails this test instead of the nightly.
  run bash -c "printf '6.17.1-arch1-1\n6.17.1-2-cachyos\n' | sort -V | tail -1"
  [ "$output" = "6.17.1-arch1-1" ]
  # Hence: -name '*cachyos*'. The `--` is required: the pattern starts with a
  # dash, so grep would otherwise parse it as options.
  run grep -F -- "-name '*cachyos*'" "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "an empty kernel selection is a hard failure, not an empty path" {
  # KVER="" would silently produce /usr/lib/modules//initramfs.img.
  run grep -A1 -E '^if \[ -z "\$KVER" \]' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ERROR"* ]]
  run grep -E '^\s*exit 1' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

# ── exactly one kernel survives ────────────────────────────────────────────

@test "cachyos.sh removes the stock kernel it was layered on top of" {
  # Containerfile.arch installs ${KERNEL_PKG} and ${KERNEL_PKG}-headers, which
  # is linux/linux-headers on x86_64. Same -Rdd mechanism as asahi.sh.
  run grep -F 'pacman -Rdd --noconfirm' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  run grep -E 'linux-headers' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "leftover module trees are deleted, because initramfs.img is not packaged" {
  # pacman -Rdd removes packaged files; the generated initramfs.img in the
  # stock tree survives and keeps the tree alive.
  run grep -F 'find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d ! -name "$KVER" -exec rm -rf {} +' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "exactly one remaining kernel is proven, not hoped for" {
  # tunaOS#912: the same rm -rf silently not working shipped a two-kernel
  # image. The count must be asserted and must exit non-zero.
  run grep -F 'REMAINING_COUNT' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  run grep -E 'REMAINING_COUNT.*-ne 1' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  # The assertion block must terminate the build.
  run awk '/REMAINING_COUNT.*-ne 1/{f=1} f&&/exit 1/{print "found"; exit}' "$CACHYOS_SH"
  [ "$output" = "found" ]
}

@test "the single-kernel assertion runs BEFORE the initramfs is built" {
  run awk '/REMAINING_COUNT.*-ne 1/{print NR; exit}' "$CACHYOS_SH"
  local assert_line="$output"
  run awk '/^dracut --force/{print NR; exit}' "$CACHYOS_SH"
  local dracut_line="$output"
  [ -n "$assert_line" ]
  [ -n "$dracut_line" ]
  [ "$assert_line" -lt "$dracut_line" ]
}

# ── dracut names its kernel ────────────────────────────────────────────────

@test "cachyos.sh passes both the output path and the kernel version to dracut" {
  # dracut's second positional is the kernel version. Passing the path alone is
  # what let the path and the built kernel disagree.
  run grep -F 'dracut --force --omit "tpm2-tss" "/usr/lib/modules/${KVER}/initramfs.img" "${KVER}"' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "the --omit tpm2-tss behaviour is preserved" {
  # tpm2-tss is in the installed package set; dropping the omit while
  # rewriting the line would be a silent behaviour change.
  run grep -F -- '--omit "tpm2-tss"' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "Containerfile.arch passes the kernel version to dracut and dracut-config" {
  run grep -F 'dracut --force "/usr/lib/modules/${KVER}/initramfs.img" "${KVER}"' "$ARCH_CF"
  [ "$status" -eq 0 ]
  # dracut-config.sh probes drivers against a kernel's module tree; it takes
  # the kver positionally and otherwise guesses with a plain (non -V) sort.
  run grep -F '/run/context/build_scripts/bootc/dracut-config.sh "$KVER"' "$ARCH_CF"
  [ "$status" -eq 0 ]
}

@test "cachyos.sh matches the nvidia-arch overlay's positional path+kver form" {
  # nvidia-arch is the sibling Arch overlay whose five flavors passed the Gate
  # in the run that failed all five cachyos flavors. Both must name the kernel.
  #
  # Match the positional pair alone, without a `dracut .*` prefix: nvidia-arch
  # wraps its invocation across two lines (the args are on the continuation),
  # and grep is line-oriented, so requiring both on one line asserts a line
  # layout rather than the thing that matters.
  run grep -E '"/usr/lib/modules/\$\{KVER\}/initramfs\.img" "\$\{KVER\}"' "$NVIDIA_ARCH_SH"
  [ "$status" -eq 0 ]
  run grep -E '"/usr/lib/modules/\$\{KVER\}/initramfs\.img" "\$\{KVER\}"' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

# ── no full upgrade mid-overlay ────────────────────────────────────────────

@test "cachyos.sh does not run a full -Syu mid-overlay" {
  # A full upgrade on a published parent can bump the stock kernel too, adding
  # a second moving kernel to a script whose job is to end with one. Not what
  # broke run 31766586852 (no `upgrading linux` in its log) — a latent one.
  run grep -E '^[^#]*pacman -Syu' "$CACHYOS_SH"
  [ "$status" -ne 0 ]
  # -Sy or -Syy, at any indent: the sync moved inside _cachyos_sync() when it
  # gained mirror rotation. Anchoring to column zero asserted the layout of the
  # file rather than what it does, and went red on a refactor that changed
  # neither the flags nor the upgrade ban this test exists for.
  run grep -E '^[[:space:]]*pacman -Syy? --noconfirm' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  run grep -E '^[[:space:]]*pacman -S --noconfirm --needed' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

# ── the db sync survives one bad mirror ─────────────────────────────────────

# All five *-cachyos cells died together on 2026-09-16 with
#   error: cachyos: signature from "CachyOS <admin@cachyos.org>" is invalid
# The key was right and unexpired, the keyring installed cleanly seconds
# earlier, and the same db/sig pair verifies Good on every mirror today — CI
# was served a stale db against a fresh sig, 38 minutes after a republish.
# buildah already retries the whole build three times; all three hit the same
# CDN edge and failed identically. Rotating the mirror is the load-bearing part.
@test "the cachyos db sync retries rather than failing on one bad mirror" {
  run grep -E '_cachyos_sync' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  # A refresh that ignores the cached copy, and the cached copy removed.
  run grep -E 'pacman -Syy --noconfirm' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  run grep -F 'rm -f /var/lib/pacman/sync/cachyos.db' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}

@test "a failed sync rotates to a different mirror" {
  # Retrying the same edge is what the buildah wrapper already did, and it did
  # not help. Without this line the retry above is decoration.
  run grep -F 'cachyos-mirrorlist' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
  # Assert the mirrorlist is REWRITTEN, not merely named. The first spelling
  # grepped the function body for "mirrorlist" and passed against a version
  # with the rotation deleted, because `local attempt mirrorlist=...` on line
  # one of the function still matched. A test that cannot fail is the bug it
  # was written to catch.
  run bash -c "sed -n '/_cachyos_sync()/,/^}/p' '$CACHYOS_SH' | grep -qE 'mv .*mirrorlist'"
  [ "$status" -eq 0 ]
  # And that the failed mirror is what moves to the back.
  run bash -c "sed -n '/_cachyos_sync()/,/^}/p' '$CACHYOS_SH' | grep -qE 'grep -m1 .\^Server'"
  [ "$status" -eq 0 ]
}

# The one fix that must never be taken. SigLevel = Never on [cachyos] would
# silence the error and ship an unverified kernel. It is legitimate ONLY in the
# throwaway config used to bootstrap the keyring itself, which cannot be
# verified before it exists.
@test "the cachyos repo is never given SigLevel = Never" {
  # The bootstrap sed targets a temp copy; assert it stays that way.
  run bash -c "grep -n 'SigLevel' '$CACHYOS_SH' | grep -v 'tmpconf' | grep -v '^[0-9]*:#'"
  [ "$status" -ne 0 ]
  # And nothing writes it into the real pacman.conf. Comments are stripped
  # first: an earlier spelling scanned a sed range from the first "[cachyos]"
  # to the next EOF and matched the very comment warning against this, so the
  # test failed on the prose documenting it.
  run bash -c "sed 's/#.*//' '$CACHYOS_SH' | grep -n 'SigLevel' | grep -v tmpconf"
  [ "$status" -ne 0 ]
}

@test "linux-cachyos is still what gets installed" {
  run grep -F 'linux-cachyos linux-cachyos-headers' "$CACHYOS_SH"
  [ "$status" -eq 0 ]
}
