#!/usr/bin/env bash
# Install asahi-bootbin-sync (tunaOS#779): bootc deploys never run package
# scriptlets, so update-m1n1 never re-runs after `bootc upgrade` — new
# DTBs/m1n1/U-Boot would silently never reach <ESP>/m1n1/boot.bin. This
# oneshot compares a content stamp against the ESP and regenerates boot.bin
# when stale. Apple-DT-gated: a no-op on non-Apple hardware, so it is safe
# to ship in every asahi flavor unconditionally.
#
# Vendored at a pinned ref from tuna-os/bootc-installer-asahi (same pattern
# as the asahi-scripts dracut vendoring in overlay/asahi.sh).
set -euo pipefail

BOOTBIN_SYNC_REF=f9dbe4a3d98af94e3317eb420c0a5ecbfdac8368
BASE="https://raw.githubusercontent.com/tuna-os/bootc-installer-asahi/${BOOTBIN_SYNC_REF}/components/asahi-bootbin-sync"

install -d /usr/libexec /usr/lib/systemd/system /usr/lib/systemd/system-preset
curl -fsSL "${BASE}/asahi-bootbin-sync.sh" -o /usr/libexec/asahi-bootbin-sync
chmod 0755 /usr/libexec/asahi-bootbin-sync
curl -fsSL "${BASE}/asahi-bootbin-sync.service" \
	-o /usr/lib/systemd/system/asahi-bootbin-sync.service
printf 'enable asahi-bootbin-sync.service\n' \
	> /usr/lib/systemd/system-preset/90-asahi-bootbin-sync.preset

# Verify the vendored pair is coherent (unit must exec what we installed).
grep -q "ExecStart=/usr/libexec/asahi-bootbin-sync" \
	/usr/lib/systemd/system/asahi-bootbin-sync.service

# Presets only apply to future first-boots on some flows; enable directly
# too (symlink — systemctl may be unavailable in-container).
install -d /usr/lib/systemd/system/multi-user.target.wants
ln -sf ../asahi-bootbin-sync.service \
	/usr/lib/systemd/system/multi-user.target.wants/asahi-bootbin-sync.service

echo "asahi-bootbin-sync installed (ref ${BOOTBIN_SYNC_REF})"
