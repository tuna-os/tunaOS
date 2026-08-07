#!/usr/bin/env bats
# COSMIC's display manager is whichever one already claimed
# display-manager.service, and greetd only when nothing has.
#
# configure-desktop-runtime.sh mapped `cosmic` straight to greetd. On Ubuntu
# the PPA's cosmic-greeter deb enables cosmic-greeter.service and repoints
# display-manager.service at it in its postinst, so the next line —
# `systemctl enable greetd.service`, deliberately not `|| true` — hard-failed
# and took the whole image build with it:
#
#   Failed to enable unit: File '/etc/systemd/system/display-manager.service'
#   already exists and is a symlink to /lib/systemd/system/cosmic-greeter.service
#
# grouper:cosmic, LUKS run 31135761136 — the third distinct failure that cell
# hit, each one further along than the last.
#
# The fix tests the SYMLINK, not whether cosmic-greeter is installed, and that
# distinction is the entire safety argument. Fedora and EL10 install
# cosmic-greeter as well, and their cosmic cells are green today *because*
# `systemctl enable greetd` succeeds there — direct evidence that their RPM
# scriptlets do not touch the alias. A package-presence test would have
# repointed those images; a symlink test cannot. The last case below pins
# exactly that.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/desktop/configure-desktop-runtime.sh"

# Run the script's `case` up to the point dm is chosen, with a fake sysroot.
# systemctl is stubbed out: what is under test is the selection, and the real
# thing needs a booted system it cannot have in a container build either.
choose_dm() {
	local link_target="$1" desktop="${2:-cosmic}"
	local root="${BATS_TEST_TMPDIR}/${BATS_TEST_NUMBER}"
	rm -rf "$root"
	mkdir -p "$root/etc/systemd/system" "$root/lib/systemd/system"
	if [ -n "$link_target" ]; then
		touch "$root/lib/systemd/system/${link_target}"
		ln -sf "$root/lib/systemd/system/${link_target}" \
			"$root/etc/systemd/system/display-manager.service"
	fi

	# Take the case block verbatim, retargeting only the absolute path it
	# reads so it looks at the fake sysroot instead of the runner's own.
	local block
	block="$(awk '/^case "\$desktop" in$/{f=1} f{print} f&&/^esac$/{exit}' "$SCRIPT" |
		sed "s#/etc/systemd/system/display-manager.service#${root}/etc/systemd/system/display-manager.service#")"

	bash -c "
		desktop='${desktop}'
		systemctl() { return 1; }   # no unit files exist in a fake root
		${block}
		echo \"\$dm\"
	"
}

@test "the case block was actually extracted" {
	run awk '/^case "\$desktop" in$/{f=1} f{print} f&&/^esac$/{exit}' "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"cosmic)"* ]]
	[[ "$output" == *"esac"* ]]
	[ "$(wc -l <<<"$output")" -ge 15 ]
}

# The regression: this is the grouper case.
@test "cosmic defers to cosmic-greeter when it already owns the alias" {
	run choose_dm cosmic-greeter.service
	[ "$output" = "cosmic-greeter" ]
}

# The safety case: Fedora/EL10, where nothing claimed the alias. These cells
# are green on greetd and must stay on greetd.
@test "cosmic still picks greetd when nothing claimed the alias" {
	run choose_dm ""
	[ "$output" = "greetd" ]
}

# A different greeter owning the alias is not cosmic-greeter, and must not be
# mistaken for it by a sloppy substring match.
@test "cosmic picks greetd when some other DM owns the alias" {
	run choose_dm gdm.service
	[ "$output" = "greetd" ]
}

# niri shared the `niri | cosmic)` arm before this change. It has no
# cosmic-greeter and must be untouched by the split.
@test "niri is unaffected by the split" {
	run choose_dm "" niri
	[ "$output" = "greetd" ]
	run choose_dm cosmic-greeter.service niri
	[ "$output" = "greetd" ]
}

# Forcing the alias is the wrong instrument here — the kde comment in this
# same file records why (tunaOS#824). Pin that it is not how this was fixed.
# Comments are stripped first: the cosmic branch deliberately NAMES --force in
# prose to record why it is the wrong instrument, and that explanation is worth
# more than the grep is.
@test "the fix does not force the display-manager alias" {
	run sh -c "grep -v '^[[:space:]]*#' '$SCRIPT' | grep 'systemctl enable'"
	[ "$status" -eq 0 ]
	[ -n "$output" ]
	[[ "$output" != *"--force"* ]]
	[[ "$output" != *" -f "* ]]
}

