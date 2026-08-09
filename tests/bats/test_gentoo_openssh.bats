#!/usr/bin/env bats
# Containerfile.gentoo must install openssh UNCONDITIONALLY, in the `builder`
# stage, so every published guppy image carries a real
# /usr/lib/systemd/system/sshd.service for the dev-ISO pipeline to enable.
#
# WHAT WENT WRONG (tunaOS#879)
#
# Every LUKS E2E cell builds a *dev* ISO (ENABLE_SSHD=1), and
# customize-live.sh aborts the build unless the image has an SSH unit to
# enable:
#
#   ERROR: dev ISO requested but no SSH service is installed
#
# Flounder (the Gentoo variant, now `guppy`) died there for weeks. The issue's
# original hypothesis was that Gentoo's net-misc/openssh installs its systemd
# unit "at a different path, or under a different name". That is wrong: the
# Gentoo ebuild runs systemd_newunit(sshd.service) UNCONDITIONALLY (it is not
# behind USE=systemd), and the unit lands at the standard
# /usr/lib/systemd/system/sshd.service as a real file, exactly the shape
# customize-live.sh prefers over the Debian-style compat symlink.
#
# The actual root cause was that the package was never installed in the image
# at all. Containerfile.gentoo declared ARG/ENV ENABLE_SSHD but did nothing
# with it on the Gentoo branch — the first fix (6931c34b) added a conditional
# emerge:
#
#   RUN if [ "${ENABLE_SSHD}" = "1" ]; then emerge net-misc/openssh ...; fi
#
# which failed twice over: the ENABLE_SSHD build-arg is never set when the
# published images the ISO pipeline customizes are built (production policy is
# SSH closed), and the emerge was sited after /var/db had been removed, where
# portage cannot record what it installs. The definitive fix (3c812ca8) moved
# the atom into the builder stage's always-run emerge:
#
#   RUN emerge --verbose dev-util/ostree net-misc/openssh && ...
#
# `builder` is the ancestor of every bootable stage (system, base-no-de,
# desktop-build -> desktop -> gnome/kde/xfce), so the unit is present in every
# published guppy flavor whether or not ENABLE_SSHD was set. The green guppy
# LUKS cells (e.g. run 31242742608, guppy:xfce) are downstream evidence; these
# tests pin the wiring so the gap cannot silently regress.
#
# WHY THE TEST LIVES HERE AND NOT IN test_build_scripts.bats
#
# 40-services.sh's ensure_openssh_installed (tunaOS#951) is the belt-and-
# braces path: it installs openssh if the unit is missing, so a future
# Containerfile.gentoo that drops the atom would still "work" on dev ISOs —
# except the 40-services.sh emerge runs in the desktop stage AFTER the /var
# wipe, against a relocated portage database, and is exactly the fragile
# late-emerge the definitive fix moved away from. The property this file
# guards is the Containerfile's own unconditional base-install.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
GENTOO="${REPO_ROOT}/Containerfile.gentoo"

# Non-comment lines, annotated with the stage they fall in: "<stage>\t<lineno>\t<text>".
# Comment-stripped so that commenting the emerge out fails exactly like
# deleting it.
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

# Parent of a stage, per the file's FROM lines: "<stage> <parent>".
from_pairs() {
  grep -iE '^FROM ' "$GENTOO" |
    sed -E 's/^FROM[[:space:]]+([^[:space:]]+)[[:space:]]+AS[[:space:]]+([^[:space:]]+).*/\2 \1/I'
}

@test "Containerfile.gentoo: the builder stage emerges net-misc/openssh" {
  local n
  n="$(first_in_stage builder 'net-misc/openssh')"
  [ -n "$n" ] || {
    echo "FAIL: the builder stage never emerges net-misc/openssh." >&2
    echo "      customize-live.sh then aborts every dev ISO with" >&2
    echo "      'no SSH service is installed' (tunaOS#879)." >&2
    return 1
  }
}

