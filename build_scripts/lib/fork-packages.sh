#!/usr/bin/env bash

# Opt-in fork delta adapter. Sourcing this module never changes the image.
# Call after legacy packages and before the desktop runtime contract, with
# lib.sh's pkg_install/pkg_refresh wrappers already loaded. The root argument
# redirects receipt/repository files only; tests must also stub those wrappers.

_tunaos_fork_packages_error() {
	printf 'fork packages: %s\n' "$*" >&2
	return 1
}

_tunaos_fork_package_refresh() (
	if [[ "$PKG_MGR" == apt ]]; then
		# shellcheck disable=SC2329
		apt-get() {
			command apt-get -o APT::Update::Error-Mode=any -o Acquire::AllowInsecureRepositories=false \
				-o Acquire::AllowDowngradeToInsecureRepositories=false "$@"
		}
	fi
	pkg_refresh
)

_tunaos_fork_package_install() (
	if [[ "$PKG_MGR" == apt ]]; then
		local refresh_failed=0 install_failed=0
		# Legacy pkg_install does not propagate its initial update failure.
		# A scoped guard prevents every install/retry after a failed refresh.
		# shellcheck disable=SC2329
		apt-get() {
			if [[ "${1:-}" == update ]]; then
				command apt-get -o APT::Update::Error-Mode=any -o Acquire::AllowInsecureRepositories=false \
					-o Acquire::AllowDowngradeToInsecureRepositories=false "$@" || {
					refresh_failed=1
					return 1
				}
			elif [[ "${1:-}" == install ]]; then
				((refresh_failed == 0 && install_failed == 0)) || return 1
				command apt-get --no-remove -o APT::Get::AllowUnauthenticated=false "$@" || {
					install_failed=1
					return 1
				}
			else
				return 1
			fi
		}
		# Never inherit lib.sh forced dependency recovery for fork intent.
		# shellcheck disable=SC2329
		dpkg() { return 1; }
	fi
	local status=0
	pkg_install "$@" || status=$?
	# Repository verification failures are fatal even for optional packages.
	if [[ "$PKG_MGR" == apt ]] && ((refresh_failed != 0)); then return 78; fi
	return "$status"
)

