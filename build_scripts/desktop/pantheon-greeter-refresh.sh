#!/usr/bin/env bash
# Restart LightDM once elementary Initial Setup has created the first account.
#
# io.elementary.greeter launches Initial Setup itself when no account exists,
# and keeps running underneath it. It adds a card for the new account the
# moment accounts-daemon creates it, while the account is still locked (`!`
# in /etc/shadow). Initial Setup then sets the password, but the card never
# leaves its "Account disabled" state (greeter src/Cards/UserCard.vala says
# its `locked` binding "doesn't work when creating a new user"). Measured on
# gurnard-pantheon, iso-builder run 44516439600: /etc/shadow held a `$y$`
# hash for tunaose2e, and the greeter still showed "Account disabled" for 13
# minutes, so nobody could log in after a fresh install.
#
# The fix is a fresh greeter: Initial Setup's binary is wrapped, and after a
# successful exit that left a login account the wrapper restarts
# lightdm.service. A polkit rule lets the lightdm user restart that one unit.
# TUNAOS_DM_ROOT points at a scratch root for tests.
set -euo pipefail

root="${TUNAOS_DM_ROOT:-}"
bin="${root}/usr/bin/io.elementary.initial-setup"
real="${root}/usr/libexec/tunaos/io.elementary.initial-setup"

if [[ ! -x "$bin" && ! -x "$real" ]]; then
	echo "pantheon-greeter-refresh: io.elementary.initial-setup is not installed; nothing to do"
	exit 0
fi

mkdir -p "$(dirname "$real")" "${root}/usr/share/polkit-1/rules.d"
# Idempotent: a second run must not wrap the wrapper.
if ! grep -qs 'tunaos-initial-setup-wrapper' "$bin"; then
	mv "$bin" "$real"
fi
cat >"$bin" <<'WRAP'
#!/bin/sh
# tunaos-initial-setup-wrapper: see build_scripts/desktop/pantheon-greeter-refresh.sh
/usr/libexec/tunaos/io.elementary.initial-setup "$@"
rc=$?
if [ "$rc" -eq 0 ] && getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 { found = 1 } END { exit !found }'; then
	systemctl --no-block restart lightdm.service || true
fi
exit "$rc"
WRAP
chmod 0755 "$bin"

cat >"${root}/usr/share/polkit-1/rules.d/49-tunaos-initial-setup-greeter.rules" <<'RULES'
// Lets the greeter's Initial Setup restart LightDM after it created the first
// account (build_scripts/desktop/pantheon-greeter-refresh.sh).
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        action.lookup("unit") == "lightdm.service" &&
        action.lookup("verb") == "restart" &&
        subject.user == "lightdm") {
        return polkit.Result.YES;
    }
    return polkit.Result.NOT_HANDLED;
});
RULES
echo "pantheon-greeter-refresh: Initial Setup restarts LightDM after creating the first account"
