#!/usr/bin/env bats
# The manifest package-name checker (tunaOS#1469).
#
# manifests/desktops/pantheon.yaml states the rule and the incident behind it:
# every name was verified published via the Launchpad API, "do not add an
# unverified name here", and "an unresolvable name is what shipped a
# desktop-less image in tunaos-packages#132". The verification was done once by
# hand and nothing re-does it.
#
# scripts/verify-manifest-packages.sh re-does it. The network half cannot run
# here, so these cover the half that decides whether the network half asks the
# right questions: which names get extracted, and which archive they are looked
# up in. A checker that silently parses zero packages would pass forever.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/verify-manifest-packages.sh"
PANTHEON="${REPO_ROOT}/manifests/desktops/pantheon.yaml"

# The script's own package-list parser, lifted so the test cannot drift from it.
parse_pkgs() {
  awk '/^    packages:$/{f=1;next}
       f && /^    - /{n=$2; sub(/#.*/,"",n); gsub(/[ \t]/,"",n); if (n != "") print n}
       f && /^[a-z_]+:$/{exit}' "$1"
}

@test "the script exists, is executable, and is valid bash" {
  [ -x "$SCRIPT" ]
  run bash -n "$SCRIPT"
  [ "$status" -eq 0 ]
}

@test "the parser finds the pantheon manifest's packages" {
  run parse_pkgs "$PANTHEON"
  [ "$status" -eq 0 ]
  [ "$(echo "$output" | wc -l)" -ge 15 ]
}

@test "the parser strips trailing comments from a package line" {
  # Most lines carry an inline comment; a parser that kept them would query
  # Launchpad for "gala#8.5.1—windowmanager/compositor" and get 0 hits for
  # every package, which reads as a catastrophic manifest failure.
  run parse_pkgs "$PANTHEON"
  [[ "$output" == *"gala"* ]]
  [[ "$output" != *"#"* ]]
  [[ "$output" != *"compositor"* ]]
}

@test "the parser stops at the next top-level key" {
  # post_install: follows the package list. Swallowing it would query for
  # script filenames.
  run parse_pkgs "$PANTHEON"
  [[ "$output" != *"tuna-flatpak-remote.sh"* ]]
  [[ "$output" != *"flatpak-preinstall.sh"* ]]
}

@test "the manifest's own documented non-names are absent from the list" {
  # The manifest header lists four names that resolve to nothing
  # (pantheon-desktop, pantheon-session, io.elementary.files,
  # pantheon-session-settings) as a warning. They must stay in prose and out of
  # the package list — this is the exact class of entry #132 shipped.
  run parse_pkgs "$PANTHEON"
  [[ "$output" != *"pantheon-desktop"* ]]
  [[ "$output" != *"pantheon-session"* ]]
  [[ "$output" != *"io.elementary.files"* ]]
}

@test "the PPA spec is derivable from the manifest" {
  run awk '/repo: *"ppa:/{ if (match($0, /ppa:[^"]+/)) print substr($0, RSTART+4, RLENGTH-4); exit }' "$PANTHEON"
  [ "$status" -eq 0 ]
  [ "$output" = "elementary-os/stable" ]
}

@test "an unreadable manifest is an error, not an empty pass" {
  run bash "$SCRIPT" "${BATS_TEST_TMPDIR}/nope.yaml"
  [ "$status" -eq 2 ]
  [[ "$output" == *"cannot read"* ]]
}

@test "a manifest with no packages is an error, not a pass" {
  # The failure this guards: a manifest-format change makes the parser return
  # nothing, and a naive checker reports success having verified zero names.
  local m="${BATS_TEST_TMPDIR}/empty.yaml"
  printf 'display_manager: lightdm\npackages:\n  apt:\n    packages:\n' > "$m"
  run bash "$SCRIPT" "$m"
  [ "$status" -eq 2 ]
  [[ "$output" == *"no apt packages parsed"* ]]
}
