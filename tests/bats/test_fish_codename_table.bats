#!/usr/bin/env bats
# Every variant needs a fish codename, and the table has to be able to find it.
#
# verify-branding.sh looks the variant up in an associative array. The keys were
# unquoted, and shfmt reads `[bonito-rawhide]` as an arithmetic subscript and
# rewrites it to `[bonito - rawhide]`. Bash then stores a key with spaces in it,
# so the lookup for the real variant id misses and the build fails on:
#
#   FAIL: no fish codename defined for variant 'flounder-sid'
#
# flounder-sid:gnome, LUKS run 31093350820 — every other branding assertion
# passed. bonito-rawhide had the identical corruption and had never been run,
# so it was two latent failures, not one.
#
# 90-image-info.sh spells the same mapping as a `case` pattern, which shfmt does
# not touch, so the two sources of truth disagreed with nothing in the diff to
# show it. That is what makes this worth a test rather than a one-line fix.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
BRANDING="${REPO_ROOT}/build_scripts/checks/verify-branding.sh"
IMAGEINFO="${REPO_ROOT}/build_scripts/90-image-info.sh"

# The table as bash actually parses it, not as it reads on the page.
fish_keys() {
  bash -c 'eval "$(sed -n "/^declare -A FISH=(/,/^)/p" "$1")"; printf "%s\n" "${!FISH[@]}"' _ "$BRANDING"
}

@test "no key in the table contains whitespace" {
  # The corruption is invisible in review — `[flounder - sid]` looks like
  # formatting. This is the assertion that sees it.
  local k
  while read -r k; do
    [[ "$k" != *" "* ]] || {
      echo "FAIL: FISH key '${k}' contains a space." >&2
      echo "      shfmt mangles unquoted hyphenated subscripts; quote the key." >&2
      return 1
    }
  done < <(fish_keys)
}

@test "every variant in build-config.yml resolves to a codename" {
  local fail=0 v
  local keys
  keys="$(fish_keys)"
  while read -r v; do
    [ -n "$v" ] || continue
    if ! grep -qxF "$v" <<<"$keys"; then
      echo "FAIL: variant '${v}' has no entry in verify-branding.sh's FISH table." >&2
      echo "      Its image build fails the branding contract." >&2
      fail=1
    fi
  done < <(python3 -c "
import yaml,sys
d=yaml.safe_load(open('${REPO_ROOT}/.github/build-config.yml'))
print('\n'.join(v['id'] for v in d['variants']))
")
  [ "$fail" -eq 0 ]
}

@test "the two sources of the codename agree" {
  # 90-image-info.sh WRITES VERSION_CODENAME and verify-branding.sh CHECKS it.
  # If a variant is in one and not the other the build fails at the check, so
  # both must name it.
  local fail=0 v
  while read -r v; do
    [ -n "$v" ] || continue
    grep -qE "(^|[| ])${v}[ )|]" "$IMAGEINFO" || {
      echo "FAIL: variant '${v}' has a codename in verify-branding.sh but is" >&2
      echo "      not matched by any case pattern in 90-image-info.sh." >&2
      fail=1
    }
  done < <(fish_keys)
  [ "$fail" -eq 0 ]
}
