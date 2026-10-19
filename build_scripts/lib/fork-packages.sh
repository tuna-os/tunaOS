#!/usr/bin/env bash

# Opt-in fork delta adapter. Sourcing this module never changes the image.
# Call after legacy packages and before the desktop runtime contract, with
# lib.sh's pkg_install/pkg_refresh wrappers already loaded. The root argument
# redirects receipt/repository files only; tests must also stub those wrappers.

_tunaos_fork_packages_error() {
	printf 'fork packages: %s\n' "$*" >&2
	return 1
}

_tunaos_fork_package_install() (
	# apt can resolve an addition by removing installed packages, even with
	# no explicit removal intent. Protect both install attempts in lib.sh.
	# A subshell keeps this override out of all later stock package calls.
	if [[ "$PKG_MGR" == apt ]]; then
		# pkg_install in lib.sh calls this override indirectly.
		# shellcheck disable=SC2329
		apt-get() {
			if [[ "${1:-}" == install ]]; then
				command apt-get --no-remove "$@"
			else
				command apt-get "$@"
			fi
		}
	fi
	# Other families retain their existing solver flags. Command dispatch
	# tests do not qualify conflict/replacement behavior in a built image.
	pkg_install "$@"
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
				type == "object" and keys == ["id", "key_url", "url"] and
				(.id | token) and (.url | https) and (.key_url | https)) and
				(map(.id) | length == (unique | length))))
	' "$manifest" >/dev/null; then
		_tunaos_fork_packages_error "invalid generated manifest or package syntax: $manifest"
		return 1
	fi

	# A removal denylist cannot protect transitive desktop/base dependencies.
	# lib.sh also masks pacman removal errors and emerge only deselects atoms.
	# Until solver-backed protection exists, fail closed for every removal.
	if [[ $(jq '.intent.packages.remove | length' "$manifest") != 0 ]]; then
		_tunaos_fork_packages_error 'removals are unsupported without protected transaction validation'
		return 1
	fi
	if [[ $(jq '.intent.packages.repositories | length' "$manifest") != 0 && "$manager" != dnf && "$manager" != zypper ]]; then
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

	local -a required=() optional=() optional_installed=() optional_missing=()
	mapfile -t required < <(jq -r '.intent.packages.add[]' "$manifest")
	mapfile -t optional < <(jq -r '.intent.packages.optional[]' "$manifest")
	local count index repo_id repo_url key_url repo_dir repo_path content existing package
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
	if ((count > 0)); then
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
		elif ! pkg_refresh; then
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
	if ! jq --arg digest "$digest" --argjson installed "$installed_json" --argjson missing "$missing_json" '
		{schema_version: 1, status: "complete", variant, flavor, platform,
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
