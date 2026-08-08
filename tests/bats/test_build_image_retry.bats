#!/usr/bin/env bats
# The whole-image build retries on transient failure, whichever builder is used.
#
# scripts/build-image-inner.sh wraps its `${BUILDER} build` in an until-loop.
# That loop used to bail immediately unless BUILDER was buildah:
#
#     if [[ "${BUILDER}" != "buildah" || "${build_attempt}" -ge 3 ]]; then
#
# The ISO path builds with podman, so every ISO build got zero retries, and
# a base-image pull that died mid-blob against the registry CDN —
#
#     Error: creating build container: copying system image from manifest
#     list: writing blob ...: happened during read: unexpected EOF
#
# — took out LUKS albacore:niri six seconds into run 31135329021. The log line
# is the trap: "image build failed after 1 attempt(s)" reads like a retry that
# ran out, not one that never happened.
#
# These tests drive the loop's logic directly rather than the whole script,
# which needs a container runtime, a git tree and a Containerfile. What is
# under test is the loop, and the loop is what is extracted.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/build-image-inner.sh"

setup() {
	TEST_ROOT="$(mktemp -d)"
}

teardown() {
	rm -rf "${TEST_ROOT}"
}

# The until-loop as it appears in the script: from the `build_attempt=1`
# initialiser through the closing `done`. Extracted rather than restated so a
# future edit to the loop is what these tests run.
retry_loop() {
	awk '/^build_attempt=1$/{f=1} f{print} f&&/^done$/{exit}' "$SCRIPT"
}

# Run the extracted loop with a stub build_primary_image that fails the first
# $1 attempts, then succeeds. Echoes one line per attempt, then the exit code.
# `sleep` is stubbed to nothing so 10s+20s of backoff does not become test time.
run_loop() {
	local fail_count="$1" builder="$2"
	bash -c "
		BUILDER='${builder}'
		attempts=0
		sleep() { :; }
		build_primary_image() {
			attempts=\$((attempts + 1))
			echo \"attempt \$attempts\"
			[ \$attempts -gt ${fail_count} ]
		}
		$(retry_loop)
		echo \"exit 0\"
	" 2>&1
}

@test "the loop was actually extracted from the script" {
	run retry_loop
	[ "$status" -eq 0 ]
	[[ "$output" == *"build_attempt=1"* ]]
	[[ "$output" == *"until build_primary_image"* ]]
	[[ "$output" == *"done"* ]]
	# A one-line extraction would make every test below vacuous.
	[ "$(wc -l <<<"$output")" -ge 6 ]
}

@test "a build that succeeds first time runs exactly once" {
	run run_loop 0 podman
	[[ "$output" == *"attempt 1"* ]]
	[[ "$output" != *"attempt 2"* ]]
	[[ "$output" == *"exit 0"* ]]
}

# The regression. Before the fix this stopped at one attempt and exited 1.
@test "podman retries a transient failure" {
	run run_loop 1 podman
	[[ "$output" == *"attempt 2"* ]]
	[[ "$output" == *"exit 0"* ]]
}

@test "buildah still retries a transient failure" {
	run run_loop 1 buildah
	[[ "$output" == *"attempt 2"* ]]
	[[ "$output" == *"exit 0"* ]]
}

# Three attempts, not unbounded: a genuinely broken build must still fail, and
# fail in bounded time rather than looping on a real error.
@test "a persistently failing build gives up after three attempts" {
	local b
	for b in podman buildah; do
		run run_loop 99 "$b"
		[[ "$output" == *"attempt 3"* ]] || fail "$b did not reach attempt 3"
		[[ "$output" != *"attempt 4"* ]] || fail "$b went past attempt 3"
		[[ "$output" == *"failed after 3 attempt(s)"* ]] ||
			fail "$b did not report exhaustion"
		# `exit 1` inside the loop means the trailing marker never prints.
		[[ "$output" != *"exit 0"* ]] || fail "$b returned success after giving up"
	done
}

# The builder-specific gate is what caused the bug. Assert it is gone from the
# source, so reintroducing it fails here with an explanation rather than
# silently halving the retry coverage again. (A buildah-only storage clean
# inside the loop is fine — see the next test — what must not return is the
# `!= buildah` early-exit that gave podman zero retries.)
@test "the retry is not gated on the builder name" {
	run retry_loop
	[[ "$output" != *'!= "buildah"'* ]]
}

@test "buildah storage is cleaned before a retry, not on first success" {
	cat >"${TEST_ROOT}/buildah" <<'EOF'
#!/usr/bin/env bash
echo "buildah $*" >> "${BUILDAH_LOG:?}"
EOF
	chmod +x "${TEST_ROOT}/buildah"
	export BUILDAH_LOG="${TEST_ROOT}/buildah.log"
	export PATH="${TEST_ROOT}:${PATH}"
	run bash -c "
		BUILDER=buildah
		attempts=0
		sleep() { :; }
		build_primary_image() {
			attempts=\$((attempts + 1))
			[ \$attempts -gt 1 ]
		}
		$(retry_loop)
	"
	[ "$status" -eq 0 ]
	run cat "${BUILDAH_LOG}"
	# exactly one clean, between attempt 1 and attempt 2
	[ "$(wc -l <<<"$output")" -eq 1 ]
	[[ "$output" == *"rm -a"* ]]
}

@test "podman retries do not invoke buildah rm" {
	cat >"${TEST_ROOT}/buildah" <<'EOF'
#!/usr/bin/env bash
echo "buildah called" > "${TEST_ROOT}/buildah.log"
EOF
	chmod +x "${TEST_ROOT}/buildah"
	export PATH="${TEST_ROOT}:${PATH}"
	run bash -c "
		BUILDER=podman
		attempts=0
		sleep() { :; }
		build_primary_image() {
			attempts=\$((attempts + 1))
			[ \$attempts -gt 1 ]
		}
		$(retry_loop)
	"
	[ "$status" -eq 0 ]
	[[ ! -f "${TEST_ROOT}/buildah.log" ]]
}