# The distinction the safety argument rests on: presence of the unit file is
# NOT what is tested. If someone "simplifies" this to a list-unit-files check,
# Fedora and EL10 cosmic get repointed and this fails.
@test "selection keys off the symlink, not whether cosmic-greeter exists" {
	run awk '/^cosmic\)$/{f=1} f{print} f&&/^\t;;$/{exit}' "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"readlink"* ]]
	[[ "$output" == *"display-manager.service"* ]]
	[[ "$output" != *"list-unit-files cosmic-greeter"* ]]
}

# ── The diagnostic on the enable itself ─────────────────────────────────────
#
# The selection above prevents the known collision. This covers the next one:
# when `systemctl enable` fails, the build must say WHICH case it is, because
# the two have opposite fixes (defer to the claimant vs install the missing
# package) and systemd's own message distinguishes neither.

# Run just the enable-and-diagnose block against a fake sysroot, with
# systemctl stubbed to fail the way the real one does.
run_enable() {
	local link_target="$1"
	local root="${BATS_TEST_TMPDIR}/enable-${BATS_TEST_NUMBER}"
	rm -rf "$root"
	mkdir -p "$root/etc/systemd/system" "$root/lib/systemd/system"
	if [ -n "$link_target" ]; then
		touch "$root/lib/systemd/system/${link_target}"
		ln -sf "$root/lib/systemd/system/${link_target}" \
			"$root/etc/systemd/system/display-manager.service"
	fi

	local block
	block="$(awk '/^if ! systemctl enable /{f=1} f{print} f&&/^fi$/{exit}' "$SCRIPT" |
		sed "s#/etc/systemd/system/display-manager.service#${root}/etc/systemd/system/display-manager.service#")"

	bash -c "
		set -euo pipefail
		desktop=cosmic
		dm=greetd
		systemctl() { return 1; }
		${block}
	" 2>&1
}

@test "the enable block was actually extracted" {
	run awk '/^if ! systemctl enable /{f=1} f{print} f&&/^fi$/{exit}' "$SCRIPT"
	[ "$status" -eq 0 ]
	[[ "$output" == *"readlink"* ]]
	[ "$(wc -l <<<"$output")" -ge 8 ]
}

@test "a claimed alias names the claimant and points at deferring" {
	run run_enable cosmic-greeter.service
	[ "$status" -ne 0 ]
	[[ "$output" == *"already claimed by cosmic-greeter.service"* ]]
	[[ "$output" == *"Defer to it"* ]]
	# The other diagnosis must NOT also be printed — two contradictory
	# suggestions is no better than none.
	[[ "$output" != *"not installed"* ]]
}

@test "an unclaimed alias points at the missing package instead" {
	run run_enable ""
	[ "$status" -ne 0 ]
	[[ "$output" == *"not installed"* ]]
	[[ "$output" != *"already claimed by"* ]]
}

# If display-manager.service already points at the very unit we are enabling,
# the failure is not a collision — saying "claimed by greetd.service, defer to
# it" would be nonsense advice to defer to yourself.
@test "the alias pointing at our own unit is not reported as a collision" {
	run run_enable greetd.service
	[ "$status" -ne 0 ]
	[[ "$output" != *"already claimed by"* ]]
	[[ "$output" == *"not installed"* ]]
}

# The whole point of not using `|| true`: an image with no display manager is
# worse than a failed build.
@test "a failed enable still fails the build" {
	run run_enable cosmic-greeter.service
	[ "$status" -eq 1 ]
}

# ── The other half: install-desktop.sh ──────────────────────────────────────
#
# Deferring in configure-desktop-runtime.sh stops the build from dying, but
# install-desktop.sh resolves the manifest's display_manager independently and
# then FORCE-LINKS it into graphical.target.wants. Ubuntu's greetd.service
# carries `[Install] Alias=display-manager.service` and no WantedBy=, so that
# link is the only thing that would ever start greetd on an image where
# cosmic-greeter owns the alias -- and cosmic-greeter.service is itself
# `ExecStart=greetd --config /etc/greetd/cosmic-greeter.toml` with `vt = "1"`.
# Two units running greetd on vt1, both Restart=always, is the
# two-DMs-racing-for-seat0 state that file's own sibling-link cleanup exists to
# prevent.
INSTALLER="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"

