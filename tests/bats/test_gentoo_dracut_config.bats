#!/usr/bin/env bats
# Containerfile.gentoo's initramfs must be built the way every other bootc
# variant builds one — through build_scripts/bootc/dracut-config.sh, and only
# after the ostree layout that script reads from.
#
# WHAT WENT WRONG
#
# Gentoo was the one bootable variant not calling the shared script. The
# comment that stood here said why: the script names the crypt and dm dracut
# modules, "which require cryptsetup and dmsetup binaries; Gentoo emerges
# neither", and dracut treats a requested-but-unsatisfiable module as fatal.
#
# Measured inside the published ghcr.io/tuna-os/guppy:gnome, that is no longer
# true — /usr/sbin/cryptsetup and /usr/sbin/dmsetup are both present, and dracut
# modules 51bootc, 70crypt and 70dm are all installed. What the image did NOT
# have was any of them in its initramfs: `lsinitrd` matched ZERO ostree/bootc
# files, because with no drop-in nothing ever asked for the bootc module.
#
# So nothing prepared the composefs deployment at boot, /sysroot stayed the
# physical root, and switch-root refused it:
#
#   Failed to switch root: Specified switch root path '/sysroot' does not seem
#   to be an OS tree. os-release file is missing.
#
# guppy:xfce reached an emergency shell with the disk already unlocked and
# /sysroot already mounted (LUKS run 31232170155) — a green image build, a green
# ISO build and a working LUKS unlock, all the way to the last step.
#
# ORDERING IS HALF THE FIX
#
# dracut-config.sh decides whether to add the erofs driver by reading
# /usr/lib/ostree/prepare-root.conf, which ostree-layout.sh writes. Gentoo built
# its initramfs BEFORE laying out the filesystem, so simply calling the script
# in place would have read composefs=off and produced an initramfs that still
# could not mount its own root — with every step exiting 0. And ostree-layout.sh
# `rm -rf`s /boot, so the kernel image has to be staged into /usr/lib/modules
# before it runs. Three steps, one order, none of it self-evident from any one
# line: hence a test.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
GENTOO="${REPO_ROOT}/Containerfile.gentoo"

# The two bootable stages. `desktop` is not a child of `system` (the chain is
# base -> builder -> desktop-build -> desktop), so each carries its own copy of
# the whole sequence and each has to be checked on its own.
BOOTABLE_STAGES=(system desktop)

# Non-comment lines, annotated with the stage they fall in: "<stage>\t<lineno>\t<text>".
# Comment-stripped so that commenting a step out fails exactly like deleting it.
stage_lines() {
  awk '
    tolower($0) ~ /^from[ \t]/ {
      stage="?"
      for (i=1;i<=NF;i++) if (tolower($i)=="as") stage=$(i+1)
      next
    }
    /^[[:space:]]*#/ { next }
    { print stage "\t" NR "\t" $0 }
  ' "$GENTOO"
}

# Line number of the first line in <stage> matching <ERE>, or empty.
first_in_stage() {
  stage_lines | awk -F'\t' -v s="$1" -v p="$2" '$1==s && $3 ~ p {print $2; exit}'
}

# A real dracut run, not the package name in an emerge/pacman/apt list: an
# invocation is `dracut` followed by a flag.
DRACUT_RUN='dracut[ \t]+-'
CONFIG_CALL='bootc/dracut-config\.sh'
LAYOUT_CALL='bootc/ostree-layout\.sh'

@test "both bootable gentoo stages build an initramfs at all" {
  local s n
  for s in "${BOOTABLE_STAGES[@]}"; do
    n="$(first_in_stage "$s" "$DRACUT_RUN")"
    [ -n "$n" ] || {
      echo "FAIL: stage '${s}' runs no dracut — nothing produces its initramfs." >&2
      return 1
    }
  done
}

@test "every gentoo dracut run is configured by the shared dracut-config.sh" {
  # The whole bug in one assertion. An unconfigured dracut still exits 0 and
  # still writes an initramfs; it just writes one with no bootc module.
  local s cfg dracut
  for s in "${BOOTABLE_STAGES[@]}"; do
    cfg="$(first_in_stage "$s" "$CONFIG_CALL")"
    dracut="$(first_in_stage "$s" "$DRACUT_RUN")"
    [ -n "$cfg" ] || {
      echo "FAIL: stage '${s}' runs dracut without calling dracut-config.sh." >&2
      echo "      Its initramfs gets no bootc module, so switch-root finds the" >&2
      echo "      physical root instead of the deployment and emergency-shells." >&2
      return 1
    }
    [ "$cfg" -lt "$dracut" ] || {
      echo "FAIL: stage '${s}' calls dracut-config.sh at line ${cfg}, AFTER the" >&2
      echo "      dracut run at line ${dracut}. The config lands too late to" >&2
      echo "      affect the initramfs that was just built." >&2
      return 1
    }
  done
}

