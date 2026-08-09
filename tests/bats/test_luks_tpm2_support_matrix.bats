#!/usr/bin/env bats
# docs/LUKS-TPM.md's variant support matrix claims three variants — sailfin,
# marlin, guppy — can never get TPM2 auto-unlock because their initramfs
# never carries the tpm2-tss dracut module at all, regardless of enrollment
# (tunaOS#714). That is a static fact: it follows from the Containerfile's
# dracut omit lines / package list, not from booting anything.
#
# This test is the tripwire that keeps the doc honest. If a future change
# gives one of these bases a real TPM2 userspace (e.g. Arch starts installing
# tpm2-tools), the matching test below breaks — which is the point: it means
# docs/LUKS-TPM.md's ❌ row for that variant is now stale and needs updating
# alongside whatever fixed the Containerfile, not silently left to say "not
# possible" about something that now works.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
DOC="${REPO_ROOT}/docs/LUKS-TPM.md"

strip_comments() { grep -v '^[[:space:]]*#' || true; }

# ── openSUSE (sailfin): unconditional omit ─────────────────────────────────

@test "Containerfile.opensuse still omits tpm2-tss/pcsc from dracut unconditionally" {
  local f="${REPO_ROOT}/Containerfile.opensuse"
  grep -qE 'omit_dracutmodules\+?="? *tpm2-tss +pcsc' "$f" || {
    echo "FAIL: Containerfile.opensuse no longer has the unconditional" >&2
    echo "      tpm2-tss/pcsc omit docs/LUKS-TPM.md's sailfin row cites." >&2
    echo "      If sailfin now installs a TPM2 userspace, update that row" >&2
    echo "      from '❌ not possible today' before touching this test." >&2
    return 1
  }
}

@test "sailfin installs no TPM2 userspace package" {
  local f="${REPO_ROOT}/Containerfile.opensuse"
  local code
  code="$(strip_comments <"$f")"
  # tpm2.0-tools is openSUSE's package name for the tpm2_pcrread binary
  # dracut-config.sh's probe (and this same fact, restated) looks for.
  if grep -qE 'tpm2\.0-tools|tpm2-tools' <<<"$code"; then
    echo "FAIL: Containerfile.opensuse now installs a tpm2 tools package," >&2
    echo "      but still hardcodes 'omit tpm2-tss pcsc' unconditionally —" >&2
    echo "      the omit is now blocking a userspace that exists. Route" >&2
    echo "      sailfin through dracut-config.sh's probe instead (like" >&2
    echo "      marlin/RPM bases) so the module is included when present," >&2
    echo "      and update docs/LUKS-TPM.md's sailfin row." >&2
    return 1
  fi
}

# ── Arch (marlin): dracut-config.sh probe, no userspace package ───────────

@test "Containerfile.arch still installs no TPM2 userspace package" {
  local f="${REPO_ROOT}/Containerfile.arch"
  local code
  code="$(strip_comments <"$f")"
  if grep -qE '(^|[[:space:]])tpm2-tools([[:space:]]|\\|$)' <<<"$code"; then
    echo "FAIL: Containerfile.arch now installs tpm2-tools." >&2
    echo "      dracut-config.sh's 'command -v tpm2_pcrread' probe will now" >&2
    echo "      find it and stop omitting tpm2-tss — marlin's initramfs" >&2
    echo "      would carry the module. Flip docs/LUKS-TPM.md's marlin row" >&2
    echo "      from '❌ not possible today' to '_pending E2E_' before" >&2
    echo "      touching this test, and run the tpm_autounlock sweep to" >&2
    echo "      confirm it actually unlocks." >&2
    return 1
  fi
}

@test "Containerfile.arch routes its dracut config through the shared probe" {
  # marlin's ❌ verdict depends on dracut-config.sh's probe being the thing
  # that decides tpm2-tss inclusion for this base — if Arch stops delegating
  # (e.g. reverts to a hardcoded omit like openSUSE/Gentoo, or starts adding
  # the module unconditionally), the reasoning in the doc's marlin row no
  # longer describes what the Containerfile actually does.
  local f="${REPO_ROOT}/Containerfile.arch"
  grep -qE 'bootc/dracut-config\.sh' "$f" || {
    echo "FAIL: Containerfile.arch no longer calls dracut-config.sh — the" >&2
    echo "      probe docs/LUKS-TPM.md's marlin row relies on doesn't run." >&2
    return 1
  }
}

