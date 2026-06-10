#!/usr/bin/env bats
# Unit tests for scripts/_registry.sh — registry reference resolution
#
# Coverage targets:
#   - _registry_host() with default yq lookup
#   - _registry_host() with TUNA_REGISTRY_<key> env override
#   - registry_ref() basic resolution (host/path/tag)
#   - registry_ref() with explicit tag/digest spec
#   - registry_ref() with no tag (akmods base-path pattern)
#   - registry_ref() with TUNA_IMAGE_PATH_<name> override
#   - registry_ref() with TUNA_IMAGE_TAG_<name> override
#   - registry_ref() with TUNA_REGISTRY_<key> host override
#   - registry_ref() error on unknown image name
#   - Auto-export of COMMON_IMAGE, BREW_IMAGE, BASE_IMAGE
#   - Pre-existing env vars suppress auto-export

setup() {
	TEST_ROOT="$(mktemp -d)"
	export TEST_ROOT

	# Create a minimal registry-map.yaml for testing
	cat >"${TEST_ROOT}/registry-map.yaml" <<'YAML'
registries:
  ghcr: "ghcr.io"
  quay: "quay.io"
  docker: "docker.io"
images:
  common:
    registry: ghcr
    path: projectbluefin/common
    tag: latest
  brew:
    registry: ghcr
    path: ublue-os/brew
    tag: latest
  akmods:
    registry: ghcr
    path: ublue-os
  almalinux-bootc:
    registry: quay
    path: almalinuxorg/almalinux-bootc
    tag: "10"
  centos-bootc:
    registry: quay
    path: centos-bootc/centos-bootc
    tag: stream10
  novnc:
    registry: ghcr
    path: novnc/novnc
    tag: latest
YAML

	# Create stub directory
	mkdir -p "${TEST_ROOT}/usr/bin"

	# Stub yq — mimics yq -r "<yq-expr>" <file> for registry queries
	cat >"${TEST_ROOT}/usr/bin/yq" <<'YQ'
#!/usr/bin/env bash
set -euo pipefail
# Skip -r flag if present
if [[ "${1:-}" == "-r" ]]; then
	shift
fi
_jq_expr="${1:-}"
shift 2>/dev/null || true
_yaml_file="${1:-}"

case "${_jq_expr}" in
	*".registries."*)
		_key="${_jq_expr#*.registries.\"}"
		_key="${_key%%\"*}"
		case "${_key}" in
			ghcr)   echo "ghcr.io" ;;
			quay)   echo "quay.io" ;;
			docker) echo "docker.io" ;;
			*)      echo "null" ;;
		esac
		;;
	*".images."*".registry"*)
		_name="${_jq_expr#*.images.\"}"
		_name="${_name%%\"*}"
		case "${_name}" in
			common)          echo "ghcr" ;;
			brew)            echo "ghcr" ;;
			akmods)          echo "ghcr" ;;
			almalinux-bootc) echo "quay" ;;
			centos-bootc)    echo "quay" ;;
			novnc)           echo "ghcr" ;;
			*)               echo "null" ;;
		esac
		;;
	*".images."*".path"*)
		_name="${_jq_expr#*.images.\"}"
		_name="${_name%%\"*}"
		case "${_name}" in
			common)          echo "projectbluefin/common" ;;
			brew)            echo "ublue-os/brew" ;;
			akmods)          echo "ublue-os" ;;
			almalinux-bootc) echo "almalinuxorg/almalinux-bootc" ;;
			centos-bootc)    echo "centos-bootc/centos-bootc" ;;
			novnc)           echo "novnc/novnc" ;;
			*)               echo "null" ;;
		esac
		;;
	*".images."*".tag"*)
		_name="${_jq_expr#*.images.\"}"
		_name="${_name%%\"*}"
		case "${_name}" in
			common)          echo "latest" ;;
			brew)            echo "latest" ;;
			akmods)          echo "" ;;
			almalinux-bootc) echo "10" ;;
			centos-bootc)    echo "stream10" ;;
			novnc)           echo "latest" ;;
			*)               echo "null" ;;
		esac
		;;
	*)
		echo "null"
		;;
esac
YQ
	chmod +x "${TEST_ROOT}/usr/bin/yq"

	# Stub realpath
	cat >"${TEST_ROOT}/usr/bin/realpath" <<'REALPATH'
#!/usr/bin/env bash
echo "${1}"
REALPATH
	chmod +x "${TEST_ROOT}/usr/bin/realpath"

	# Prepend stubs to PATH
	export PATH="${TEST_ROOT}/usr/bin:${PATH}"

	# Copy _registry.sh to the test root structure so BASH_SOURCE resolution works
	mkdir -p "${TEST_ROOT}/scripts"
	cp "$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)/scripts/_registry.sh" "${TEST_ROOT}/scripts/_registry.sh"
}

teardown() {
	rm -rf "${TEST_ROOT}"
}

# ── Helpers ──────────────────────────────────────────────────────────────────

