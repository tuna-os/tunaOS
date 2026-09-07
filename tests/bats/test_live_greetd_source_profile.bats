#!/usr/bin/env bats
# greetd must not source the login profile for a live autologin session.
#
# greetd's source_profile defaults to true, which means it does not exec the
# session command directly — it wraps it:
#
#   /bin/sh -c '[ -f /etc/profile ] && . /etc/profile; ...; exec <command>'
#
# MEASURED on a marlin:cosmic dev ISO, from inside the live guest:
#
#   859 S+  do_wait     /bin/sh -c ... . /etc/profile; ... exec cosmic-session
#   882 Sl+ wait_woken  umotd
#
# umotd (/etc/profile.d/umotd.sh, from the ublue common payload) blocks in a
# non-interactive session, so the shell waits forever and never reaches exec.
# Everything else looks healthy — greetd active, autologin succeeded, no
# failed units, graphical.target active — and there is still no compositor and
# no installer. That is the most expensive kind of failure to diagnose, so it
# is pinned here.
#
# Applies to every desktop whose live adapter autologins through greetd.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

greetd_adapters() {
	grep -rl 'greetd' "${REPO_ROOT}/live-iso/common/src/" --include='desktop-*.sh'
}

@test "every greetd live adapter writes a greetd config" {
	local found=0
	while read -r f; do
		grep -q '/etc/greetd/config.toml' "$f" && found=$((found + 1))
	done < <(greetd_adapters)
	[ "$found" -ge 1 ]
}

@test "every greetd config disables source_profile" {
	while read -r f; do
		grep -q '/etc/greetd/config.toml' "$f" || continue
		# One [general] source_profile = false per config heredoc.
		local configs profiles
		configs=$(grep -c 'tee /etc/greetd/config.toml' "$f" || true)
		profiles=$(grep -c 'source_profile = false' "$f" || true)
		[ "$profiles" -ge "$configs" ] || {
			echo "$f writes $configs greetd config(s) but disables"
			echo "source_profile $profiles time(s) — a config without it hangs"
			echo "the session in /etc/profile (umotd)."
			return 1
		}
	done < <(greetd_adapters)
}

@test "source_profile is set in the [general] section, where greetd reads it" {
	# In any other section greetd ignores it and the hang comes back silently.
	while read -r f; do
		grep -q 'source_profile' "$f" || continue
		grep -B 1 'source_profile = false' "$f" | grep -q '\[general\]'
	done < <(greetd_adapters)
}