_tunaos_validate_fork_packages() {
	local manifest="$1" manager="$2"
	local package_pattern='^[A-Za-z0-9][A-Za-z0-9+_.-]*$'
	case "$manager" in
	dnf | zypper | pacman) ;;
	apt) package_pattern='^[a-z0-9][a-z0-9+.-]*$' ;;
	emerge) package_pattern='^[A-Za-z0-9][A-Za-z0-9+_.-]*/[A-Za-z0-9][A-Za-z0-9+_.-]*$' ;;
	*)
		_tunaos_fork_packages_error "unsupported package manager '$manager'"
		return 1
		;;
	esac

	# Do not pass an option, a URL, a local archive, a wildcard, a manager
	# expression, or an injected repository directive to the legacy adapters.
	# The host compiler applies the same subset before starting the build.
	if ! jq -e --arg manager "$manager" --arg pattern "$package_pattern" '
		def token: type == "string" and test("^[a-z0-9][a-z0-9_-]*$\\z");
		def digest: type == "string" and test("^[0-9a-f]{64}$\\z");
		def https: type == "string" and
			test("^https://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?(/[A-Za-z0-9._~%+,:=@/-]*)?$\\z");
		def names: type == "array" and all(.[];
			type == "string" and test($pattern + "\\z") and
			(test("\\.(rpm|deb|udeb|ebuild|tbz2|gpkg\\.tar|pkg\\.tar(\\.[a-z0-9]+)?)$"; "i") | not));
		type == "object" and
		(keys == ["assets", "flavor", "image", "intent", "package_manager", "platform", "schema_version", "sources", "variant"]) and
		.schema_version == 1 and
		(.image | type == "object" and keys == ["namespace", "registry"] and
			(.registry | type == "string" and test("^[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?$\\z") and
				(if contains(":") then split(":")[-1] | tonumber | . >= 1 and . <= 65535 else true end)) and
			(.namespace | type == "string" and test("^[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*$\\z"))) and
		(.variant | token) and (.flavor | token) and
		(.platform | type == "string" and test("^linux/(amd64|arm64)(/v[0-9]+)?$\\z")) and
		.package_manager == $manager and
		(.sources | type == "object" and keys == ["sha256"] and (.sha256 | digest)) and
		(.assets | type == "object") and
		(.intent | type == "object" and keys == ["branding", "packages"]) and
		(.intent.branding | type == "object") and
		(.intent.packages |
			type == "object" and keys == ["add", "optional", "remove", "repositories"] and
			(.add | names) and (.optional | names) and (.remove | names) and
			([.add[], .optional[], .remove[]] | length == (unique | length)) and
			(.repositories | type == "array" and all(.[];
				type == "object" and (.id | token) and (.url | https) and (.key_url | https) and
				(if .type == "apt" then
					$manager == "apt" and keys == ["components", "id", "key_sha256", "key_url", "suites", "type", "url"] and
					(.key_sha256 | digest) and
					([.suites, .components] | all(.[]; type == "array" and length > 0 and
						length == (unique | length) and all(.[]; type == "string" and test("^[a-z0-9][a-z0-9+._-]*$\\z"))))
				else keys == ["id", "key_url", "url"] end)) and
				(map(.id) | length == (unique | length))))
	' "$manifest" >/dev/null; then
		_tunaos_fork_packages_error "invalid generated manifest or package syntax: $manifest"
		return 1
	fi

	if [[ "$manager" == apt ]] && ! jq -e '.intent.packages.repositories | all(.[]; .type == "apt")' "$manifest" >/dev/null; then
		_tunaos_fork_packages_error 'repositories are unsupported for apt without type, suites, components and key_sha256'
		return 1
	fi

	# Eligibility is source-controlled and shared with config preview.
	if [[ $(jq '.intent.packages.remove | length' "$manifest") != 0 ]]; then
		python3 "$(dirname "${BASH_SOURCE[0]}")/fork-optional-removals.py" validate --manifest "$manifest" || {
			_tunaos_fork_packages_error 'removals are unsupported for this intent'
			return 1
		}
	fi
	if [[ $(jq '.intent.packages.repositories | length' "$manifest") != 0 && "$manager" != dnf && "$manager" != zypper && "$manager" != apt ]]; then
		_tunaos_fork_packages_error "repositories are unsupported for '$manager'; v1 has no family-specific trust/source contract"
		return 1
	fi
}