# Source _registry.sh in a subshell with suppressed auto-exports, then
# call the specified function. All function arguments are forwarded.
# Extra env vars are passed through to the subshell.
run_with_registry() {
	local func="$1"
	shift
	(
		cd "${TEST_ROOT}"
		# Pre-set exports so the auto-export block is skipped
		COMMON_IMAGE="__suppress__"
		BREW_IMAGE="__suppress__"
		BASE_IMAGE="__suppress__"
		export COMMON_IMAGE BREW_IMAGE BASE_IMAGE

		# shellcheck disable=SC1091
		source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null

		"${func}" "$@"
	)
}

# ═══════════════════════════════════════════════════════════════════════════════
# _registry_host() tests
# ═══════════════════════════════════════════════════════════════════════════════

@test "_registry_host: resolves ghcr → ghcr.io" {
	result="$(run_with_registry _registry_host "ghcr")"
	[[ "${result}" == "ghcr.io" ]]
}

@test "_registry_host: resolves quay → quay.io" {
	result="$(run_with_registry _registry_host "quay")"
	[[ "${result}" == "quay.io" ]]
}

@test "_registry_host: resolves docker → docker.io" {
	result="$(run_with_registry _registry_host "docker")"
	[[ "${result}" == "docker.io" ]]
}

@test "_registry_host: applies TUNA_REGISTRY_<key> override" {
	result="$(TUNA_REGISTRY_ghcr="mirror.example.com" run_with_registry _registry_host "ghcr")"
	[[ "${result}" == "mirror.example.com" ]]
}

