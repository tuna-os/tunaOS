#!/usr/bin/env bash
# Opt-in URL/wallpaper adapter. Source this file; an absent generated manifest
# must not create files or change stock identity. See docs/FORK-BRANDING.md.

_tunaos_fork_branding_error() {
	printf 'ERROR: fork branding: %s\n' "$*" >&2
	return 1
}

_tunaos_fork_branding_schema() {
	local manifest="$1"
	[[ -f "$manifest" && ! -L "$manifest" ]] || {
		_tunaos_fork_branding_error "manifest is missing, non-regular, or a symlink: $manifest"
		return 1
	}
	# jq normally accepts duplicate object keys by keeping the last one. The
	# stream still exposes every value and completed container, so reject a
	# value whose path (or a parent path) was already completed.
	if ! jq --stream -e -s '
		reduce .[] as $event ({closed: [], valid: true};
			if ($event | length) == 2 then
				.valid = (.valid and (any(.closed[]; . as $path |
					$event[0][0:($path | length)] == $path) | not)) |
				.closed += [$event[0]]
			else .closed += [$event[0][0:-1]] end) | .valid
	' "$manifest" >/dev/null; then
		_tunaos_fork_branding_error "invalid JSON or duplicate manifest key"
		return 1
	fi
	# jq reads JSON as data; no config value is sourced or evaluated as shell.
	if ! jq -e -s '
		def exact($allowed): type == "object" and (keys == ($allowed | sort));
		def subset($allowed): type == "object" and ((keys - $allowed) | length == 0);
		def text: type == "string" and length > 0 and (test("[[:cntrl:]]") | not);
		def https: text and test("^https://[^/[:space:]]+(/[^[:space:]]*)?$");
		def strings: type == "array" and all(.[]; text) and (length == (unique | length));
		length == 1 and (.[0] | exact(["schema_version", "variant", "flavor", "platform", "package_manager", "intent", "sources", "assets", "image"])
		and .schema_version == 1
		and (.image | exact(["registry", "namespace"])
			and (.registry | text and test("^[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?$\\z"))
			and (.namespace | text and test("^[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*$\\z")))
		and (.variant | text and test("^[a-z0-9][a-z0-9-]*$\\z"))
		and (.flavor | IN("gnome", "kde", "cosmic", "niri", "xfce", "pantheon", "tuna"))
		and (.platform | IN("linux/amd64", "linux/amd64/v2", "linux/arm64"))
		and (.package_manager | IN("dnf", "apt", "pacman", "zypper", "emerge"))
		and (.sources | exact(["sha256"]) and (.sha256 | type == "string" and test("^[a-f0-9]{64}$\\z")))
		and (.intent | exact(["branding", "packages"]))
		and (.intent.branding | subset(["homepage", "documentation", "support", "wallpaper"]))
		and (.intent.branding | to_entries | all(.[]; if .key == "wallpaper" then .value | text else .value | https end))
		and (.intent.packages | exact(["add", "remove", "optional", "repositories"]))
		and (.intent.packages | (.add | strings) and (.remove | strings) and (.optional | strings))
		and (.intent.packages.repositories | type == "array" and all(.[];
			exact(["id", "url", "key_url"]) and (.id | text) and (.url | https) and (.key_url | https)))
		and (.assets | subset(["wallpaper"]))
		and ((.assets | has("wallpaper")) == (.intent.branding | has("wallpaper")))
		and (if .assets | has("wallpaper") then .assets.wallpaper |
			exact(["path", "sha256"])
			and (.sha256 | type == "string" and test("^[a-f0-9]{64}$\\z"))
			and (.path | type == "string" and test("^fork-assets/[a-f0-9]{64}\\.jpg$\\z"))
			and (.path == ("fork-assets/" + .sha256 + ".jpg"))
		else true end))
	' "$manifest" >/dev/null; then
		_tunaos_fork_branding_error "invalid or unsupported manifest; name/logo require embedded installer, lettermark and Plymouth adapters"
		return 1
	fi
	if jq -e '.flavor == "tuna" and (.intent.branding | has("wallpaper"))' "$manifest" >/dev/null; then
		_tunaos_fork_branding_error "tuna wallpaper override is unsupported until its desktop setting consumer is verified"
		return 1
	fi
}

