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
# there; this file covers the apt bases, which install the userspace instead,
# plus the emerge base, which is on neither route (see below).
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

# The other half of the same trap. pcsc is in the default module set on both
# apt bases and neither installs pcscd — but only Containerfile.ubuntu carried
# an omit line, because that is the variant the failure was first chased on.
# flounder:gnome died in `just iso` (run 31073039837) after a completely
# successful image build; flounder:kde survives because the Plasma set drags
# enough of the stack in by accident, which is exactly why a green cell is not
# evidence here either.
@test "every apt base omits the dracut modules whose userspace it lacks" {
  local f code fail=0
  for f in "${APT_CONTAINERFILES[@]}"; do
    code="$(strip_comments <"${REPO_ROOT}/$f")"
    # Two acceptable shapes. Delegating is the preferred one: the shared script
    # runs the same two `command -v` probes and has its own tests, so a base on
    # it cannot drift. Writing the line inline is fine for a base not yet moved.
    if grep -qE 'bootc/dracut-config\.sh' <<<"$code"; then
      # Delegation only covers this base while the script still does the thing
      # delegated to it. Assert the probe, or the omission can be deleted one
      # file away from every Containerfile that depends on it.
      local shared="${REPO_ROOT}/build_scripts/bootc/dracut-config.sh"
      grep -qE 'omit_dracutmodules' "$shared" &&
        grep -qE 'command -v pcscd([[:space:]]|$)' "$shared" || {
        echo "FAIL: ${f} delegates its dracut config to dracut-config.sh, but" >&2
        echo "      that script no longer probes pcscd and omits what is" >&2
        echo "      missing — so nothing omits pcsc on this base any more." >&2
        fail=1
      }
      continue
    fi
    if ! grep -qE 'omit_dracutmodules' <<<"$code"; then
      echo "FAIL: ${f} neither calls bootc/dracut-config.sh nor writes an" >&2
      echo "      omit_dracutmodules line. dracut's pcsc module is in the" >&2
      echo "      default set and neither apt base installs pcscd. An" >&2
      echo "      unsatisfiable module is fatal, and the failure surfaces at" >&2
      echo "      ISO build, not image build." >&2
      fail=1
      continue
    fi
    grep -qE 'pcsc' <<<"$code" || {
      echo "FAIL: ${f} omits something, but never pcsc." >&2
      fail=1
    }
  done
  [ "$fail" -eq 0 ]
}

# ── The emerge base ────────────────────────────────────────────────────────
#
# Containerfile.gentoo is on neither route: it installs no tpm2 userspace (as
# the apt bases do) and is not on dracut-config.sh's probe (as the rpm/pacman/
# zypper bases are), so all it ever had was `--omit "tpm2-tss pcsc"` on its own
# two dracut command lines. That covers the image build and nothing else, and
# tacklebox's rebuild is where this class of failure lands — guppy:gnome died
# there in LUKS run 31111959946 on a completely successful image.
GENTOO_CONTAINERFILE=Containerfile.gentoo

@test "the emerge base declares the omit in the image, not just on its own dracut line" {
  local code
  code="$(strip_comments <"${REPO_ROOT}/${GENTOO_CONTAINERFILE}")"

  # A command-line --omit is invisible to any other dracut run. Only a drop-in
  # under /usr/lib/dracut/dracut.conf.d reaches tacklebox's rebuild and a
  # kernel update on the installed system. /etc is not a substitute: it is
  # 3-way merged on a bootc system, so a local edit can drop it.
  grep -qE 'omit_dracutmodules\+=" *tpm2-tss +pcsc *"' <<<"$code" || {
    echo "FAIL: ${GENTOO_CONTAINERFILE} never declares omit_dracutmodules for" >&2
    echo "      tpm2-tss and pcsc. sys-kernel/dracut ships both modules.d" >&2
    echo "      directories whether or not the userspace was emerged, so" >&2
    echo "      tacklebox's presence probe omits neither and the ISO build" >&2
    echo "      dies on \"Module 'tpm2-tss' cannot be installed\"." >&2
    return 1
  }
  grep -qF '/usr/lib/dracut/dracut.conf.d/' <<<"$code"
}

@test "the emerge base's omit drop-in is inherited by every published stage" {
  # desktop-build is FROM builder, NOT FROM system, so the two stages that run
  # dracut do not share an ancestor below `base`. A drop-in written in `system`
  # would reach base-no-de and no desktop image at all — and the desktop images
  # are the ones the LUKS matrix builds ISOs from.
  local f conf_line builder_line
  f="${REPO_ROOT}/${GENTOO_CONTAINERFILE}"
  conf_line="$(grep -n 'dracut.conf.d/30-omit-unsatisfiable.conf' "$f" | head -1 | cut -d: -f1)"
  builder_line="$(grep -n '^FROM base AS builder' "$f" | head -1 | cut -d: -f1)"
  [ -n "$conf_line" ]
  [ -n "$builder_line" ]
  [ "$conf_line" -lt "$builder_line" ]
}

@test "the emerge base still passes the same omit to its own dracut runs" {
  # Belt and braces, and not redundant: the drop-in is what survives into the
  # ISO build, the flag is what the image build itself has always used. Both
  # dracut invocations (system and desktop stages) need it — the desktop stage
  # rebuilds the initramfs after install-desktop.sh.
  local f count
  f="${REPO_ROOT}/${GENTOO_CONTAINERFILE}"
  count="$(grep -cF -- '--omit "tpm2-tss pcsc"' "$f")"
  [ "$count" -eq 2 ]
}
