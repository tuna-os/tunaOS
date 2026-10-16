#!/usr/bin/env bash
# Give a bare greetd its system integration: greeter account, PAM services,
# state directory and SELinux labels.
#
# The TunaOS factory's greetd (tuna-os/tunaos-packages packages/greetd, the
# only greetd an EL10 image may install now that COPRs are retired) ships the
# daemon and its unit and nothing else: "Configuration and PAM policy remain
# image-owned." Without the rest, greetd cannot start a greeter at all. It
# runs the greeter as `greetd`, which does not exist, and authenticates through
# the `greetd-greeter` and `greetd` PAM services, which fall back to `other`
# (deny). Distribution packages (Arch, Fedora, openSUSE) ship all of it, so
# this is a no-op there: it acts only when greetd is installed and its PAM
# service is missing.
#
# The files mirror Fedora's greetd packaging (tunaos-packages
# src/hummingbird/greetd: greetd.pam, greetd-greeter.pam, greetd.sysusers,
# greetd.tmpfiles, greetd.fc) so EL10 behaves like the Fedora cells.
#
# Sourced by install-desktop.sh (post_install); list it BEFORE
# greetd-gtkgreet.sh, which needs the greeter account to exist. `return`,
# not `exit`, on failure: install-desktop.sh runs under set -e.

if command -v greetd &>/dev/null && [[ ! -e /etc/pam.d/greetd && ! -e /usr/lib/pam.d/greetd ]]; then
	echo "greetd ships no system integration; installing the image-owned account, PAM services and SELinux labels"

	install -Dm0644 /dev/stdin /usr/lib/sysusers.d/greetd.conf <<'EOF'
#Type Name   ID    GECOS           Home directory  Shell
u     greetd -     "greetd daemon" /var/lib/greetd
EOF
	# Create the account now: greetd-gtkgreet.sh resolves it at build time,
	# and the greeter configuration names it.
	systemd-sysusers /usr/lib/sysusers.d/greetd.conf || return 1

	install -Dm0644 /dev/stdin /usr/lib/tmpfiles.d/greetd.conf <<'EOF'
#  Path            Mode User   Group  Age Argument
d  /var/lib/greetd 0750 greetd greetd -   -
EOF

	install -Dm0644 /dev/stdin /etc/pam.d/greetd <<'EOF'
#%PAM-1.0
auth       substack    system-auth
-auth       optional    pam_gnome_keyring.so
auth       include     postlogin

account    required    pam_sepermit.so
account    required    pam_nologin.so
account    include     system-auth

password   include     system-auth

session    required    pam_selinux.so close
session    required    pam_loginuid.so
session    required    pam_selinux.so open
session    optional    pam_keyinit.so force revoke
session    required    pam_namespace.so
session    include     system-auth
-session    optional    pam_gnome_keyring.so auto_start
session    include     postlogin
EOF

	install -Dm0644 /dev/stdin /etc/pam.d/greetd-greeter <<'EOF'
#%PAM-1.0
# The greeter session itself starts without authentication.
auth            required pam_env.so
auth            required pam_permit.so
account         required pam_permit.so
password        required pam_deny.so
session         required pam_unix.so
session         optional pam_systemd.so
EOF

	# Fedora's greetd-selinux labels greetd as a display manager (xdm_*), so
	# pam_selinux can move the user session into the user's own domain. A
	# greetd left at bin_t runs as unconfined_service_t instead.
	if command -v selinuxenabled &>/dev/null || [[ -d /etc/selinux/targeted ]]; then
		command -v semanage &>/dev/null || dnf_retry -y install policycoreutils-python-utils || return 1
		semanage fcontext -a -t xdm_exec_t '/usr/bin/greetd' || return 1
		semanage fcontext -a -t xdm_etc_t '/etc/greetd(/.*)?' || return 1
		semanage fcontext -a -t xdm_var_lib_t '/var/lib/greetd(/.*)?' || return 1
		# /run, not Fedora's /var/run spelling: the policy's /var/run = /run
		# equivalence rejects a local rule under /var/run.
		semanage fcontext -a -t xdm_var_run_t -f s '/run/greetd[^/]*\.sock' || return 1
		semanage fcontext -a -t xdm_var_run_t -f f '/run/greetd\.run' || return 1
	fi
fi
