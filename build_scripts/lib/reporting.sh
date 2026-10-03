#!/usr/bin/env bash

# Build reporting shared by image build stages: GitHub Actions warnings,
# bootc lint findings, and the package manifest written into the image.
# This module is sourced by build_scripts/lib.sh; keep it free of source-time
# side effects so the compatibility facade remains safe for every consumer.

# Run a command and emit a GitHub Actions ::warning on failure instead of
# silently swallowing the error with || true.  Use for operations that are
# important enough to surface in the build summary but not build-fatal
# (e.g. versionlock changes, optional removes, RHSM registration).
#
# Usage: warn_on_fail subscription-manager register --username "${RHSM_USER}" ...
#        warn_on_fail dnf -y versionlock delete glib2
warn_on_fail() {
	local cmd="$1"
	shift
	if ! "$cmd" "$@"; then
		local caller_script
		caller_script="$(basename "${BASH_SOURCE[1]:-?}")"
		printf '::warning title=Operation failed (%s on %s)::%s %s exited with %d (called from %s)\n' \
			"${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}" "$cmd" "$*" "$?" "$caller_script"
	fi
}

# Run `bootc container lint` and SURFACE its findings instead of silently
# swallowing them. The lint is the product-quality gate for bootc images
# (#272: bonito's three failures were hidden behind `warn_on_fail`, which
# emits a one-line ::warning and discards the actual check output — so nobody
# could see *what* failed, let alone fix it).
#
# Behaviour:
#   * Always runs the lint, capturing combined stdout+stderr.
#   * On failure, echoes the full output inside a collapsed ::group:: and
#     mirrors it into $GITHUB_STEP_SUMMARY so the findings are visible in the
#     run summary, not buried in 10k lines of build log.
#   * Fails the build when BOOTC_LINT_FATAL=1 (default: warn-only, preserving
#     today's behaviour). Flip a variant to fatal once its findings are fixed.
#
# Usage: lint_image            # lints the in-build root (bootc container lint)
lint_image() {
	local fatal="${BOOTC_LINT_FATAL:-0}"
	local out rc=0
	out="$(bootc container lint --fatal-warnings 2>&1)" || rc=$?

	if ((rc == 0)); then
		echo "bootc container lint: OK (${IMAGE_NAME:-?} ${MAJOR_VERSION_NUMBER:-?})"
		return 0
	fi

	# Surface the findings prominently.
	printf '::group::bootc container lint findings (%s %s)\n%s\n::endgroup::\n' \
		"${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}" "$out"

	if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
		local fence='```'
		{
			printf '### ⚠️ bootc container lint — %s %s\n\n' "${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}"
			printf '%s\n%s\n%s\n' "$fence" "$out" "$fence"
		} >>"$GITHUB_STEP_SUMMARY"
	fi

	if [[ "$fatal" == "1" ]]; then
		printf '::error title=bootc lint failed (%s)::lint reported failures (exit %d); see the grouped findings above\n' \
			"${IMAGE_NAME:-?}" "$rc"
		return "$rc"
	fi

	printf '::warning title=bootc lint findings (%s)::lint reported failures (exit %d) — surfaced above, not build-fatal (set BOOTC_LINT_FATAL=1 to enforce)\n' \
		"${IMAGE_NAME:-?}" "$rc"
	return 0
}

# emit_packages_manifest — Write normalized JSON package manifest to /usr/share/tunaos/packages.json
# Usage: emit_packages_manifest
emit_packages_manifest() {
	local img_name="${IMAGE_NAME:-unknown}"
	local img_flavor="${DESKTOP_FLAVOR:-gnome}"
	local pkg_mgr="${PKG_MGR:-unknown}"
	local target_dir="/usr/share/tunaos"
	local target_file="${target_dir}/packages.json"
	local tmp_file="/tmp/packages.json.tmp"

	mkdir -p "${target_dir}"

	local raw_pkgs=""
	if command -v rpm >/dev/null 2>&1; then
		raw_pkgs="$(rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}\n' 2>/dev/null | LC_ALL=C sort -u || true)"
	elif command -v dpkg-query >/dev/null 2>&1; then
		raw_pkgs="$(dpkg-query -W -f '${Package}\t${Version}\n' 2>/dev/null | LC_ALL=C sort -u || true)"
	elif command -v pacman >/dev/null 2>&1; then
		raw_pkgs="$(pacman -Q 2>/dev/null | tr ' ' '\t' | LC_ALL=C sort -u || true)"
	elif command -v qlist >/dev/null 2>&1; then
		raw_pkgs="$(qlist -ICv 2>/dev/null | awk '{
			name=$0;
			sub(/-[0-9].*/, "", name);
			sub(/^[^\/]*\//, "", name);
			ver=$0;
			sub(/^.*-/, "", ver);
			print name "\t" ver;
		}' | LC_ALL=C sort -u || true)"
	fi

	python3 -c '
import json, sys

img_name = sys.argv[1]
img_flavor = sys.argv[2]
pkg_mgr = sys.argv[3]
raw = sys.stdin.read().strip()

packages = []
if raw:
    for line in raw.split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2:
            packages.append({"name": parts[0], "version": parts[1]})
        elif len(parts) == 1 and parts[0]:
            packages.append({"name": parts[0], "version": ""})

manifest = {
    "image": img_name,
    "flavor": img_flavor,
    "pkg_manager": pkg_mgr,
    "count": len(packages),
    "packages": packages
}

with open(sys.argv[4], "w") as f:
    json.dump(manifest, f, indent=2)
' "$img_name" "$img_flavor" "$pkg_mgr" "$tmp_file" < <(printf '%s\n' "$raw_pkgs")

	mv "$tmp_file" "$target_file"
	chmod 0644 "$target_file"
	echo "emit_packages_manifest: wrote $(wc -l <"$target_file") lines to ${target_file}"
}
