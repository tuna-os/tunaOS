#!/usr/bin/env bash
# sudo-env.sh — keep the caller's environment across sudo on every sudo.
#
# `sudo -E` (and a bare `--preserve-env`) is ignored by sudo-rs, the default
# sudo on Ubuntu 26.04 (ubuntu-latest runners, 26.04 workstations):
#
#   sudo: preserving the entire environment is not supported, '-E' is ignored
#
# `--preserve-env=LIST` works on both sudo and sudo-rs. This helper builds that
# LIST from the variables currently exported, so a call site keeps the meaning
# `sudo -E` had without having to name every variable by hand:
#
#   . scripts/lib/sudo-env.sh
#   sudo "$(tunaos_sudo_preserve_env)" ./scripts/iso-e2e.sh ...
#
# Names that are not plain identifiers (exported bash functions, for example)
# are left out; sudo rejects them.

tunaos_sudo_preserve_env() {
	local names
	names="$(compgen -e | grep -E '^[A-Za-z_][A-Za-z0-9_]*$' | paste -sd, -)"
	printf -- '--preserve-env=%s\n' "$names"
}
