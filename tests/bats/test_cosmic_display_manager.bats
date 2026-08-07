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