@test "the ostree layout is written before dracut-config.sh reads it" {
  # dracut-config.sh probes /usr/lib/ostree/prepare-root.conf (written by
  # ostree-layout.sh) to decide whether this image is composefs and therefore
  # whether its initramfs needs the erofs driver. Reversed, composefs reads as
  # off and the driver is silently dropped — the exact bug wiring arch hit, and
  # the reason Containerfile.debian carries a MUST-precede note.
  local s layout cfg
  for s in "${BOOTABLE_STAGES[@]}"; do
    layout="$(first_in_stage "$s" "$LAYOUT_CALL")"
    cfg="$(first_in_stage "$s" "$CONFIG_CALL")"
    [ -n "$layout" ]
    [ -n "$cfg" ]
    [ "$layout" -lt "$cfg" ] || {
      echo "FAIL: stage '${s}' runs ostree-layout.sh at ${layout}, after" >&2
      echo "      dracut-config.sh at ${cfg} — composefs will read as off and" >&2
      echo "      the initramfs will ship with no erofs driver." >&2
      return 1
    }
  done
}

@test "the kernel is staged out of /boot before the layout deletes /boot" {
  # ostree-layout.sh does `rm -rf /boot`. Gentoo's kernel image only exists
  # there (or in the kernel source tree), and /usr/lib/modules/<kver>/vmlinuz is
  # where bootc looks for it. Staging after the wipe leaves an image with no
  # kernel to boot.
  local s stage_kernel layout
  for s in "${BOOTABLE_STAGES[@]}"; do
    stage_kernel="$(first_in_stage "$s" 'cp /boot/vmlinuz')"
    layout="$(first_in_stage "$s" "$LAYOUT_CALL")"
    [ -n "$stage_kernel" ] || {
      echo "FAIL: stage '${s}' never copies a kernel into /usr/lib/modules." >&2
      return 1
    }
    [ "$stage_kernel" -lt "$layout" ] || {
      echo "FAIL: stage '${s}' stages the kernel at ${stage_kernel}, after" >&2
      echo "      ostree-layout.sh removes /boot at ${layout}." >&2
      return 1
    }
  done
}

@test "the RUN that calls dracut-config.sh mounts the build context" {
  # The script is reached at /run/context/build_scripts/..., which exists only
  # inside a RUN carrying the context bind-mount. Without it the path is absent
  # and the step dies — or, worse, is written with `|| true` somewhere and does
  # nothing. Caught on the first draft of this very change.
  local n header
  while read -r n; do
    header="$(awk -v n="$n" 'NR<=n && /^RUN/ {h=$0} END {print h}' "$GENTOO")"
    [[ "$header" == *"from=context"* ]] || {
      echo "FAIL: the dracut-config.sh call at line ${n} is in a RUN with no" >&2
      echo "      context bind-mount: ${header}" >&2
      return 1
    }
  done < <(stage_lines | awk -F'\t' -v p="$CONFIG_CALL" '$3 ~ p {print $2}')
}

@test "each stage verifies the built initramfs actually has the bootc module" {
  # The failure this whole file is about was invisible at build time. lsinitrd
  # on the produced image makes it loud, the way Containerfile.opensuse already
  # does for its own crypt/dm payload.
  local s code
  for s in "${BOOTABLE_STAGES[@]}"; do
    code="$(stage_lines | awk -F'\t' -v st="$s" '$1==st {print $3}')"
    grep -q 'lsinitrd' <<<"$code" || {
      echo "FAIL: stage '${s}' never inspects the initramfs it just built." >&2
      return 1
    }
    grep -qE "grep -qx bootc" <<<"$code" || {
      echo "FAIL: stage '${s}' runs lsinitrd but never asserts the bootc module." >&2
      return 1
    }
  done
}

@test "the initramfs assertion is fatal, not a warning" {
  # A check that prints and continues would have let run 31232170155 ship
  # unchanged. Pin the exit.
  run grep -A2 "initramfs has no 'bootc' dracut module" "$GENTOO"
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit 1"* ]]
}

@test "no Containerfile runs dracut before configuring it" {
  # The cross-variant version of the same property. Scoped to files that have
  # adopted the shared script — Containerfile.opensuse writes its config inline
  # and is checked by its own drop-in assertions; Containerfile.ubuntu runs no
  # dracut at all (tacklebox rebuilds its initramfs at ISO time).
  local cf name cfg dracut
  for cf in "${REPO_ROOT}"/Containerfile.*; do
    name="$(basename "$cf")"
    cfg=$(grep -nE "$CONFIG_CALL" "$cf" | grep -vE ':[[:space:]]*#' | head -1 | cut -d: -f1)
    [ -n "$cfg" ] || continue
    dracut=$(grep -nE "$DRACUT_RUN" "$cf" | grep -vE ':[[:space:]]*#' | head -1 | cut -d: -f1)
    [ -n "$dracut" ] || continue
    [ "$cfg" -lt "$dracut" ] || {
      echo "FAIL: ${name} runs dracut at ${dracut} before dracut-config.sh at ${cfg}." >&2
      return 1
    }
  done
}
