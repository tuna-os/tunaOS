#!/usr/bin/env bash
# Called only after the generated manifest passed the package schema.
# Keep trust local to each deb822 source; never import a globally trusted key.

tunaos_fork_apt_repositories() (
	local manifest="$1" root="$2" tool stage index count id url key_url digest actual path parent
	[[ -d "$root" && ! -L "$root" ]] || return 1
	for tool in curl gpg sha256sum cmp; do
		command -v "$tool" >/dev/null || {
			_tunaos_fork_packages_error "APT repositories need $tool"
			return 1
		}
	done
	stage=$(mktemp -d) || return 1
	trap 'rm -rf -- "$stage"' EXIT
	mkdir -m 0700 "$stage/gnupg" || return 1
	count=$(jq '.intent.packages.repositories | length' "$manifest") || return 1
	# Validate every destination before network requests or root mutations.
	for ((index = 0; index < count; index++)); do
		id=$(jq -r ".intent.packages.repositories[$index].id" "$manifest")
		for path in "etc/apt/sources.list.d/fork-${id}.sources" "usr/share/keyrings/fork-${id}.gpg"; do
			parent="${root%/}/$path"
			while [[ "$parent" != "${root%/}" && "$parent" != / ]]; do
				[[ ! -L "$parent" ]] || {
					_tunaos_fork_packages_error "refusing repository symlink: $parent"
					return 1
				}
				parent=$(dirname "$parent")
			done
			[[ ! -e "${root%/}/$path" || -f "${root%/}/$path" ]] || return 1
		done
	done
	for ((index = 0; index < count; index++)); do
		id=$(jq -r ".intent.packages.repositories[$index].id" "$manifest")
		url=$(jq -r ".intent.packages.repositories[$index].url" "$manifest")
		key_url=$(jq -r ".intent.packages.repositories[$index].key_url" "$manifest")
		digest=$(jq -r ".intent.packages.repositories[$index].key_sha256" "$manifest")
		curl --proto '=https' --proto-redir '=https' --tlsv1.2 --fail --location \
			--max-filesize 1048576 --max-time 120 --output "$stage/$id.key" "$key_url" || return 1
		actual=$(sha256sum "$stage/$id.key") || return 1
		[[ "${actual%% *}" == "$digest" ]] || {
			_tunaos_fork_packages_error "APT repository key digest mismatch: $id"
			return 1
		}
		# A key download is data, not a script or an apt-key global import.
		gpg --homedir "$stage/gnupg" --batch --yes --dearmor --output "$stage/$id.gpg" "$stage/$id.key" || return 1
		[[ -s "$stage/$id.gpg" ]] || return 1
		{
			printf 'Types: deb\nURIs: %s\n' "$url"
			printf 'Suites: %s\n' "$(jq -r ".intent.packages.repositories[$index].suites | join(\" \")" "$manifest")"
			printf 'Components: %s\n' "$(jq -r ".intent.packages.repositories[$index].components | join(\" \")" "$manifest")"
			printf 'Signed-By: /usr/share/keyrings/fork-%s.gpg\nEnabled: yes\n' "$id"
		} >"$stage/$id.sources" || return 1
		for path in "etc/apt/sources.list.d/fork-${id}.sources" "usr/share/keyrings/fork-${id}.gpg"; do
			if [[ -e "${root%/}/$path" ]] && ! cmp -s "${root%/}/$path" "$stage/$id.${path##*.}"; then
				_tunaos_fork_packages_error "refusing to replace existing APT repository file: $path"
				return 1
			fi
		done
	done
	# All network, digest, format and collision checks succeeded. No apt refresh
	# occurs until every source has its verified, source-specific keyring.
	mkdir -p "${root%/}/etc/apt/sources.list.d" "${root%/}/usr/share/keyrings" || return 1
	for ((index = 0; index < count; index++)); do
		id=$(jq -r ".intent.packages.repositories[$index].id" "$manifest")
		install -m 0644 "$stage/$id.gpg" "${root%/}/usr/share/keyrings/fork-$id.gpg" || return 1
		install -m 0644 "$stage/$id.sources" "${root%/}/etc/apt/sources.list.d/fork-$id.sources" || return 1
	done
)
