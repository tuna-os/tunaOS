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
# ZIRCONIUM_REF overrides the ref (default: main). Run as root inside a
# container build (context bind-mounted, no network isolation for this RUN).
set -euo pipefail

ZIRCONIUM_REF="${ZIRCONIUM_REF:-main}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Fetching zirconium-dev/zirconium@${ZIRCONIUM_REF}"
curl -fsSL --retry 3 \
	"https://github.com/zirconium-dev/zirconium/archive/refs/heads/${ZIRCONIUM_REF}.tar.gz" |
	tar -xz -C "$TMP"

SRC="$TMP/zirconium-${ZIRCONIUM_REF}/mkosi.extra"
[[ -d "$SRC" ]] || { echo "ERROR: mkosi.extra not found in zirconium@${ZIRCONIUM_REF}" >&2; exit 1; }

# Factory etc -> /etc (greetd, profile.d, kmscon, taidan.toml).
cp -av "$SRC/usr/share/factory/etc/." /etc/

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