# Run install-desktop.sh's greetd-resolution block against a fake sysroot.
resolve_installer_dm() {
	local link_target="$1" declared="${2:-greetd}"
	local root="${BATS_TEST_TMPDIR}/inst-${BATS_TEST_NUMBER}"
	rm -rf "$root"
	mkdir -p "$root/etc/systemd/system" "$root/usr/lib/systemd/system"
	if [ -n "$link_target" ]; then
		touch "$root/usr/lib/systemd/system/${link_target}"
		ln -sf "$root/usr/lib/systemd/system/${link_target}" \
			"$root/etc/systemd/system/display-manager.service"
	fi

	local block
	block="$(awk '/^if \[\[ "\$\{_TD_DM\}" == "greetd" \]\]; then$/{f=1} f{print} f&&/^fi$/{exit}' "$INSTALLER" |
		sed "s#/etc/systemd/system/display-manager.service#${root}/etc/systemd/system/display-manager.service#")"

	bash -c "
		_TD_DM='${declared}'
		${block}
		echo \"\${_TD_DM}\"
	" | tail -1
}

@test "the installer's resolution block was actually extracted" {
	run awk '/^if \[\[ "\$\{_TD_DM\}" == "greetd" \]\]; then$/{f=1} f{print} f&&/^fi$/{exit}' "$INSTALLER"
	[ "$status" -eq 0 ]
	[[ "$output" == *"cosmic-greeter.service"* ]]
	[[ "$output" == *"readlink"* ]]
}

@test "install-desktop.sh wants cosmic-greeter, not a second greetd on vt1" {
	run resolve_installer_dm cosmic-greeter.service
	[ "$output" = "cosmic-greeter" ]
}

@test "install-desktop.sh leaves greetd alone when nothing claimed the alias" {
	run resolve_installer_dm ""
	[ "$output" = "greetd" ]

	run resolve_installer_dm gdm.service
	[ "$output" = "greetd" ]
}

# A dangling alias is the openSUSE-shaped case the block below this one in
# install-desktop.sh reclaims. It must not be read as a cosmic-greeter claim.
@test "install-desktop.sh ignores an alias pointing at a unit that is gone" {
	local root="${BATS_TEST_TMPDIR}/dangling"
	mkdir -p "$root/etc/systemd/system"
	ln -sf "$root/usr/lib/systemd/system/cosmic-greeter.service" \
		"$root/etc/systemd/system/display-manager.service"
	local block
	block="$(awk '/^if \[\[ "\$\{_TD_DM\}" == "greetd" \]\]; then$/{f=1} f{print} f&&/^fi$/{exit}' "$INSTALLER" |
		sed "s#/etc/systemd/system/display-manager.service#${root}/etc/systemd/system/display-manager.service#")"
	run bash -c "_TD_DM='greetd'; ${block}; echo \"\${_TD_DM}\""
	[ "$output" = "greetd" ]
}

# ── And the contracts that judge the result ─────────────────────────────────
#
# dm_id is `systemctl show -P Id display-manager.service`, so on Ubuntu it
# reads cosmic-greeter.service and on Fedora/EL10 greetd.service. A pattern
# pinned to greetd alone would fail grouper:cosmic at boot -- fatally in
# verify-desktop-experience.sh (dm_mismatch), and as a TAP failure harvested
# from the serial console in e2e-runtime-checks.sh -- on a COSMIC login screen
# that is working exactly as intended.
@test "both runtime contracts accept either greeter as cosmic's DM" {
	local f
	for f in "${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh" \
		"${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"; do
		run grep -c "greetd|cosmic-greeter" "$f"
		[ "$status" -eq 0 ]
		[ "$output" -ge 1 ]
	done
}

# niri keeps the strict pattern: it has no cosmic-greeter, and widening it
# there would accept a greeter that variant never installs.
@test "niri's contracts still pin greetd alone" {
	local f
	for f in "${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh" \
		"${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"; do
		run grep -E "^niri\)? *(\)|dm_pattern)" "$f"
		[ "$status" -eq 0 ]
	done
	run grep -E "^niri\) dm_pattern='\^greetd" "${REPO_ROOT}/build_scripts/checks/e2e-runtime-checks.sh"
	[ "$status" -eq 0 ]
}
