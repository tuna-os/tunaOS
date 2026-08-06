#!/usr/bin/env bats
# dracut's tpm2-tss module, and the userspace it needs.
#
# The module ships in the default set on the apt bases, and dracut treats a
# requested-but-unsatisfiable module as FATAL rather than skipping it:
#
#   dracut[E]: Module 'tpm2-tss' cannot be installed.
#
# This bites at ISO-build time, not image-build time: tacklebox rebuilds the
# initramfs against the published image to inject tbox-live/tbox-root, and its
# omit-detection only drops a module whose modules.d directory is ABSENT. The
# directory is present on these bases; the userspace is not.
#
# The rpm/pacman/zypper bases take the other route — build_scripts/bootc/
# dracut-config.sh omits the module when `command -v tpm2_pcrread` fails. That
# lives on the containerfile-dedup branch and is asserted by its own tests
# there; this file covers the apt bases, which install the userspace instead.
#
# It is also flavour-dependent, which is what makes it dangerous: flounder:kde
# is green and flounder:gnome died here (run 31071849261), because the Plasma
# package set happens to pull enough of the tss2 stack in transitively. A cell
# passing is therefore NOT evidence the base is covered — hence a test on the
# package list rather than on a green matrix.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# The apt bases install dracut explicitly and get the module in the default
# set. The rpm/pacman/zypper ones manage it through dracut-config.sh's probe
# (`command -v tpm2_pcrread` decides omit), so they are not in scope here.
APT_CONTAINERFILES=(Containerfile.debian Containerfile.ubuntu)

strip_comments() { grep -v '^[[:space:]]*#' || true; }

@test "every apt base installs the tpm2 userspace dracut's module requires" {
  local f code missing fail=0
  for f in "${APT_CONTAINERFILES[@]}"; do
    code="$(strip_comments <"${REPO_ROOT}/$f")"
    missing=""
    grep -qE '(^|[[:space:]])tpm2-tools([[:space:]]|\\|$)' <<<"$code" || missing+=" tpm2-tools"
    grep -qE 'libtss2-esys' <<<"$code" || missing+=" libtss2-esys"
    grep -qE 'libtss2-tcti-device' <<<"$code" || missing+=" libtss2-tcti-device"
    grep -qE 'libtss2-tctildr' <<<"$code" || missing+=" libtss2-tctildr"
    grep -qE 'libtss2-rc' <<<"$code" || missing+=" libtss2-rc"
    if [ -n "$missing" ]; then
      echo "FAIL: ${f} installs dracut but not:${missing}" >&2
      echo "      dracut's tpm2-tss module is in the default set and an" >&2
      echo "      unsatisfiable module is fatal — the ISO build dies, not the" >&2
      echo "      image build, so this does not show up until tacklebox runs." >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}

@test "the apt bases use the t64 names, which are the ones that exist" {
  # Checked against the Debian trixie/sid and Ubuntu noble/resolute binary
  # indexes: the unsuffixed libtss2 names are published in none of them. A
  # copy-paste of the pre-t64 list installs nothing and fails the same way.
  local f code
  for f in "${APT_CONTAINERFILES[@]}"; do
    code="$(strip_comments <"${REPO_ROOT}/$f")"
    run grep -cE 'libtss2-(esys-3\.0\.2-0|rc0|tctildr0|tcti-device0)([[:space:]]|\\|$)' <<<"$code"
    [ "$output" -eq 0 ] || {
      echo "FAIL: ${f} names a pre-t64 libtss2 package, which does not exist" >&2
      return 1
    }
  done
}
