#!/usr/bin/env bash

# Compatibility facade for the build library.
#
# Build scripts continue to source this one path. Domain code lives in the
# side-effect-free modules under build_scripts/lib/ so platform detection,
# package transport, service policy, reporting, and override orchestration have
# separate regression boundaries.

set -euo pipefail

# Do not rely on any of these scripts existing in a specific path.
# shellcheck disable=SC2034 # consumed by the sourced orchestration module
CONTEXT_PATH="$(realpath "$(dirname "$0")/..")"
# shellcheck disable=SC2034 # consumed by the sourced orchestration module
BUILD_SCRIPTS_PATH="$(realpath "$(dirname "$0")")"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export SCRIPTS_PATH DESKTOP_FLAVOR

_TUNAOS_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")/lib"

# shellcheck source=build_scripts/lib/platform.sh
source "${_TUNAOS_LIB_DIR}/platform.sh"
# shellcheck source=build_scripts/lib/orchestration.sh
source "${_TUNAOS_LIB_DIR}/orchestration.sh"
# shellcheck source=build_scripts/lib/packages.sh
source "${_TUNAOS_LIB_DIR}/packages.sh"
# shellcheck source=build_scripts/lib/service-policy.sh
source "${_TUNAOS_LIB_DIR}/service-policy.sh"
# shellcheck source=build_scripts/lib/reporting.sh
source "${_TUNAOS_LIB_DIR}/reporting.sh"

# Keep the historical source contract: callers receive the platform flags and
# package-manager selection immediately. Tests and new callers may invoke the
# same explicit initializer again after changing their fixture environment.
initialize_platform
