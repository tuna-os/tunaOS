#!/usr/bin/env bash
# Local counterpart of live-overlay.yml's shared Tacklebox customization path.
# No registry publication. The resulting manifest is an input to final ISO
# customization, so the overlay digest does not refer to its own receipt.
set -euo pipefail
source scripts/lib/tacklebox.sh
variant="${1:?variant}" flavor="${2:?flavor}" platform="${3:?platform}"
source_image="${4:?source image}" source_digest="${5:?source digest}"
env_output="${6:?environment output}"
[[ "$EUID" == 0 && "$source_digest" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$variant" =~ ^[a-z0-9-]+$ && "$flavor" =~ ^[a-z0-9-]+$ ]]
[[ "$platform" == linux/amd64 || "$platform" == linux/amd64/v2 ]]
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
# Require the immutable local source ref to resolve to the measured manifest.
skopeo inspect --raw "containers-storage:${source_image}@${source_digest}" >"$work/source.json"
[[ "sha256:$(sha256sum "$work/source.json" | awk '{print $1}')" == "$source_digest" ]]
bin="$(tunaos_tacklebox_source_binary)"
cp "$bin" "$work/tacklebox"
chmod 0555 "$work/tacklebox"
engine_digest="sha256:$(sha256sum "$work/tacklebox" | awk '{print $1}')"
cp -a live-iso/common/src/. "$work/"
case "${flavor%%-*}" in
kde) installer_app=org.tunaos.InstallerKde ;;
niri) installer_app=org.tunaos.InstallerNiri ;;
cosmic) installer_app=org.tunaos.InstallerCosmic ;;
xfce) installer_app=org.tunaos.InstallerXfce ;;
gnome) installer_app=org.bootcinstaller.Installer ;;
*)
	echo 'ERROR: unsupported native overlay desktop' >&2
	exit 1
	;;
esac
wrapper="$work/native-customize.sh"
{
	printf '#!/usr/bin/env bash\n'
	printf 'export TUNA_INSTALLER_ARCH=%q\n' x86_64
	printf 'export TUNA_INSTALLER_APP=%q\n' "$installer_app"
	printf 'export TUNA_LIVE_BASE_IMAGE=%q\n' "$source_image"
	printf 'export TUNA_LIVE_BASE_DIGEST=%q\n' "$source_digest"
	printf 'export TUNA_LIVE_OVERLAY_DIGEST=%q\n' unknown
	printf 'export TUNA_LIVE_ENGINE_DIGEST=%q\n' "$engine_digest"
	printf 'export TUNA_LIVE_PLATFORM=%q\n' "$platform"
	cat "$work/customize-live.sh"
} >"$wrapper"
chmod +x "$wrapper"
image="localhost/native-live-overlay:${variant}-${flavor}"
# Match the native ISO adapter's validated inner commit deadline.
TBOX_CUSTOMIZE_COMMIT_TIMEOUT="${TBOX_CUSTOMIZE_COMMIT_TIMEOUT:-1800}"
[[ "$TBOX_CUSTOMIZE_COMMIT_TIMEOUT" =~ ^(0|[1-9][0-9]*)$ ]] || exit 2
export TBOX_CUSTOMIZE_COMMIT_TIMEOUT
# This runs baseline + customization via the same command as live-overlay.yml.
timeout --foreground --kill-after=120 3600 "$work/tacklebox" customize-live \
	--image "${source_image}@${source_digest}" --script "$wrapper" --tag "$image" \
	--label "org.tunaos.live-overlay.base=${source_image}" \
	--label "org.tunaos.live-overlay.base-digest=${source_digest}" \
	--label "org.tunaos.live-overlay.platform=${platform}" \
	--label org.tunaos.live-overlay.baseline=true
skopeo inspect --raw "containers-storage:${image}" >"$work/manifest.json"
overlay_digest="sha256:$(sha256sum "$work/manifest.json" | awk '{print $1}')"
# Verify that digest addressing works locally before passing the immutable ref.
skopeo inspect --raw "containers-storage:${image}@${overlay_digest}" >"$work/pinned.json"
cmp "$work/manifest.json" "$work/pinned.json"
{
	printf 'TUNA_LIVE_OVERLAY_REF=%q\n' "${image}@${overlay_digest}"
	printf 'TUNA_LIVE_OVERLAY_DIGEST=%q\n' "$overlay_digest"
} >"$env_output"