_tunaos_fork_branding_asset() {
	local manifest="$1" asset hash dir
	asset="$(jq -r '.assets.wallpaper.path // empty' "$manifest")"
	[[ -n "$asset" ]] || return 0
	dir="$(dirname "$manifest")"
	[[ ! -L "$dir/fork-assets" && -f "$dir/$asset" && ! -L "$dir/$asset" ]] || {
		_tunaos_fork_branding_error "wallpaper is missing, non-regular, or a symlink: $asset"
		return 1
	}
	hash="$(sha256sum "$dir/$asset")"
	[[ "${hash%% *}" == "$(jq -r '.assets.wallpaper.sha256' "$manifest")" ]] || {
		_tunaos_fork_branding_error "wallpaper hash mismatch: $asset"
		return 1
	}
}

# Root is an explicit test seam. It never redirects source input selection.
# Platform architecture is checked here; the wrapper pins the exact --platform.
# uname cannot establish the amd64/v2 ISA requirement or prove a booted image.
tunaos_validate_fork_branding() {
	local context="${1:-/run/context}" manifest variant flavor
	manifest="$context/manifests/fork-config.json"
	[[ -e "$manifest" || -L "$manifest" ]] || return 0
	_tunaos_fork_branding_schema "$manifest" || return 1
	variant="${IMAGE_NAME_VARIANT:-}"
	flavor="${TUNAOS_IMAGE_FLAVOR:-}"
	[[ -n "$variant" && -n "$flavor" ]] || {
		_tunaos_fork_branding_error "IMAGE_NAME_VARIANT and TUNAOS_IMAGE_FLAVOR must identify the build cell"
		return 1
	}
	if ! jq -e --arg variant "$variant" --arg flavor "$flavor" \
		'.variant == $variant and .flavor == $flavor' "$manifest" >/dev/null; then
		_tunaos_fork_branding_error "manifest cell does not match build identity $variant:$flavor"
		return 1
	fi
	if [[ -n "${PKG_MGR:-}" ]] && ! jq -e --arg manager "$PKG_MGR" '.package_manager == $manager' "$manifest" >/dev/null; then
		_tunaos_fork_branding_error "manifest package manager does not match $PKG_MGR"
		return 1
	fi
	_tunaos_fork_branding_platform "$manifest" || return 1
	_tunaos_fork_branding_asset "$manifest"
}

_tunaos_fork_branding_platform() {
	local manifest="$1" arch platform
	arch="$(uname -m)"
	platform="$(jq -r '.platform' "$manifest")"
	case "$arch:$platform" in
	x86_64:linux/amd64 | x86_64:linux/amd64/v2 | aarch64:linux/arm64) ;;
	*)
		_tunaos_fork_branding_error "manifest platform $platform does not match machine architecture $arch"
		return 1
		;;
	esac
}

tunaos_fork_branding_url() {
	local manifest="$1" field="$2" key
	case "$field" in
	HOME_URL) key=homepage ;;
	DOCUMENTATION_URL) key=documentation ;;
	SUPPORT_URL | BUG_REPORT_URL) key=support ;;
	*) return 1 ;;
	esac
	jq -r --arg key "$key" '.intent.branding[$key] // empty' "$manifest"
}

_tunaos_fork_branding_osr_value() {
	local value="$1"
	value="${value//\\/\\\\}"
	value="${value//\"/\\\"}"
	value="${value//\$/\\\$}"
	value="${value//\`/\\\`}"
	printf '"%s"' "$value"
}

_tunaos_fork_branding_osr_set() {
	local file="$1" key="$2" value="$3" tmp
	tmp="$(mktemp "${file}.fork.XXXXXX")" || return 1
	# Filter by key, then print a literal value. URL query ampersands, quotes,
	# dollar signs and backticks cannot become sed replacements or shell code.
	awk -v key="$key" 'index($0, key "=") != 1' "$file" >"$tmp" || return 1
	printf '%s=%s\n' "$key" "$(_tunaos_fork_branding_osr_value "$value")" >>"$tmp"
	chmod --reference="$file" "$tmp"
	mv "$tmp" "$file"
}

