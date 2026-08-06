#!/usr/bin/env bash
# Lay down the Zirconium (DMS/Niri upstream) system payload for niri images.
#
# Sources from the zirconium-dev/zirconium source tarball (mkosi.extra tree)
# instead of the published OCI image. mkosi.extra is a root-filesystem overlay,
# so every path maps 1:1. Replacing `COPY --from=zirconium <path> <path>`
# removes the digest-pin churn (the ARG pin went stale once) and keeps the
# exact file set this repo ships in one place.
#
# Factory files (/usr/share/factory/etc/*) are copied to /etc explicitly, the
# same way the Containerfile COPYs did — greetd needs its config present at
# first boot, not only after the 99-zirconium-factory tmpfiles run.
#
# The ref is PINNED to a commit in image-versions.yaml (downloads.zirconium_src,
# tracked by Renovate like every other download). Fetching a branch tip instead
# would make niri images non-reproducible — two builds of the same tunaOS commit
# would ship whatever upstream happened to have merged in between — and would
# hand anything that lands on that branch a path straight into the image. A
# checksum of the tarball is deliberately not layered on top: GitHub generates
# these archives on demand and their bytes are not stable, so such a pin would
# break spontaneously, whereas the commit is already content-addressed.
#
# ZIRCONIUM_REF overrides the pin for local testing against an unmerged branch.
# Run as root inside a container build (context bind-mounted, no network
# isolation for this RUN).
set -euo pipefail

VERSIONS="${VERSIONS_FILE:-/run/context/image-versions.yaml}"
if [[ -z "${ZIRCONIUM_REF:-}" ]]; then
	# Same grep/sed reader the other pinned downloads use (10-base-packages.sh,
	# niri.sh) so no yq is needed inside the build.
	ZIRCONIUM_REF=$(grep '^\s*zirconium_src:' "$VERSIONS" 2>/dev/null |
		sed 's/.*"\(.*\)".*/\1/')
	[[ -n "$ZIRCONIUM_REF" ]] || {
		echo "ERROR: downloads.zirconium_src not found in $VERSIONS — refusing to" >&2
		echo "       fall back to a moving branch tip. Set ZIRCONIUM_REF to override." >&2
		exit 1
	}
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Fetching zirconium-dev/zirconium@${ZIRCONIUM_REF}"
# /archive/<ref>.tar.gz resolves commits, tags and branch names alike, so an
# override does not need a different URL shape than the pinned commit.
curl -fsSL --retry 3 \
	"https://github.com/zirconium-dev/zirconium/archive/${ZIRCONIUM_REF}.tar.gz" |
	tar -xz -C "$TMP"

# GitHub names the archive's top-level directory after the ref with slashes
# flattened (feat/x -> zirconium-feat-x), so don't reconstruct it from the ref —
# take whatever single directory the tarball extracted.
shopt -s nullglob
_roots=("$TMP"/*/)
shopt -u nullglob
[[ "${#_roots[@]}" -eq 1 ]] || {
	echo "ERROR: expected one top-level dir in zirconium@${ZIRCONIUM_REF} tarball, got ${#_roots[@]}" >&2
	exit 1
}
SRC="${_roots[0]}mkosi.extra"
[[ -d "$SRC" ]] || { echo "ERROR: mkosi.extra not found in zirconium@${ZIRCONIUM_REF}" >&2; exit 1; }

# Factory etc -> /etc (greetd, profile.d, kmscon, taidan.toml).
cp -av "$SRC/usr/share/factory/etc/." /etc/

# The greeter's own niri config, which the factory tree does NOT contain.
#
# /etc/greetd/config.toml (just copied above) launches:
#     dms-greeter --command niri --cache-dir /var/cache/dms-greeter \
#         -C /etc/greetd/niri/config.kdl
#
# Upstream never ships that file either — it materialises it at first boot
# from the tail of usr/lib/tmpfiles.d/99-zirconium-factory.conf:
#     d /etc/greetd/niri
#     f /etc/greetd/niri/config.kdl
# We deliberately do not install 99-zirconium-factory.conf (its other lines
# symlink /etc back into the factory tree, which is exactly what the cp above
# replaces with real files), so that pair was silently lost and the greeter
# came up pointed at a path that did not exist — tunaOS#1009, and the reason
# verify-branding-niri.sh asserts the -C target rather than trusting it.
#
# `f` with no argument creates an empty file, so an empty config is upstream's
# actual behaviour, not a placeholder: the greeter wants niri's built-in
# defaults. The comment line is valid KDL and changes nothing but discoverability.
install -d -m 0755 /etc/greetd/niri
cat >/etc/greetd/niri/config.kdl <<'EOF'
// Greeter session config. Intentionally empty: dms-greeter runs niri with
// its built-in defaults here. Laid down by build_scripts/install-zirconium.sh.
EOF
chmod 0644 /etc/greetd/niri/config.kdl

# The niri/DMS payload -> /usr. Explicit paths (not the whole usr/ tree, which
# carries zirconium-branded zfetch/zmotd and extra services we don't ship).
install -Dm0644 "$SRC/usr/share/greetd/greetd-spawn.pam_env.conf" /usr/share/greetd/greetd-spawn.pam_env.conf
install -Dm0644 "$SRC/usr/share/dms/cli-policy.json" /usr/share/dms/cli-policy.json
install -Dm0644 "$SRC/usr/lib/pam.d/greetd-spawn" /usr/lib/pam.d/greetd-spawn
install -Dm0644 "$SRC/usr/lib/sysusers.d/dms-greeter.conf" /usr/lib/sysusers.d/dms-greeter.conf
install -Dm0644 "$SRC/usr/lib/tmpfiles.d/99-dms-greeter.conf" /usr/lib/tmpfiles.d/99-dms-greeter.conf
install -Dm0644 "$SRC/usr/lib/systemd/user/chezmoi-init.service" /usr/lib/systemd/user/chezmoi-init.service
install -Dm0644 "$SRC/usr/lib/systemd/user/chezmoi-update.service" /usr/lib/systemd/user/chezmoi-update.service
install -Dm0644 "$SRC/usr/lib/systemd/user/dms.service.d/override.conf" /usr/lib/systemd/user/dms.service.d/override.conf
install -Dm0644 "$SRC/usr/share/flatpak/preinstall.d/zirconium.preinstall" /usr/share/flatpak/preinstall.d/zirconium.preinstall
install -Dm0644 "$SRC/usr/share/xdg-terminal-exec/xdg-terminals.list" /usr/share/xdg-terminal-exec/xdg-terminals.list
install -Dm0644 "$SRC/usr/share/zirconium/fastfetch.jsonc" /usr/share/zirconium/fastfetch.jsonc
install -Dm0644 "$SRC/usr/share/zirconium/glorp.txt" /usr/share/zirconium/glorp.txt
install -Dm0644 "$SRC/usr/share/zirconium/legally-distinct.txt" /usr/share/zirconium/legally-distinct.txt
install -Dm0644 "$SRC/usr/share/zirconium/zirconium.txt" /usr/share/zirconium/zirconium.txt
install -Dm0644 "$SRC/usr/share/zirconium/just/00-start.just" /usr/share/zirconium/just/00-start.just
# zdots is an intentionally empty directory (dotfiles live in the zdots repo).
install -d /usr/share/zirconium/zdots

echo "==> zirconium payload installed"
