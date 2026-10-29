#!/usr/bin/env bash
# Image-wide package additions from tunaos.toml ([defaults.packages] and each
# variant's `packages`), compiled into image-packages.tsv beside this file by
# `scripts/config.py generate-image-packages`. 30-image-packages.sh calls this
# in the base stage of every Containerfile.
#
# A variant with no rows returns before anything runs or is written, so a
# build without additions is unchanged. Removals are not supported: the TOML
# check rejects them, and apt may not remove packages to satisfy an addition.

_tunaos_image_packages_error() {
	printf 'image packages: %s\n' "$*" >&2
	return 1
}

# Print this variant's rows; nothing when tunaos.toml adds no packages to it.
# Aliases ("opensuse") fold onto their variant first, as in 90-image-info.sh.
tunaos_image_package_rows() {
	local lib="$1" variant="$2" canonical
	canonical="$(awk -F'\t' -v alias="$variant" '$1 == alias { print $2 }' "${lib}/variant-aliases.tsv")" || return 1
	awk -F'\t' -v id="${canonical:-$variant}" '!/^#/ && $1 == id' "${lib}/image-packages.tsv"
}

_tunaos_image_package_install() (
	# apt can resolve an addition by removing installed packages. Refuse that
	# in both of lib.sh's install attempts; the subshell keeps the override
	# away from every later package call.
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
	pkg_install "$@"
)

# tunaos_apply_image_packages <lib dir> [root]
# root redirects the repository files and receipt only (tests).
tunaos_apply_image_packages() {
	local lib="${1:-/run/context/build_scripts/lib}" root="${2:-/}"
	local variant="${IMAGE_NAME_VARIANT:-${IMAGE_NAME:-}}" rows
	[[ -n "$variant" ]] || {
		_tunaos_image_packages_error 'IMAGE_NAME_VARIANT and IMAGE_NAME are unset'
		return 1
	}
	rows="$(tunaos_image_package_rows "$lib" "$variant")" || return 1
	[[ -n "$rows" ]] || return 0
	if ! declare -F pkg_install >/dev/null || ! declare -F pkg_refresh >/dev/null; then
		_tunaos_image_packages_error 'source lib.sh before applying package additions'
		return 1
	fi

	# Rows name the canonical variant; report that, not an alias. (Read into
	# a separate name: the final, failing read at EOF clears its variables.)
	local row_variant manager kind name url key_url
	local -a required=() optional=() repositories=() installed=() missing=()
	while IFS=$'\t' read -r row_variant manager kind name url key_url; do
		variant="$row_variant"
		[[ "$manager" == "$PKG_MGR" ]] || {
			_tunaos_image_packages_error "tunaos.toml compiled ${variant} for ${manager}; this image uses ${PKG_MGR:-no package manager}"
			return 1
		}
		case "$kind" in
		add) required+=("$name") ;;
		optional) optional+=("$name") ;;
		repository) repositories+=("${name}"$'\t'"${url}"$'\t'"${key_url}") ;;
		*)
			_tunaos_image_packages_error "unknown row kind '${kind}'; regenerate image-packages.tsv"
			return 1
			;;
		esac
	done <<<"$rows"

	# Signed repositories only: package AND metadata signatures, under our
	# own file names. Never replace a repository the base already defines.
	local repo repo_dir content path
	if ((${#repositories[@]})); then
		case "$PKG_MGR" in
		dnf) repo_dir="${root%/}/etc/yum.repos.d" ;;
		zypper) repo_dir="${root%/}/etc/zypp/repos.d" ;;
		*)
			_tunaos_image_packages_error "repositories are supported on dnf and zypper only, not ${PKG_MGR}"
			return 1
			;;
		esac
		mkdir -p "$repo_dir" || return 1
		for repo in "${repositories[@]}"; do
			IFS=$'\t' read -r name url key_url <<<"$repo"
			content="$(printf '[image-%s]\nname=%s\nbaseurl=%s\nenabled=1\ngpgcheck=1\nrepo_gpgcheck=1\ngpgkey=%s\n' \
				"$name" "$name" "$url" "$key_url")"
			if [[ "$PKG_MGR" == zypper ]]; then content+=$'\npkg_gpgcheck=1\nautorefresh=1'; fi
			path="${repo_dir}/image-${name}.repo"
			if [[ -e "$path" || -L "$path" ]] && [[ "$(cat "$path" 2>/dev/null)" != "$content" ]]; then
				_tunaos_image_packages_error "refusing to replace existing repository: ${path}"
				return 1
			fi
			printf '%s\n' "$content" >"$path" || return 1
		done
	fi

	# The repository's key comes from tunaos.toml. Bare dnf makecache prompts
	# on the first metadata-key import; approve it explicitly instead of
	# turning either signature check off.
	if [[ "$PKG_MGR" == dnf && ${#repositories[@]} -gt 0 ]]; then
		dnf_retry -y makecache || {
			_tunaos_image_packages_error 'signed repository metadata refresh failed'
			return 1
		}
	elif ! pkg_refresh; then
		_tunaos_image_packages_error 'repository metadata refresh failed'
		return 1
	fi
	if ((${#required[@]})); then
		_tunaos_image_package_install "${required[@]}" || {
			_tunaos_image_packages_error "required packages failed to install: ${required[*]}"
			return 1
		}
	fi
	for name in "${optional[@]}"; do
		if _tunaos_image_package_install "$name"; then
			installed+=("$name")
		else
			missing+=("$name")
			printf 'image packages: optional package unavailable: %s\n' "$name" >&2
		fi
	done

	# What this image got, for verification and support.
	local receipt="${root%/}/usr/share/tunaos/image-packages.tsv"
	mkdir -p "${receipt%/*}" || return 1
	{
		printf '# Written by build_scripts/lib/image-packages.sh for %s (%s).\n' "$variant" "$PKG_MGR"
		for name in "${required[@]}"; do printf 'required\t%s\n' "$name"; done
		for name in "${installed[@]}"; do printf 'optional\t%s\n' "$name"; done
		for name in "${missing[@]}"; do printf 'optional-missing\t%s\n' "$name"; done
		for repo in "${repositories[@]}"; do printf 'repository\t%s\n' "${repo%%$'\t'*}"; done
	} >"$receipt" || return 1
	printf 'image packages: %s required, %s optional, %s missing for %s\n' \
		"${#required[@]}" "${#installed[@]}" "${#missing[@]}" "$variant"
}
