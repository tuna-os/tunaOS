#!/usr/bin/env bats
# Hummingbird gets its own manifest section, and that section reuses Fedora's
# package names rather than restating them.
#
# Why its own section: Hummingbird IS a Fedora Rawhide rebuild (30 of 38 core
# packages match Rawhide's version AND release, differing only in the .hum1
# dist tag), so lib.sh's substring test routing it to el10 is a
# misclassification. But `fedora` is equally wrong — of the 58 packages the
# GNOME manifest installs, Hummingbird's 3384-package repository ships exactly
# ONE (avahi). It publishes a base OS and no desktop, so the fedora: section
# fails the same way el10: did, just further along. Measured in
# tuna-os/tunaos-packages#250.
#
# Why an alias and not a copy: the names ARE Fedora's. A second literal list
# across five desktop manifests is how these files drift apart — this repo has
# been bitten repeatedly by a fact true of a CLASS being retyped per file.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
INSTALL="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
GNOME="${REPO_ROOT}/manifests/desktops/gnome.yaml"

yq_bin() { command -v yq; }

@test "install-desktop.sh routes hummingbird to its own OS section" {
	run grep -E 'IS_HUMMINGBIRD.*== true' "$INSTALL"
	[ "$status" -eq 0 ]
	run grep -E '_TD_OS="hummingbird"' "$INSTALL"
	[ "$status" -eq 0 ]
}

# The branch must come BEFORE the IS_FEDORA test. Hummingbird's os-release
# says fedora, so a later branch never runs — the selector is first-match.
@test "the hummingbird branch precedes the fedora branch" {
	local hb fed
	hb=$(grep -n 'IS_HUMMINGBIRD.*== true' "$INSTALL" | head -1 | cut -d: -f1)
	fed=$(grep -n 'IS_FEDORA" == true' "$INSTALL" | head -1 | cut -d: -f1)
	[ -n "$hb" ]
	[ -n "$fed" ]
	[ "$hb" -lt "$fed" ]
}

# hummingbird is dnf-driven. Omitting it from this guard sends a dnf base down
# the list-style path, where indexing a map with .group_options is a hard yq
# error rather than a graceful skip.
@test "hummingbird takes the dnf path" {
	run grep -E '_TD_OS.*==.*"hummingbird".*\]\]; then' "$INSTALL"
	[ "$status" -eq 0 ]
}

@test "gnome.yaml declares a hummingbird repo at the measured target path" {
	[ -n "$(yq_bin)" ] || skip "yq not available"
	run yq -r '.packages.hummingbird.repos[0].baseurl' "$GNOME"
	[ "$status" -eq 0 ]
	[[ "$output" == *"hummingbird/current/\$basearch"* ]]
}

# The assertion this file exists for: the hummingbird package list must BE the
# fedora one, not a copy of it. If someone replaces the alias with a literal
# list, the two drift the first time either is edited and nothing else notices.
@test "hummingbird reuses fedora's package list rather than copying it" {
	[ -n "$(yq_bin)" ] || skip "yq not available"
	local fedora hummingbird
	fedora="$(yq -r '.packages.fedora.packages[]' "$GNOME" | sort)"
	hummingbird="$(yq -r '.packages.hummingbird.packages[]' "$GNOME" | sort)"
	[ -n "$fedora" ]
	[ "$fedora" = "$hummingbird" ]

	# and it is literally an alias in the source, not a duplicated block
	run grep -c 'packages: \*fedora_gnome_packages' "$GNOME"
	[ "$status" -eq 0 ]
	[ "$output" -ge 1 ]
}

# Only gnome is wired on purpose. kde uses `groups:` and niri uses `copr:`,
# and their Hummingbird package sets (384 and 310 sources) do not exist yet —
# inventing sections for repositories that 404 would be guesswork. This test
# records that as a deliberate boundary so its absence is not read as an
# oversight.
@test "only the desktops whose hummingbird packages exist are wired" {
	[ -n "$(yq_bin)" ] || skip "yq not available"
	local d
	for d in kde niri cosmic; do
		run yq -r '.packages.hummingbird // "absent"' "${REPO_ROOT}/manifests/desktops/${d}.yaml"
		[ "$output" = "absent" ] || [ "$output" = "null" ]
	done
}