tunaos_apply_fork_packages() {
	local context="${1:-/run/context}" root="${2:-/}"
	local manifest="${context}/manifests/fork-config.json"
	# Stock builds must not acquire a jq dependency, create state or run a
	# package manager merely because the adapter was sourced/called.
	[[ -e "$manifest" || -L "$manifest" ]] || return 0
	[[ -f "$manifest" && ! -L "$manifest" ]] || {
		_tunaos_fork_packages_error 'generated manifest must be a regular file, not a symlink'
		return 1
	}
	[[ "$root" == /* && -d "$root" ]] || {
		_tunaos_fork_packages_error 'receipt root must be an existing absolute directory'
		return 1
	}
	command -v jq >/dev/null 2>&1 || {
		_tunaos_fork_packages_error 'jq is required for a generated fork manifest'
		return 1
	}
	_tunaos_validate_fork_packages "$manifest" "${PKG_MGR:-}" || return 1

	local variant flavor platform expected_variant receipt_dir receipt digest canonical architecture
	variant=$(jq -r '.variant' "$manifest")
	flavor=$(jq -r '.flavor' "$manifest")
	platform=$(jq -r '.platform' "$manifest")
	expected_variant="${IMAGE_NAME_VARIANT:-${IMAGE_NAME:-}}"
	if [[ -z "$expected_variant" || "$variant" != "$expected_variant" ]]; then
		_tunaos_fork_packages_error "manifest variant '$variant' differs from image '$expected_variant'"
		return 1
	fi
	if [[ -z "${TUNAOS_IMAGE_FLAVOR:-}" || "$flavor" != "$TUNAOS_IMAGE_FLAVOR" ]]; then
		_tunaos_fork_packages_error "manifest flavor '$flavor' differs from image '${TUNAOS_IMAGE_FLAVOR:-}'"
		return 1
	fi
	architecture=$(uname -m) || return 1
	case "$platform:$architecture" in
	linux/amd64:x86_64 | linux/amd64/v2:x86_64 | linux/arm64:aarch64) ;;
	*)
		_tunaos_fork_packages_error "manifest platform '$platform' differs from running architecture '$architecture'"
		return 1
		;;
	esac
	canonical=$(jq -cS . "$manifest") || return 1
	digest=$(printf '%s' "$canonical" | sha256sum) || return 1
	digest="${digest%% *}"
	receipt_dir="${root%/}/usr/share/tunaos/fork-config/packages"
	receipt="${receipt_dir}/${variant}--${flavor}--${platform//\//-}.json"
	if [[ -e "$receipt" || -L "$receipt" ]]; then
		[[ -f "$receipt" && ! -L "$receipt" ]] || {
			_tunaos_fork_packages_error "receipt must be a regular file, not a symlink: $receipt"
			return 1
		}
		if jq -e --arg digest "$digest" --arg manager "$PKG_MGR" \
			'.status == "complete" and .manifest_sha256 == $digest and .package_manager == $manager' \
			"$receipt" >/dev/null; then
			printf 'fork packages: already applied for %s:%s (%s)\n' "$variant" "$flavor" "$platform"
			return 0
		fi
		_tunaos_fork_packages_error "existing receipt differs or is incomplete: $receipt"
		return 1
	fi

	local removal_count receipt_status=complete
	removal_count=$(jq '.intent.packages.remove | length' "$manifest") || return 1
	if ((removal_count > 0)); then
		# Keep the baseline hash in this shell, outside files later package scripts
		# can rewrite. Interrupted pending work cannot be resumed in a new shell.
		mkdir -p "$receipt_dir" || return 1
		TUNAOS_FORK_REMOVAL_BASELINE="${receipt}.baseline.json"
		TUNAOS_FORK_REMOVAL_BASELINE_SHA256=$(python3 "$(dirname "${BASH_SOURCE[0]}")/fork-optional-removals.py" capture \
			--manifest "$manifest" --baseline "$TUNAOS_FORK_REMOVAL_BASELINE" --root "$root") || return 1
		TUNAOS_FORK_REMOVAL_MANIFEST_SHA256="$digest"
		TUNAOS_FORK_REMOVAL_PACKAGE_RECEIPT="$receipt"
		receipt_status=pending-removal
	fi

	local -a required=() optional=() optional_installed=() optional_missing=()
	mapfile -t required < <(jq -r '.intent.packages.add[]' "$manifest")
	mapfile -t optional < <(jq -r '.intent.packages.optional[]' "$manifest")
	local count index repo_id repo_url key_url repo_dir repo_path content existing package status
	count=$(jq '.intent.packages.repositories | length' "$manifest")
	if ((${#required[@]} + ${#optional[@]} + count > 0)); then
		if ! declare -F pkg_refresh >/dev/null || ! declare -F pkg_install >/dev/null; then
			_tunaos_fork_packages_error 'source lib.sh before applying package intent'
			return 1
		fi
		if [[ "$PKG_MGR" == dnf && "$count" != 0 ]] && ! declare -F dnf_retry >/dev/null; then
			_tunaos_fork_packages_error 'source lib.sh for noninteractive signed dnf repository refresh'
			return 1
		fi
	fi

	# Namespace every repository; never overwrite a legacy source. Both RPM
	# adapters require package AND metadata signatures for this narrow opt-in.
	# A source that lacks signed metadata must fail, not disable verification.
	if ((count > 0)) && [[ "$PKG_MGR" == apt ]]; then
		# The family adapter stages all keys/files before committing any source.
		source "$(dirname "${BASH_SOURCE[0]}")/fork-apt-repositories.sh" || return 1
		tunaos_fork_apt_repositories "$manifest" "$root" || return 1
	elif ((count > 0)); then
		case "$PKG_MGR" in
		dnf) repo_dir="${root%/}/etc/yum.repos.d" ;;
		zypper) repo_dir="${root%/}/etc/zypp/repos.d" ;;
		esac
		# Preflight every collision before writing any repository file.
		for ((index = 0; index < count; index++)); do
			repo_id=$(jq -r ".intent.packages.repositories[$index].id" "$manifest")
			repo_url=$(jq -r ".intent.packages.repositories[$index].url" "$manifest")
			key_url=$(jq -r ".intent.packages.repositories[$index].key_url" "$manifest")
			content=$(printf '[fork-%s]\nname=Fork %s\nbaseurl=%s\nenabled=1\ngpgcheck=1\nrepo_gpgcheck=1\ngpgkey=%s\n' \
				"$repo_id" "$repo_id" "$repo_url" "$key_url")
			if [[ "$PKG_MGR" == zypper ]]; then content+=$'\npkg_gpgcheck=1\nautorefresh=1'; fi
			repo_path="${repo_dir}/fork-${repo_id}.repo"
			if [[ -e "$repo_path" || -L "$repo_path" ]]; then
				[[ -f "$repo_path" && ! -L "$repo_path" ]] || {
					_tunaos_fork_packages_error "repository path is not a regular file: $repo_path"
					return 1
				}
				existing=$(cat "$repo_path") || return 1
				[[ "$existing" == "$content" ]] || {
					_tunaos_fork_packages_error "refusing to replace existing repository: $repo_path"
					return 1
				}
			fi
		done
		mkdir -p "$repo_dir" || return 1
		for ((index = 0; index < count; index++)); do
			repo_id=$(jq -r ".intent.packages.repositories[$index].id" "$manifest")
			repo_url=$(jq -r ".intent.packages.repositories[$index].url" "$manifest")
			key_url=$(jq -r ".intent.packages.repositories[$index].key_url" "$manifest")
			{
				printf '[fork-%s]\nname=Fork %s\nbaseurl=%s\nenabled=1\ngpgcheck=1\nrepo_gpgcheck=1\ngpgkey=%s\n' \
					"$repo_id" "$repo_id" "$repo_url" "$key_url"
				if [[ "$PKG_MGR" == zypper ]]; then printf 'pkg_gpgcheck=1\nautorefresh=1\n'; fi
			} >"${repo_dir}/fork-${repo_id}.repo" || return 1
		done
	fi
	if ((${#required[@]} + ${#optional[@]} + count > 0)); then
		# The fork supplies the trust key URL. Bare dnf makecache prompts on
		# the first metadata-key import; use the existing retry adapter with
		# explicit approval rather than disabling either signature check.
		if [[ "$PKG_MGR" == dnf && "$count" != 0 ]]; then
			dnf_retry -y makecache || {
				_tunaos_fork_packages_error 'signed repository metadata refresh failed'
				return 1
			}
		elif ! _tunaos_fork_package_refresh; then
			_tunaos_fork_packages_error 'repository metadata refresh failed'
			return 1
		fi
	fi
	if ((${#required[@]} > 0)); then
		_tunaos_fork_package_install "${required[@]}" || {
			_tunaos_fork_packages_error 'required package installation failed'
			return 1
		}
	fi
	for package in "${optional[@]}"; do
		if _tunaos_fork_package_install "$package"; then
			optional_installed+=("$package")
		else
			status=$?
			if ((status == 78)); then
				_tunaos_fork_packages_error 'repository refresh failed during optional installation'
				return 1
			fi
			optional_missing+=("$package")
			printf 'fork packages: optional package unavailable: %s\n' "$package" >&2
		fi
	done

	# Only successful required work gets a completed receipt. Optional misses
	# are durable and do not get retried when a second desktop path runs.
	local installed_json missing_json receipt_tmp
	installed_json=$(printf '%s\n' "${optional_installed[@]}" | jq -Rsc 'split("\n") | map(select(length > 0))') || return 1
	missing_json=$(printf '%s\n' "${optional_missing[@]}" | jq -Rsc 'split("\n") | map(select(length > 0))') || return 1
	mkdir -p "$receipt_dir" || return 1
	receipt_tmp=$(mktemp "${receipt}.XXXXXX") || return 1
	if ! jq --arg digest "$digest" --argjson installed "$installed_json" --argjson missing "$missing_json" --arg status "$receipt_status" '
		{schema_version: 1, status: $status, variant, flavor, platform,
		 package_manager, image, manifest_sha256: $digest, sources,
		 repositories: .intent.packages.repositories, remove: [],
		 required_installed: .intent.packages.add,
		 optional_installed: $installed, optional_missing: $missing}
	' "$manifest" >"$receipt_tmp"; then
		rm -f "$receipt_tmp"
		return 1
	fi
	chmod 0644 "$receipt_tmp" && mv "$receipt_tmp" "$receipt" || return 1
	printf 'fork packages: recorded %s\n' "$receipt"
}

# Called only after desktop setup, branding and the normal contract have run.
tunaos_finalize_fork_packages() {
	local context="${1:-/run/context}" desktop="${2:-}" root="${3:-/}"
	local manifest="${context}/manifests/fork-config.json" canonical digest receipt receipt_tmp
	[[ -e "$manifest" || -L "$manifest" ]] || return 0
	_tunaos_validate_fork_packages "$manifest" "${PKG_MGR:-}" || return 1
	[[ $(jq '.intent.packages.remove | length' "$manifest") != 0 ]] || return 0
	canonical=$(jq -cS . "$manifest") || return 1
	digest=$(printf '%s' "$canonical" | sha256sum) || return 1
	digest="${digest%% *}"
	local variant flavor platform
	variant=$(jq -r '.variant' "$manifest") || return 1
	flavor=$(jq -r '.flavor' "$manifest") || return 1
	platform=$(jq -r '.platform' "$manifest") || return 1
	receipt="${root%/}/usr/share/tunaos/fork-config/packages/${variant}--${flavor}--${platform//\//-}.json"
	[[ -f "$receipt" && ! -L "$receipt" ]] || return 1
	if jq -e --arg digest "$digest" '.status == "complete" and .manifest_sha256 == $digest' "$receipt" >/dev/null; then
		# Ubuntu invokes both desktop paths in separate shells. A completed
		# transaction may be checked again, but never resumed or re-executed.
		python3 "$(dirname "${BASH_SOURCE[0]}")/fork-optional-removals.py" verify-complete \
			--manifest "$manifest" --baseline "${receipt}.baseline.json" \
			--receipt "${receipt}.removal.json" --context "$context" --root "$root" --desktop "$desktop"
		return $?
	fi
	[[ "$digest" == "${TUNAOS_FORK_REMOVAL_MANIFEST_SHA256:-}" && -n "${TUNAOS_FORK_REMOVAL_BASELINE_SHA256:-}" ]] || {
		_tunaos_fork_packages_error 'removal baseline must be captured in this build shell before additions'
		return 1
	}
	receipt="$TUNAOS_FORK_REMOVAL_PACKAGE_RECEIPT"
	[[ -f "$receipt" && ! -L "$receipt" ]] || return 1
	jq -e --arg digest "$digest" '.status == "pending-removal" and .manifest_sha256 == $digest' "$receipt" >/dev/null || return 1
	python3 "$(dirname "${BASH_SOURCE[0]}")/fork-optional-removals.py" apply \
		--manifest "$manifest" --baseline "$TUNAOS_FORK_REMOVAL_BASELINE" \
		--baseline-sha256 "$TUNAOS_FORK_REMOVAL_BASELINE_SHA256" \
		--receipt "${receipt}.removal.json" --context "$context" --root "$root" --desktop "$desktop" || return 1
	receipt_tmp=$(mktemp "${receipt}.XXXXXX") || return 1
	if ! jq --slurpfile manifest "$manifest" '.status = "complete" | .remove = $manifest[0].intent.packages.remove' "$receipt" >"$receipt_tmp"; then
		rm -f "$receipt_tmp"
		return 1
	fi
	chmod 0644 "$receipt_tmp" && mv "$receipt_tmp" "$receipt" || return 1
	unset TUNAOS_FORK_REMOVAL_BASELINE_SHA256 TUNAOS_FORK_REMOVAL_MANIFEST_SHA256
}
