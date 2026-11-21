#!/usr/bin/env bats
# The terminal login banner names this project, never Bluefin.
#
# projectbluefin/common's umotd printed this in every interactive shell of
# bonito 69f7e8a (measured with `podman run … umotd`):
#
#   ujust bluefin-cli                   │ Enable terminal bling
#   • Report an issue https://issues.projectbluefin.io/
#   • Ask Bluefin https://ask.projectbluefin.io/
#   • Documentation https://docs.projectbluefin.io/
#
# build_scripts/tunaos-login-banner.sh rewrites umotd's and uwelcome's
# configs. These tests run it over a scratch root that holds upstream's files
# verbatim.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/tunaos-login-banner.sh"
IMAGE_INFO="${REPO_ROOT}/build_scripts/90-image-info.sh"

setup() {
	ROOT="$(mktemp -d)"
	mkdir -p "${ROOT}/etc/umotd" "${ROOT}/etc/uwelcome"
	# /etc/umotd/config.json from bonito 69f7e8a (the common pin).
	cat >"${ROOT}/etc/umotd/config.json" <<'EOF'
{
  "commands": [
    {"cmd": "ujust --choose", "desc": "cmd_list"},
    {"cmd": "umotd toggle", "desc": "motd_toggle"},
    {"cmd": "ujust bluefin-cli", "desc": "term_bling"},
    {"cmd": "brew help", "desc": "cli_pkg"}
  ],
  "links": [
    {"name": "issues", "url": "https://issues.projectbluefin.io/"},
    {"name": "Ask Bluefin", "url": "https://ask.projectbluefin.io/"},
    {"name": "docs", "url": "https://docs.projectbluefin.io/"}
  ],
  "prefix": "X ",
  "tips-presets": ["bluefin", "gnome", "ublue", "ublue-dev"],
  "use-accent-color": true
}
EOF
	# /etc/uwelcome/config.toml from projectbluefin/common main.
	cat >"${ROOT}/etc/uwelcome/config.toml" <<'EOF'
version = 1
[[commands]]
cmd = "ujust bluefin-cli"
desc = "term_bling"
[[links]]
name = "issues"
url = "https://issues.projectbluefin.io/"
EOF
	export DOCUMENTATION_URL="https://docs.example.org" BUG_REPORT_URL="https://example.org/issues"
}

teardown() {
	rm -rf "$ROOT"
}

@test "umotd: our links, no Bluefin recipe, no tips, accent kept" {
	run "$SCRIPT" "$ROOT"
	[ "$status" -eq 0 ]
	local c="${ROOT}/etc/umotd/config.json"
	[ "$(jq -c '.links' "$c")" = '[{"name":"issues","url":"https://example.org/issues"},{"name":"docs","url":"https://docs.example.org"}]' ]
	[ "$(jq -r '[.commands[].cmd] | join(",")' "$c")" = "ujust --choose,umotd toggle,brew help" ]
	# The compiled-in tips name Bluefin, Aurora, Bazzite and Universal Blue.
	[ "$(jq -c '."tips-presets"' "$c")" = "[]" ]
	[ "$(jq -r '.prefix' "$c")" = "" ]
	[ "$(jq -r '."use-accent-color"' "$c")" = "true" ]
}

@test "uwelcome: rewritten with our links and no Bluefin recipe" {
	run "$SCRIPT" "$ROOT"
	[ "$status" -eq 0 ]
	local c="${ROOT}/etc/uwelcome/config.toml"
	python3 - "$c" <<'PY'
import sys, tomllib
config = tomllib.load(open(sys.argv[1], "rb"))
assert [l["url"] for l in config["links"]] == ["https://example.org/issues", "https://docs.example.org"], config["links"]
cmds = [c["cmd"] for c in config["commands"]]
assert "ujust bluefin-cli" not in cmds and "ujust report" not in cmds, cmds
assert config["greeting"]["prefix"] == ""
PY
}

@test "an image without either banner is left alone" {
	rm -rf "${ROOT}/etc/umotd" "${ROOT}/etc/uwelcome"
	run "$SCRIPT" "$ROOT"
	[ "$status" -eq 0 ]
	[ ! -e "${ROOT}/etc/umotd" ]
	[ ! -e "${ROOT}/etc/uwelcome" ]
}

# Falsification: drop the closing grep loop from tunaos-login-banner.sh, and
# an upstream command naming another project survives with exit 0.
@test "a banner that still names another project stops the build" {
	jq '.commands += [{"cmd": "ujust aurora-setup", "desc": "x"}]' \
		"${ROOT}/etc/umotd/config.json" >"${ROOT}/c" && mv "${ROOT}/c" "${ROOT}/etc/umotd/config.json"
	run "$SCRIPT" "$ROOT"
	[ "$status" -ne 0 ]
	[[ "$output" == *"still names another project"* ]]
}

@test "the URLs are required, not defaulted" {
	run env -u DOCUMENTATION_URL "$SCRIPT" "$ROOT"
	[ "$status" -ne 0 ]
}

# Being invoked is not being reached (AGENTS.md): the call must come before
# any exit in 90-image-info.sh that a successful build can take. Every exit
# there is `exit 1`, so this asserts the call exists, passes both URLs and
# runs unconditionally at the top level.
# Falsification: remove the call, or nest it under an `if`, and this fails.
@test "90-image-info.sh runs it at top level with both URLs" {
	run grep -nE '^DOCUMENTATION_URL="\$\{DOCUMENTATION_URL\}" BUG_REPORT_URL="\$\{BUG_REPORT_URL\}" \\$' "$IMAGE_INFO"
	[ "$status" -eq 0 ]
	local line="${output%%:*}"
	sed -n "$((line + 1))p" "$IMAGE_INFO" | grep -qx $'\t/run/context/build_scripts/tunaos-login-banner.sh'
	! grep -nE '^\s*exit 0' "$IMAGE_INFO"
}
