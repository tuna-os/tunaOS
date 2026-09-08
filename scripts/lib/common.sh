#!/usr/bin/env bash
# scripts/lib/common.sh — shared helpers sourced by scripts/build-*.sh and
# friends. Not meant to be executed directly.
#
# Pulls together the four bits of boilerplate that every build script was
# re-implementing in slightly different ways:
#   1. cd to the repo root so paths are reliable
#   2. detect host arch → podman --platform string
#   3. resolve a (variant, flavor, repo) tuple into an OCI image reference
#   4. import a localhost/* image from the invoking user's storage into
#      root podman storage (sudo'd build scripts need this)
#
# Source style:
#   #!/usr/bin/env bash
#   set -euo pipefail
#   # shellcheck source=lib/common.sh
#   . "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
#
# Then the script just calls the helpers below. The caller is responsible
# for `set -euo pipefail`; libraries shouldn't leak shell options into
# their caller's environment.

# Move to the repo root. We use this file's own path (always at
# scripts/lib/common.sh under the repo root) rather than $BASH_SOURCE[1]
# — the latter is empty when sourced from an interactive shell and would
# crash under `set -u` before the caller's `cd` could run.
_TUNAOS_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$_TUNAOS_REPO_ROOT" || {
	echo "ERROR: cannot enter repo root ${_TUNAOS_REPO_ROOT}" >&2
	exit 1
}

# Compatibility facade: existing callers retain these helpers while focused
# consumers can source the side-effect-free flavor contract directly.
# shellcheck source=flavor.sh
. "$(dirname "${BASH_SOURCE[0]}")/flavor.sh"

# ── Image-ref resolution ────────────────────────────────────────────────────
# Given (variant, flavor, repo, tag) → OCI image reference string.
# `repo` is one of: local | ghcr | registry
# `tag` defaults to the flavor name.
# If `variant` already looks like a ref (contains `:` or `/`) it's returned
# as-is so callers can pass `ghcr.io/foo/bar:tag` directly.
# Implementation provided by the side-effect-free image library.
# shellcheck source=image.sh
. "$(dirname "${BASH_SOURCE[0]}")/image.sh"

# ── Cross-storage image import ──────────────────────────────────────────────
# Some scripts run via `sudo` (e.g. build-iso-tacklebox.sh)
# which uses root's podman storage, while developers usually build images
# into their unprivileged user's storage. This helper copies the image over
# without re-pulling from the registry.
#
# Returns 0 if the image now exists in root storage (or was already there),
# non-zero otherwise.
# Implementation provided by the side-effect-free storage library.
# shellcheck source=storage.sh
. "$(dirname "${BASH_SOURCE[0]}")/storage.sh"

# ── Flavor → human title ────────────────────────────────────────────────────
# Render a flavor id (e.g. "gnome-nvidia-hwe") into the title shown in the
# systemd-boot menu of a grouped ISO (e.g. "GNOME (NVIDIA, HWE)"). Keeping the
# The compatibility import above keeps boot-menu labels consistent for legacy
# common.sh consumers.
# Implementation provided by scripts/lib/flavor.sh.

# ── Desktop session for a flavor ────────────────────────────────────────────
# The side-effect-free flavor library owns the desktop-session mapping.
# Implementation provided by scripts/lib/flavor.sh.

# ── tacklebox runner ───────────────────────────────────────
# shellcheck source=lib/tacklebox.sh
. "${_TUNAOS_REPO_ROOT}/scripts/lib/tacklebox.sh"

# Compatibility facade: existing consumers retain the backend-probe API while
# focused consumers can avoid common.sh's repository-root cwd change.
# shellcheck source=backend.sh
. "$(dirname "${BASH_SOURCE[0]}")/backend.sh"
