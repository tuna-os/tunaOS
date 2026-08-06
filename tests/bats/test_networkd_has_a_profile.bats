#!/usr/bin/env bats
# Enabling systemd-networkd is not the same as configuring a network.
#
# NetworkManager DHCPs every unmanaged link by default. networkd does nothing
# at all without a `.network` profile — so a base that ships no profile boots
# with the daemon running, a NIC present, and no address.
#
# guppy:xfce, LUKS run 31091141499: the image built, the live ISO booted,
# TUNAOS_LUKS_E2E_INSTALL_STARTED fired, sshd was enabled and its host keys
# generated — and the harness could not reach port 22 for six minutes. That is
# the same outward signature grouper and sailfin each had for a different
# underlying reason, which is why the check is on the profile and not on sshd.
#
# openSUSE ships /usr/lib/systemd/network/20-wired.network itself, so enabling
# the unit was the entire fix there; 40-services.sh says so in its own comment.
# Gentoo's stage3 ships none.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SERVICES="${REPO_ROOT}/build_scripts/40-services.sh"

@test "enabling networkd also provisions a profile for it to read" {
  run grep -q 'systemd-networkd.service' "$SERVICES"
  [ "$status" -eq 0 ]
  run grep -q 'DHCP=yes' "$SERVICES"
  [ "$status" -eq 0 ]
  run grep -q '20-wired.network' "$SERVICES"
  [ "$status" -eq 0 ]
}

@test "the profile is only written when the base ships none" {
  # Writing unconditionally would put a second policy alongside openSUSE's own
  # 20-wired.network. The guard has to look in BOTH search paths — a base that
  # ships its profile in /etc would otherwise get a competing one in /usr.
  local block
  block="$(awk '/if \[\[ "\$net_unit" == systemd-networkd.service \]\]/,/^\t\tfi$/' "$SERVICES")"
  [ -n "$block" ]
  [[ "$block" == *'/usr/lib/systemd/network/*.network'* ]]
  [[ "$block" == *'/etc/systemd/network/*.network'* ]]
}

@test "the writer is reached on the path that enables the unit" {
  # The enable and the profile must live in the same branch: writing a profile
  # somewhere the daemon is not enabled, or enabling without writing, both
  # leave the guest unreachable.
  local fn
  fn="$(awk '/^tunaos_enable_network_manager\(\) \{/,/^\}$/' "$SERVICES")"
  [ -n "$fn" ]
  [[ "$fn" == *'systemctl enable "$net_unit"'* ]]
  [[ "$fn" == *'20-wired.network'* ]]
}

@test "the profile parses as a networkd unit" {
  # A malformed profile is worse than none: networkd logs and carries on, so
  # the image looks correct and the link still has no address.
  local body
  body="$(sed -n "/^\[Match\]$/,/^NETEOF$/p" "$SERVICES" | sed '/^NETEOF$/d')"
  [[ "$body" == *'[Match]'* ]]
  [[ "$body" == *'[Network]'* ]]
  [[ "$body" == *'DHCP=yes'* ]]
  # Match on interface-name globs, not a hardcoded eth0 that modern predictable
  # naming will not produce.
  [[ "$body" == *'Name=en*'* ]]
}