_tunaos_fork_branding_image_info() {
	local manifest="$1" file="$2"
	if ! jq -e --slurpfile manifest "$manifest" '
		$manifest[0] as $m |
		.["image-name"] == $m.variant and
		.["image-flavor"] == $m.flavor and
		.["image-vendor"] == $m.image.namespace and
		.["image-ref"] == ("ostree-image-signed:docker://" + $m.image.registry + "/" + $m.image.namespace + "/" + $m.variant)
	' "$file" >/dev/null; then
		_tunaos_fork_branding_error "image-info name, flavor, vendor or image-ref does not match manifest"
		return 1
	fi
}

tunaos_apply_fork_branding() {
	local context="${1:-/run/context}" root="${2:-/}" manifest target field value file asset tmp
	manifest="$context/manifests/fork-config.json"
	[[ -e "$manifest" || -L "$manifest" ]] || return 0
	[[ "$root" == /* ]] || {
		_tunaos_fork_branding_error "root must be absolute"
		return 1
	}
	root="${root%/}"
	tunaos_validate_fork_branding "$context" || return 1
	for file in "$root/usr/lib/os-release" "$root/usr/share/ublue-os/image-info.json"; do
		[[ -f "$file" ]] || {
			_tunaos_fork_branding_error "required identity file missing: $file"
			return 1
		}
	done
	_tunaos_fork_branding_image_info "$manifest" "$root/usr/share/ublue-os/image-info.json" || return 1
	for field in HOME_URL DOCUMENTATION_URL SUPPORT_URL BUG_REPORT_URL; do
		value="$(tunaos_fork_branding_url "$manifest" "$field")"
		[[ -n "$value" ]] || continue
		_tunaos_fork_branding_osr_set "$root/usr/lib/os-release" "$field" "$value" || return 1
		if [[ -f "$root/etc/os-release" ]] && ! [[ "$root/etc/os-release" -ef "$root/usr/lib/os-release" ]]; then
			_tunaos_fork_branding_osr_set "$root/etc/os-release" "$field" "$value" || return 1
		fi
	done
	asset="$(jq -r '.assets.wallpaper.path // empty' "$manifest")"
	if [[ -n "$asset" ]]; then
		install -Dm0644 "$context/manifests/$asset" "$root/usr/share/backgrounds/tunaos/tunaos-default.jpg"
	fi
	# KDE rewrites this after package installation. Reapply after that script
	# in both paths; leave every unrelated About setting untouched.
	value="$(tunaos_fork_branding_url "$manifest" HOME_URL)"
	file="$root/etc/xdg/kcm-about-distrorc"
	if [[ -n "$value" && -f "$file" ]]; then
		tmp="$(mktemp "${file}.fork.XXXXXX")" || return 1
		# KConfig treats backslashes as escapes. Keep the literal URL and
		# change only [General], even if a package adds another section.
		value="${value//\\/\\\\}"
		TUNAOS_FORK_WEBSITE="$value" awk '
			BEGIN { want = ENVIRON["TUNAOS_FORK_WEBSITE"] }
			/^\[/ {
				if (in_general && !written) { print "Website=" want; written = 1 }
				in_general = ($0 == "[General]")
			}
			/^Website=/ { if (in_general) { if (!written) print "Website=" want; written = 1; next } }
			{ print }
			END { if (!written) { if (!in_general) print "[General]"; print "Website=" want } }
		' "$file" >"$tmp"
		chmod --reference="$file" "$tmp"
		mv "$tmp" "$file"
	fi
	# Runtime checks use the exact validated input and content-addressed asset.
	# This is source provenance, never image/boot/installer acceptance evidence.
	target="$root/usr/share/tunaos/fork"
	install -Dm0644 "$manifest" "$target/fork-config.json"
	if [[ -n "$asset" ]]; then
		install -Dm0644 "$context/manifests/$asset" "$target/$asset"
	fi
	install -Dm0755 "$context/build_scripts/lib/fork-branding.sh" "$root/usr/libexec/tunaos/fork-branding.sh"
	file="$root/usr/share/ublue-os/image-info.json"
	tmp="$(mktemp "${file}.fork.XXXXXX")" || return 1
	jq --slurpfile manifest "$manifest" \
		'.["fork-config"] = ($manifest[0] | {schema_version, image, variant, flavor, platform, sources})' "$file" >"$tmp" || return 1
	chmod --reference="$file" "$tmp"
	mv "$tmp" "$file"
}

# Checks overridden values and the installed receipt without reading build env.
# Existing verify-branding retains its fish/CPE-adjacent identity, asset, theme,
# vendor, dconf and per-desktop assertions; only URL expectations are adaptable.
tunaos_verify_fork_branding() {
	local root="${1:-/}" manifest field value expected file asset hash variant
	[[ "$root" == /* ]] || {
		_tunaos_fork_branding_error "root must be absolute"
		return 1
	}
	root="${root%/}"
	manifest="$root/usr/share/tunaos/fork/fork-config.json"
	_tunaos_fork_branding_schema "$manifest" || return 1
	_tunaos_fork_branding_platform "$manifest" || return 1
	_tunaos_fork_branding_asset "$manifest" || return 1
	file="$root/usr/share/ublue-os/image-info.json"
	_tunaos_fork_branding_image_info "$manifest" "$file" || return 1
	jq -e --slurpfile manifest "$manifest" \
		'.["fork-config"] == ($manifest[0] | {schema_version, image, variant, flavor, platform, sources})
		and .["image-flavor"] == $manifest[0].flavor' "$file" >/dev/null || {
		_tunaos_fork_branding_error "installed image-info receipt does not match manifest"
		return 1
	}
	variant="$(sed -n "s/^TUNAOS_VARIANT='\\([^']*\\)'$/\\1/p" "$root/usr/share/tunaos/identity.env")"
	[[ -n "$variant" && "$variant" == "$(jq -r '.variant' "$manifest")" ]] || {
		_tunaos_fork_branding_error "installed variant identity does not match manifest"
		return 1
	}
	for field in HOME_URL DOCUMENTATION_URL SUPPORT_URL BUG_REPORT_URL; do
		value="$(tunaos_fork_branding_url "$manifest" "$field")"
		[[ -n "$value" ]] || continue
		expected="$field=$(_tunaos_fork_branding_osr_value "$value")"
		for file in "$root/usr/lib/os-release" "$root/etc/os-release"; do
			[[ -e "$file" ]] || {
				[[ "$file" == "$root/etc/os-release" ]] && continue
				return 1
			}
			if [[ "$(grep -c "^${field}=" "$file" || true)" != 1 ]] || ! grep -Fxq "$expected" "$file"; then
				_tunaos_fork_branding_error "$field does not match manifest in $file"
				return 1
			fi
		done
	done
	value="$(tunaos_fork_branding_url "$manifest" HOME_URL)"
	file="$root/etc/xdg/kcm-about-distrorc"
	if [[ -n "$value" && -f "$file" ]]; then
		value="${value//\\/\\\\}"
		if [[ "$(awk '/^\[/ { in_general = ($0 == "[General]") } in_general && /^Website=/ { print }' "$file")" != "Website=$value" ]]; then
			_tunaos_fork_branding_error "KDE About website does not match manifest"
			return 1
		fi
	fi
	asset="$(jq -r '.assets.wallpaper.path // empty' "$manifest")"
	if [[ -n "$asset" ]]; then
		hash="$(sha256sum "$root/usr/share/backgrounds/tunaos/tunaos-default.jpg")" || return 1
		[[ "${hash%% *}" == "$(jq -r '.assets.wallpaper.sha256' "$manifest")" ]] || {
			_tunaos_fork_branding_error "active wallpaper hash does not match manifest"
			return 1
		}
	fi
}
