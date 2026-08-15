#!/usr/bin/env bats
# Which tailscale repo file a base image asks for (tunaOS#1555).
#
# Tailscale publishes one version-independent repo file for Fedora and one per
# EL major for CentOS. 20-packages.sh picked between them using
# MAJOR_VERSION_NUMBER, which is `${VERSION_ID%.*}` from os-release — not
# always an EL major. Hummingbird versions by datestamp, so this asked for
#
#   https://pkgs.tailscale.com/stable/centos/20251124/tailscale.repo
#
# which 404s (verbatim in #1555's evidence). The old guard only asked "is it
# digits", and a datestamp is digits.
#
# Nothing failed: every step in that block ends in `|| true`, so tailscale was
# simply absent from Hummingbird images with no signal. That is the part worth
# testing — a build that goes green while dropping a package is harder to
# notice than one that goes red.
#
# The selection is pure string logic, so these run it for real rather than
# grepping for it. Extracted from the script so the test cannot drift from it.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
PKGS_SH="${REPO_ROOT}/build_scripts/20-packages.sh"

# Run the selection block with the inputs a given base would supply, and print
# the URL it chose (empty = deliberately skipped).
select_url() { # IS_FEDORA IS_HUMMINGBIRD MAJOR_VERSION_NUMBER
  local block
  block="$(awk '/^ts_repo_url=""$/{f=1} f{print} f && /^fi$/{exit}' "$PKGS_SH")"
  [ -n "$block" ] || { echo "COULD-NOT-EXTRACT"; return 1; }
  IS_FEDORA="$1" IS_HUMMINGBIRD="$2" MAJOR_VERSION_NUMBER="$3" \
    bash -c "$block"'; printf "%s" "$ts_repo_url"' 2>/dev/null
}

@test "the selection block is extractable (guards against a silent no-op test)" {
  run select_url false false 10
  [ "$output" != "COULD-NOT-EXTRACT" ]
  [ -n "$output" ]
}

@test "an EL major picks that major's centos repo" {
  run select_url false false 10
  [ "$output" = "https://pkgs.tailscale.com/stable/centos/10/tailscale.repo" ]
  run select_url false false 9
  [ "$output" = "https://pkgs.tailscale.com/stable/centos/9/tailscale.repo" ]
}

@test "Fedora picks the version-independent fedora repo" {
  run select_url true false 44
  [ "$output" = "https://pkgs.tailscale.com/stable/fedora/tailscale.repo" ]
}

@test "Hummingbird picks the fedora repo, not a centos one built from its datestamp" {
  # The regression. IS_FEDORA is deliberately false for Hummingbird (lib.sh
  # excludes it so Bonito's Fedora-specific paths don't fire), so it has to be
  # named here — folding it into IS_FEDORA would change unrelated behaviour.
  run select_url false true 20251124
  [ "$output" = "https://pkgs.tailscale.com/stable/fedora/tailscale.repo" ]
}

@test "a datestamp on a non-Fedora base skips rather than requesting a 404" {
  # Belt and braces for a future base that versions by date and is not
  # Hummingbird: ask for nothing rather than a URL known not to exist.
  run select_url false false 20251124
  [ -z "$output" ]
}

@test "an unset or non-numeric version skips rather than guessing a major" {
  # The previous code defaulted to 10 here, which is a guess that happens to
  # 200 for EL bases and silently installs the wrong repo for anything else.
  run select_url false false ""
  [ -z "$output" ]
  run select_url false false "rawhide"
  [ -z "$output" ]
}

@test "the fetch is conditional on having chosen a URL" {
  # Without this the old unconditional `curl … || true` shape could come back
  # and re-hide the failure.
  run grep -F 'if [[ -n "$ts_repo_url" ]]; then' "$PKGS_SH"
  [ "$status" -eq 0 ]
}

@test "a failed fetch says so instead of failing silently" {
  run grep -F 'could not fetch' "$PKGS_SH"
  [ "$status" -eq 0 ]
}
