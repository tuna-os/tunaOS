#!/usr/bin/env bats
# The offline-store probe must not require tooling the GUEST may not ship.
#
# It used to ask two questions, `sudo podman image exists <ref>` and
# `sudo jq -e ... images.json`, both answered inside the live VM. guppy answers
# neither: Containerfile.gentoo emerges app-containers/skopeo for bootc's
# containers-image-proxy and emerges neither podman nor jq, so both probes exit
# 127 and a store that records `ghcr.io/tuna-os/guppy:gnome` verbatim read as
# "image absent". The cell then fell through to the SSH image transfer that
# scripts/iso-e2e.sh itself documents as impossible and died on
#
#   scp: write remote "/home/liveuser/luks-image-guppy-gnome.tar": Failure
#
# 2h30m into the job (guppy:gnome, LUKS run 31134373523).
#
# So the index is read out of the guest with `cat` and parsed on the host. These
# tests drive the real helper out of the script.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/iso-e2e.sh"

# The exact index guppy:gnome's store carried in run 31134373523, trimmed of the
# big-data blobs. Single line, as containers-storage writes it.
STORE_JSON='[{"id":"d94de71ea8e4b7d60214d57261db4d5aef501c39e3bc62dc45721fd8b2660271","digest":"sha256:15c4702d2d1d181ad9ff2811299dc09ca6e5fc364d7bab3791afaeb317d6c2bf","names":["ghcr.io/tuna-os/guppy:gnome"],"names-history":["ghcr.io/tuna-os/guppy:gnome"],"layer":"614327ceb146d4b2a99ac98d2458620c78e4a3f2700d42253fdf42906c84a0fd","created":"2026-08-07T02:31:35.482754018Z"}]'

# Runs store_records_image as shipped, with PATH optionally stripped of jq so
# the no-jq fallback is exercised for real rather than described.
probe() {
	local json="$1" ref="$2" no_jq="${3:-}"
	NO_JQ="$no_jq" bash -c '
		set -Eeuo pipefail
		eval "$(sed -n "/^store_records_image()/,/^}/p" "$1")"
		if [[ -n "${NO_JQ:-}" ]]; then
			# A host without jq. Hiding the binary, not stubbing the call, so
			# the fallback branch is reached the way it would be in the wild.
			command() {
				if [[ "$*" == "-v jq" ]]; then return 1; fi
				builtin command "$@"
			}
		fi
		store_records_image "$2" "$3"
	' _ "$SCRIPT" "$json" "$ref"
}

@test "a ref recorded in the store index is found (jq present)" {
	run probe "$STORE_JSON" "ghcr.io/tuna-os/guppy:gnome"
	[ "$status" -eq 0 ]
}

@test "a ref recorded in the store index is found with no jq on the host" {
	# The degraded path still has to answer, or a bare local run silently
	# reverts to the transfer that cannot work.
	run probe "$STORE_JSON" "ghcr.io/tuna-os/guppy:gnome" strip-jq
	[ "$status" -eq 0 ]
}

@test "a ref the store does not record is not found" {
	run probe "$STORE_JSON" "localhost/guppy:gnome"
	[ "$status" -ne 0 ]
	run probe "$STORE_JSON" "localhost/guppy:gnome" strip-jq
	[ "$status" -ne 0 ]
}

@test "a near-miss ref does not match by substring" {
	# `guppy:gnome` is a suffix of the recorded name, and a bare grep for it
	# would say yes. bootc would then be handed a ref containers-storage
	# cannot resolve.
	run probe "$STORE_JSON" "guppy:gnome"
	[ "$status" -ne 0 ]
	run probe "$STORE_JSON" "guppy:gnome" strip-jq
	[ "$status" -ne 0 ]
}

@test "a ref only in names-history does not count as recorded" {
	# containers-storage resolves current names only; a retagged-away ref is a
	# different dead end, not a shortcut.
	local retagged
	retagged='[{"id":"abc","names":["ghcr.io/tuna-os/guppy:base"],"names-history":["ghcr.io/tuna-os/guppy:gnome","ghcr.io/tuna-os/guppy:base"]}]'
	run probe "$retagged" "ghcr.io/tuna-os/guppy:gnome"
	[ "$status" -ne 0 ]
	run probe "$retagged" "ghcr.io/tuna-os/guppy:gnome" strip-jq
	[ "$status" -ne 0 ]
}

@test "an entry with a null names array does not abort the probe" {
	# containers-storage writes names:null for an untagged image. jq's
	# `.names | index(...)` errors on null, which would take the whole probe
	# down with it and lose the tagged entry beside it.
	local mixed
	mixed='[{"id":"aaa","names":null},{"id":"bbb","names":["ghcr.io/tuna-os/guppy:gnome"]}]'
	run probe "$mixed" "ghcr.io/tuna-os/guppy:gnome"
	[ "$status" -eq 0 ]
}

@test "an unreadable/empty index is not found, and does not error out" {
	run probe "" "ghcr.io/tuna-os/guppy:gnome"
	[ "$status" -eq 1 ]
	run probe "$STORE_JSON" ""
	[ "$status" -eq 1 ]
}

@test "the probe does not ask the guest for jq or podman" {
	# The regression itself: any guest-side `jq` in the probe re-introduces a
	# dependency guppy cannot satisfy, and does it silently.
	local body
	body="$(sed -n '/^store_records_image()/,/^}/p' "$SCRIPT")"
	[ -n "$body" ]
	run grep -qE 'ssh_cmd|sudo ' <<<"$body"
	[ "$status" -ne 0 ]
	# ...and nowhere else in the script either: the guest-side `sudo jq` this
	# replaced was the only one, so "no guest jq at all" is an assertion the
	# script can actually hold. Comments stripped, or the note explaining the
	# removal would satisfy the check it exists to make.
	local code
	code="$(sed 's/^[[:space:]]*#.*//' "$SCRIPT")"
	run grep -nE 'sudo[^|]*\bjq\b' <<<"$code"
	[ "$status" -ne 0 ]
}

@test "the store index is read from the guest with cat, not parsed there" {
	run grep -qE 'store_images_json=.*sudo cat' "$SCRIPT"
	[ "$status" -eq 0 ]
}

@test "podman-shaped store queries are gated on the guest having podman" {
	# Otherwise the dump is a dozen 'sudo: podman: command not found' lines and
	# the reader has to infer the cause from an absent 'Found' line.
	run grep -q 'local guest_has_podman=0' "$SCRIPT"
	[ "$status" -eq 0 ]
	run grep -qE 'guest_has_podman.*-eq 1.*&&' "$SCRIPT"
	[ "$status" -eq 0 ]
	# The `podman image exists` probe specifically must be behind the gate.
	run grep -B2 "sudo podman image exists" "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"guest_has_podman"* ]]
}