@test "Containerfile.gentoo: openssh is installed unconditionally, not under ENABLE_SSHD" {
  # The first fix attempt (6931c34b) gated the emerge on the ENABLE_SSHD
  # build-arg. Published images never set it (production policy is SSH
  # closed), so the gate made the dev-ISO path depend on a rebuild the
  # pipeline does not do, and the error never moved. The atom must be in the
  # always-run emerge: exactly one mention, on a plain RUN line.
  local mentions line
  mentions="$(grep -n 'net-misc/openssh' "$GENTOO" || true)"
  [ "$(grep -c . <<<"$mentions")" -eq 1 ] || {
    echo "FAIL: expected exactly one net-misc/openssh mention, got:" >&2
    echo "$mentions" >&2
    return 1
  }
  line="$(grep 'net-misc/openssh' "$GENTOO" || true)"
  grep -qE '^[[:space:]]*RUN[[:space:]]+emerge' <<<"$line" || {
    echo "FAIL: the openssh mention is not on a plain 'RUN emerge' line:" >&2
    echo "      $line" >&2
    return 1
  }
  if grep -qiE 'ENABLE_SSHD|if[[:space:]]+\[|then' <<<"$line"; then
    echo "FAIL: the openssh emerge is gated on ENABLE_SSHD/if:" >&2
    echo "      $line" >&2
    return 1
  fi
}

@test "Containerfile.gentoo: every bootable stage descends from the builder stage" {
  # `builder` is where the openssh emerge lives; a stage that does not chain
  # through it ships no sshd.service no matter what the emerge says. The chain
  # is base -> builder -> system -> base-no-de and base -> builder ->
  # desktop-build -> desktop -> gnome/kde/xfce. Pin the ancestry so a future
  # refactor that forks a bootable stage off `base` has to be deliberate.
  local pairs
  pairs="$(from_pairs)"
  local stage parent walk found
  for stage in system base-no-de desktop-build desktop gnome kde xfce; do
    # The stage itself must exist...
    grep -qE "^${stage} " <<<"$pairs" || {
      echo "FAIL: no 'FROM ... AS ${stage}' in Containerfile.gentoo" >&2
      return 1
    }
    # ...and walk its FROM chain up to the root, requiring `builder` appears.
    found=""
    walk="$stage"
    while [[ -n "$walk" ]]; do
      [[ "$walk" == "builder" ]] && found=1 && break
      parent="$(awk -v s="$walk" '$1==s {print $2; exit}' <<<"$pairs")"
      [[ -n "$parent" ]] || break
      walk="$parent"
    done
    [ -n "$found" ] || {
      echo "FAIL: stage '${stage}' does not descend from the builder stage" >&2
      echo "      that emerges net-misc/openssh — its dev ISO would abort with" >&2
      echo "      'no SSH service is installed' (tunaOS#879)." >&2
      return 1
    }
  done
}

@test "Containerfile.gentoo: the openssh emerge precedes both /var wipes" {
  # The failed first attempt also sited the emerge after /var/db had been
  # removed, where portage cannot record the install. The unconditional emerge
  # in `builder` must stay ahead of the /var relocations the system/desktop
  # stages run (the ones that move /var/db to /usr/lib/sysimage/portage).
  local emerge_line
  emerge_line="$(grep -n 'net-misc/openssh' "$GENTOO" | cut -d: -f1)"
  # The first `/var/db`-touching removal in the file, if any, must come after.
  local first_wipe
  first_wipe="$(grep -nE 'rm -rf /var/db|rm -rf /var/cache' "$GENTOO" | head -1 | cut -d: -f1)"
  if [[ -n "$first_wipe" ]]; then
    [ "$emerge_line" -lt "$first_wipe" ] || {
      echo "FAIL: openssh emerge (line ${emerge_line}) runs after the /var" >&2
      echo "      wipe/relocation at line ${first_wipe}; portage cannot record" >&2
      echo "      the install there (tunaOS#879 first attempt)." >&2
      return 1
    }
  fi
}
