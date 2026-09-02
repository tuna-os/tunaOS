#!/usr/bin/env bats

# The NVIDIA userspace repo is chosen by reading the dist tag off the akmods
# RPM bundle, then templating $releasever into negativo17's .repo file with
# sed. If that read returns more than one line the sed expression is broken
# by the embedded newline and the whole image build dies:
#
#   + AKMODS_EL_VERSION='10
#   10'
#   + sed 's/$releasever/10
#   10/g'
#   sed: -e expression #1, char 16: unterminated `s' command
#
# It happened on yellowfin's cosmic-nvidia, niri-nvidia and xfce-nvidia
# builds every nightly. The cause is `grep -oPm1`: -m1 stops after the first
# matching LINE, but -o prints every match ON that line, so a filename
# carrying the dist tag twice yields two values.

SCRIPT="${BATS_TEST_DIRNAME}/../../build_scripts/overlay/overrides/nvidia/20-nvidia.sh"

# The extraction pipeline, lifted from the script so the test exercises the
# real expression rather than a paraphrase of it.
extract() {
	local tag="$1" dir="$2"
	# shellcheck disable=SC2016
	local line
	line="$(grep -n "AKMODS_${tag}_VERSION=" "$SCRIPT" | head -1 | cut -d: -f2-)"
	# Re-point the hardcoded bundle path at the fixture and evaluate it.
	line="${line//\/tmp\/akmods-nvidia-open-rpms/$dir}"
	eval "$line"
	if [[ "$tag" == "EL" ]]; then printf '%s' "$AKMODS_EL_VERSION"
	else printf '%s' "$AKMODS_FEDORA_VERSION"; fi
}

@test "the dist tag read yields exactly one line when a filename carries it twice" {
	local d="${BATS_TEST_TMPDIR}/rpms"
	mkdir -p "$d"
	# Verbatim shape from the failing build: the kernel version and the RPM's
	# own dist tag both say .el10 in one filename.
	touch "$d/kmod-nvidia-open-6.12.0-257.el10.x86_64-580.95.05-1.el10.x86_64.rpm"
	touch "$d/ublue-os-nvidia-addons-0.14-1.el10.noarch.rpm"

	run extract EL "$d"
	[ "$status" -eq 0 ]
	[ "$output" = "10" ]
	# The bug produced "10\n10"; assert on the line count directly so a
	# future regression cannot hide behind bats' output trimming.
	[ "$(printf '%s' "$output" | wc -l)" -eq 0 ]
}

@test "a Fedora bundle reads its own tag, also as one line" {
	local d="${BATS_TEST_TMPDIR}/rpms-fc"
	mkdir -p "$d"
	touch "$d/kmod-nvidia-open-6.16.3-200.fc42.x86_64-580.95.05-1.fc42.x86_64.rpm"

	run extract FEDORA "$d"
	[ "$status" -eq 0 ]
	[ "$output" = "42" ]
}

@test "an EL value with a newline in it would break the releasever sed" {
	# Proves the consequence rather than assuming it: this is the exact sed
	# form the script uses, fed the value the old pipeline produced.
	run bash -c 'printf "baseurl=x/\$releasever/y\n" | sed "s/\$releasever/$(printf "10\n10")/g"'
	[ "$status" -ne 0 ]
	[[ "$output" == *"unterminated"* ]]
}

@test "the script no longer uses grep -m1 with -o for the dist tag" {
	run grep -E "AKMODS_(EL|FEDORA)_VERSION=.*grep -oPm1" "$SCRIPT"
	[ "$status" -ne 0 ]
}