@test "_registry_host: override does not affect other keys" {
	result="$(TUNA_REGISTRY_ghcr="mirror.example.com" run_with_registry _registry_host "quay")"
	[[ "${result}" == "quay.io" ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# registry_ref() — basic resolution
# ═══════════════════════════════════════════════════════════════════════════════

@test "registry_ref: resolves common → ghcr.io/projectbluefin/common:latest" {
	result="$(run_with_registry registry_ref "common")"
	[[ "${result}" == "ghcr.io/projectbluefin/common:latest" ]]
}

@test "registry_ref: resolves brew → ghcr.io/ublue-os/brew:latest" {
	result="$(run_with_registry registry_ref "brew")"
	[[ "${result}" == "ghcr.io/ublue-os/brew:latest" ]]
}

@test "registry_ref: resolves almalinux-bootc → quay.io/almalinuxorg/almalinux-bootc:10" {
	result="$(run_with_registry registry_ref "almalinux-bootc")"
	[[ "${result}" == "quay.io/almalinuxorg/almalinux-bootc:10" ]]
}

@test "registry_ref: resolves centos-bootc → quay.io/centos-bootc/centos-bootc:stream10" {
	result="$(run_with_registry registry_ref "centos-bootc")"
	[[ "${result}" == "quay.io/centos-bootc/centos-bootc:stream10" ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# registry_ref() — explicit tag/digest spec
# ═══════════════════════════════════════════════════════════════════════════════

@test "registry_ref: explicit tag spec overrides default tag" {
	result="$(run_with_registry registry_ref "common" ":v2.0")"
	[[ "${result}" == "ghcr.io/projectbluefin/common:v2.0" ]]
}

@test "registry_ref: digest spec replaces tag" {
	result="$(run_with_registry registry_ref "common" "@sha256:abc123")"
	[[ "${result}" == "ghcr.io/projectbluefin/common@sha256:abc123" ]]
}

@test "registry_ref: explicit tag on image without default tag" {
	result="$(run_with_registry registry_ref "akmods" ":custom-tag")"
	[[ "${result}" == "ghcr.io/ublue-os:custom-tag" ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# registry_ref() — no-tag images (base path pattern)
# ═══════════════════════════════════════════════════════════════════════════════

@test "registry_ref: akmods returns base path without tag" {
	result="$(run_with_registry registry_ref "akmods")"
	[[ "${result}" == "ghcr.io/ublue-os" ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# registry_ref() — TUNA_IMAGE_PATH_<name> override
# ═══════════════════════════════════════════════════════════════════════════════

@test "registry_ref: TUNA_IMAGE_PATH_<name> overrides default path" {
	result="$(TUNA_IMAGE_PATH_common="myorg/my-fork" run_with_registry registry_ref "common")"
	[[ "${result}" == "ghcr.io/myorg/my-fork:latest" ]]
}

@test "registry_ref: TUNA_IMAGE_PATH_<name> works with explicit tag spec" {
	result="$(TUNA_IMAGE_PATH_brew="myorg/custom-brew" run_with_registry registry_ref "brew" ":v3")"
	[[ "${result}" == "ghcr.io/myorg/custom-brew:v3" ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# registry_ref() — TUNA_IMAGE_TAG_<name> override
# ═══════════════════════════════════════════════════════════════════════════════

@test "registry_ref: TUNA_IMAGE_TAG_<name> overrides default tag" {
	result="$(TUNA_IMAGE_TAG_common="v2.0" run_with_registry registry_ref "common")"
	[[ "${result}" == "ghcr.io/projectbluefin/common:v2.0" ]]
}

@test "registry_ref: explicit tag spec takes precedence over TUNA_IMAGE_TAG_ override" {
	result="$(TUNA_IMAGE_TAG_common="v2.0" run_with_registry registry_ref "common" ":explicit")"
	[[ "${result}" == "ghcr.io/projectbluefin/common:explicit" ]]
}

@test "registry_ref: TUNA_IMAGE_TAG_ override on previously-untagged image adds tag" {
	result="$(TUNA_IMAGE_TAG_akmods="stable" run_with_registry registry_ref "akmods")"
	[[ "${result}" == "ghcr.io/ublue-os:stable" ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# registry_ref() — TUNA_REGISTRY_<key> host override
# ═══════════════════════════════════════════════════════════════════════════════

@test "registry_ref: TUNA_REGISTRY_<key> overrides hostname in full ref" {
	result="$(TUNA_REGISTRY_ghcr="mirror.example.com" run_with_registry registry_ref "common")"
	[[ "${result}" == "mirror.example.com/projectbluefin/common:latest" ]]
}

@test "registry_ref: TUNA_REGISTRY_<key> overrides quay hostname" {
	result="$(TUNA_REGISTRY_quay="quay-mirror.internal" run_with_registry registry_ref "almalinux-bootc")"
	[[ "${result}" == "quay-mirror.internal/almalinuxorg/almalinux-bootc:10" ]]
}

@test "registry_ref: combined path + registry overrides" {
	result="$(TUNA_IMAGE_PATH_common="custom/common" TUNA_REGISTRY_ghcr="mirror.local" run_with_registry registry_ref "common")"
	[[ "${result}" == "mirror.local/custom/common:latest" ]]
}

@test "registry_ref: combined path + tag + registry overrides" {
	result="$(TUNA_IMAGE_PATH_common="custom/common" TUNA_IMAGE_TAG_common="edge" TUNA_REGISTRY_ghcr="mirror.local" run_with_registry registry_ref "common")"
	[[ "${result}" == "mirror.local/custom/common:edge" ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# registry_ref() — error handling
# ═══════════════════════════════════════════════════════════════════════════════

@test "registry_ref: unknown image name returns error" {
	run run_with_registry registry_ref "nonexistent-image"
	[[ "${status}" -eq 1 ]]
	[[ "${output}" == *"unknown image name"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# registry_ref() — novnc
# ═══════════════════════════════════════════════════════════════════════════════

@test "registry_ref: resolves novnc → ghcr.io/novnc/novnc:latest" {
	result="$(run_with_registry registry_ref "novnc")"
	[[ "${result}" == "ghcr.io/novnc/novnc:latest" ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# Auto-export behavior
# ═══════════════════════════════════════════════════════════════════════════════

@test "auto-export: exports COMMON_IMAGE when not pre-set" {
	result="$(
		cd "${TEST_ROOT}"
		BREW_IMAGE="__suppress__"
		BASE_IMAGE="__suppress__"
		export BREW_IMAGE BASE_IMAGE
		unset COMMON_IMAGE

		# shellcheck disable=SC1091
		source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
		echo "${COMMON_IMAGE}"
	)"
	[[ "${result}" == "ghcr.io/projectbluefin/common:latest" ]]
}

@test "auto-export: respects pre-existing COMMON_IMAGE" {
	result="$(
		cd "${TEST_ROOT}"
		COMMON_IMAGE="pre-existing/value:v1"
		BREW_IMAGE="__suppress__"
		BASE_IMAGE="__suppress__"
		export COMMON_IMAGE BREW_IMAGE BASE_IMAGE

		# shellcheck disable=SC1091
		source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
		echo "${COMMON_IMAGE}"
	)"
	[[ "${result}" == "pre-existing/value:v1" ]]
}

@test "auto-export: exports BASE_IMAGE as almalinux-bootc reference" {
	result="$(
		cd "${TEST_ROOT}"
		COMMON_IMAGE="__suppress__"
		BREW_IMAGE="__suppress__"
		export COMMON_IMAGE BREW_IMAGE
		unset BASE_IMAGE

		# shellcheck disable=SC1091
		source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
		echo "${BASE_IMAGE}"
	)"
	[[ "${result}" == "quay.io/almalinuxorg/almalinux-bootc:10" ]]
}

@test "auto-export: exports BREW_IMAGE" {
	result="$(
		cd "${TEST_ROOT}"
		COMMON_IMAGE="__suppress__"
		BASE_IMAGE="__suppress__"
		export COMMON_IMAGE BASE_IMAGE
		unset BREW_IMAGE

		# shellcheck disable=SC1091
		source "${TEST_ROOT}/scripts/_registry.sh" 2>/dev/null
		echo "${BREW_IMAGE}"
	)"
	[[ "${result}" == "ghcr.io/ublue-os/brew:latest" ]]
}