# ── Gentoo (guppy): unconditional omit, well-documented already ───────────

@test "Containerfile.gentoo still declares the unconditional tpm2-tss/pcsc omit" {
  # Mirrors test_dracut_tpm2_userspace.bats's own assertions on this exact
  # Containerfile; restated here so this file is a complete, standalone
  # record of every ❌ row's reasoning in one place.
  local f="${REPO_ROOT}/Containerfile.gentoo"
  local code
  code="$(strip_comments <"$f")"
  grep -qE 'omit_dracutmodules\+=" *tpm2-tss +pcsc *"' <<<"$code" || {
    echo "FAIL: Containerfile.gentoo no longer declares the drop-in omit" >&2
    echo "      docs/LUKS-TPM.md's guppy row cites." >&2
    return 1
  }
  ! grep -qE '(^|[[:space:]])app-crypt/tpm2-tools([[:space:]]|\\|$)' <<<"$code" || {
    echo "FAIL: Containerfile.gentoo now emerges app-crypt/tpm2-tools —" >&2
    echo "      guppy may have a working TPM2 userspace now. Update" >&2
    echo "      docs/LUKS-TPM.md's guppy row before touching this test." >&2
    return 1
  }
}

# ── The doc itself: the three ❌ rows have to say ❌ ────────────────────────

@test "docs/LUKS-TPM.md marks sailfin, marlin, and guppy as not possible today" {
  local variant row fail=0
  for variant in sailfin marlin guppy; do
    row="$(grep -E "^\| ${variant} \|" "$DOC" || true)"
    if [[ -z "$row" ]]; then
      echo "FAIL: docs/LUKS-TPM.md has no matrix row for '${variant}'." >&2
      fail=1
      continue
    fi
    if ! grep -qF '❌' <<<"$row"; then
      echo "FAIL: docs/LUKS-TPM.md's '${variant}' row doesn't say ❌ —" >&2
      echo "      row: ${row}" >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}

@test "docs/LUKS-TPM.md does not still call the three ❌ variants 'pending E2E'" {
  # The failure mode this guards: someone runs the tpm_autounlock sweep,
  # sees it skip sailfin/marlin/guppy (by design — see generate-matrix's
  # NO_TPM_USERSPACE list), and "helpfully" resets their rows back to
  # '_pending E2E_' because no result ever showed up for them.
  local variant row fail=0
  for variant in sailfin marlin guppy; do
    row="$(grep -E "^\| ${variant} \|" "$DOC" || true)"
    [[ -n "$row" ]] || continue
    if grep -qF '_pending E2E_' <<<"$row"; then
      echo "FAIL: docs/LUKS-TPM.md's '${variant}' row still says" >&2
      echo "      '_pending E2E_' — it should not; no E2E run will ever" >&2
      echo "      populate it (generate-matrix skips these three)." >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}

# ── The workflow: the skip-list has to match the doc's ❌ rows ─────────────

@test "luks-e2e.yml's tpm_autounlock skip-list is exactly sailfin, marlin, guppy" {
  local wf="${REPO_ROOT}/.github/workflows/luks-e2e.yml"
  grep -qE 'NO_TPM_USERSPACE="sailfin marlin guppy"' "$wf" || {
    echo "FAIL: .github/workflows/luks-e2e.yml's NO_TPM_USERSPACE list has" >&2
    echo "      changed. It must track docs/LUKS-TPM.md's ❌ rows exactly:" >&2
    echo "      adding a variant there without a matching ❌ row spends a" >&2
    echo "      real QEMU boot the doc doesn't explain, and removing one" >&2
    echo "      re-tests a variant this file just asserted can't pass." >&2
    return 1
  }
}
