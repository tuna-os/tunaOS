#!/usr/bin/env bash
# Point greetd at gtkgreet, for desktops whose base has no greeter of its own.
#
# greetd ships no graphical greeter: its stock config runs `agreety --cmd
# /bin/sh`, i.e. a text prompt into a bare shell with no session picker. The
# COSMIC and DMS variants never hit this because cosmic-greeter and dms-greeter
# ship their own config.toml. openSUSE has neither packaged (quickshell, which
# DMS needs, is not in Tumbleweed at all), so sailfin:niri installed greetd and
# got the text prompt.
#
# This is sourced by install-desktop.sh via a manifest's post_install list, so
# it must never call `exit` — that would end the whole desktop install.
#
# Deliberately a no-op unless gtkgreet AND cage both landed: if packaging
# regresses, leaving greetd's own config in place fails loudly at a text prompt
# rather than silently launching a greeter that is not installed. That also
# makes it safe to list on manifests shared with variants that use a different
# greeter — on Fedora/EL10 niri, dms-greeter is installed and gtkgreet is not,
# so this block does nothing and the DMS config survives.
if command -v gtkgreet &>/dev/null && command -v cage &>/dev/null; then
	echo "Configuring greetd to use gtkgreet"
	# The account greetd runs the greeter as is NOT named the same on every
	# distro, and getting it wrong is fatal in milliseconds: greetd chowns its
	# IPC socket to that user and getpwnam()s it during startup, so an
	# unresolvable name means "unable to get user info", exit(1), and — with
	# the packaged unit's Restart=always — a display manager that never
	# becomes active. That is the black screen behind
	# TUNAOS_DESKTOP_CONTRACT_FAIL reason=dm_inactive on sailfin:niri, with
	# zero failed units and nothing on the console, because greetd was already
	# dead before the contract sampled it.
	#
	# Fedora and EL package the account with greetd itself and call it
	# `greetd`. openSUSE moved it out into system-user-greeter, which creates
	# `greeter` (home /var/lib/greetd, member of video) — greetd there
	# Requires user(greeter) and there is no `greetd` user on Tumbleweed at
	# all. So resolve the account instead of hardcoding one.
	_GG_USER=""
	for _GG_CANDIDATE in greetd greeter; do
		if getent passwd "${_GG_CANDIDATE}" >/dev/null 2>&1; then
			_GG_USER="${_GG_CANDIDATE}"
			break
		fi
	done
	if [[ -z "${_GG_USER}" ]]; then
		# Every distro that packages greetd creates one of these two. If
		# neither exists the greeter cannot run at all, and writing a config
		# naming a missing user would ship the restart loop described above.
		# Fail the build rather than the login screen. (`return`, not `exit`:
		# this file is sourced by install-desktop.sh, which runs under set -e
		# and so aborts on a non-zero return.)
		echo "ERROR: no greetd greeter account found (tried: greetd, greeter)" >&2
		echo "       greetd would exit at startup with 'unable to get user info'." >&2
		return 1
	fi
	echo "greetd greeter account: ${_GG_USER}"
	# gtkgreet is a plain Wayland client and cannot own a VT, so cage hosts
	# it. -s keeps VT switching available (without it a greeter crash locks
	# you out of the machine entirely).
	# cage is wlroots-based and needs a renderer. A VM without virgl has a DRM
	# card (virtio-gpu) but NO render node, so GL initialisation fails, cage
	# exits, greetd restarts it forever and never reaches active — a black
	# screen with no login. That is not a CI artefact: it is GNOME Boxes,
	# VirtualBox and every plain `-vga virtio` guest, which is exactly how
	# most people will first try TunaOS. scripts/iso-e2e.sh:281 says the same
	# thing about this runner ("no render node/virgl — niri/xfwl4 will not
	# render here").
	#
	# So pick the renderer at boot rather than baking one in: software
	# (pixman) only when there is no render node, hardware GL everywhere else.
	# A login screen is cheap to render, so the fallback costs nothing where
	# it is used, and machines with a GPU are unaffected.
	install -Dm0755 /dev/stdin /usr/libexec/tunaos/greetd-session <<'SESSION_EOF'
#!/usr/bin/env bash
# Launch gtkgreet under cage on hardware that may have neither 3D nor a GPU
# ready yet. Two distinct failures, both measured in the sailfin niri Gate:
#
#   1. The DRM device appears LATE. greetd is ordered only after
#      systemd-user-sessions, not after the GPU, and the boot log shows
#      virtio_gpu registering at 50.62s — the same instant greetd started.
#      cage with no /dev/dri/card* exits immediately, greetd restarts it, and
#      the unit never settles: "Started Greeter daemon" appears, yet
#      `systemctl is-active display-manager.service` is false a fraction of a
#      second later, with zero failed units. That is a restart loop, not a
#      crash, which is why it reads as dm_inactive rather than a failure.
#   2. There may be no 3D at all: the same log shows
#      "[drm] features: -virgl", so GL initialisation cannot succeed even once
#      the device exists. wlroots' pixman renderer draws fine on dumb buffers.
#
# Waiting for card* fixes (1); forcing pixman when no render node exists fixes
# (2). A render node is the honest test for 3D here — virtio-gpu without virgl
# exposes card* but no renderD*.
for _ in $(seq 1 30); do
	compgen -G '/dev/dri/card*' >/dev/null 2>&1 && break
	sleep 0.5
done
if ! compgen -G '/dev/dri/renderD*' >/dev/null 2>&1; then
	export WLR_RENDERER=pixman
	export LIBGL_ALWAYS_SOFTWARE=1
fi
exec cage -s -- gtkgreet -l -s /etc/greetd/gtkgreet.css
SESSION_EOF

	mkdir -p /etc/greetd
	cat >/etc/greetd/config.toml <<GREETD_EOF
[terminal]
vt = 1

[default_session]
command = "/usr/libexec/tunaos/greetd-session"
user = "${_GG_USER}"
GREETD_EOF

	# Greeter styling. Kept deliberately small: gtkgreet is GTK3, so it
	# already picks up the session's GTK theme, icons, cursor and font — this
	# only supplies the pieces a theme cannot know about (the layer-shell
	# background behind the login window).
	cat >/etc/greetd/gtkgreet.css <<'CSS_EOF'
/* TunaOS greeter.
 *
 * gtkgreet inherits the system GTK3 theme, which is the whole reason it is the
 * fallback greeter: the login screen and the session it launches are styled by
 * the same theme. Only the layer-shell background and the login window's
 * framing are set here — everything else is intentionally left to the theme so
 * retheming the desktop rethemes the greeter too.
 */
window {
	background-image: linear-gradient(to bottom, #2b3d4f, #1b2733);
	background-color: #1b2733;
}

/* The login box: lift it off the background, otherwise the themed widgets
 * float on the gradient with no visual container. */
box#window-box {
	background-color: @theme_bg_color;
	border-radius: 8px;
	padding: 24px;
}
CSS_EOF

	# greetd runs the greeter as its own unprivileged user; it must be able to
	# read both files.
	chmod 0644 /etc/greetd/config.toml /etc/greetd/gtkgreet.css
fi
