#!/usr/bin/env bash
# Point ublue's terminal login banner at this project, not at Bluefin.
#
# projectbluefin/common ships a banner that every interactive shell prints
# (/etc/profile.d/umotd.sh, fish_greeting). Measured in bonito 69f7e8a:
#
#   ujust bluefin-cli                   │ Enable terminal bling
#   • Report an issue https://issues.projectbluefin.io/
#   • Ask Bluefin https://ask.projectbluefin.io/
#   • Documentation https://docs.projectbluefin.io/
#
# The current common pin ships umotd (/etc/umotd/config.json). Newer common
# renames it uwelcome (/etc/uwelcome/config.toml), so both are rewritten.
# umotd's compiled-in tips name Bluefin, Aurora, Bazzite and Universal Blue
# ("**Love Aurora?** Help keep it going…"), so its tip presets are emptied.
# The welcome line already names the variant: it reads os-release.
#
#   tunaos-login-banner.sh           # the running build root
#   tunaos-login-banner.sh <root>    # write under <root> instead (tests)
#
# Needs DOCUMENTATION_URL and BUG_REPORT_URL ([defaults.branding] in
# tunaos.toml, through identity.env); 90-image-info.sh exports them.

set -euo pipefail

root="${1:-}"
docs="${DOCUMENTATION_URL:?DOCUMENTATION_URL is required}"
issues="${BUG_REPORT_URL:?BUG_REPORT_URL is required}"
umotd="${root}/etc/umotd/config.json"
uwelcome="${root}/etc/uwelcome/config.toml"

if [[ -f "$umotd" ]]; then
	python3 - "$umotd" "$docs" "$issues" <<'PY'
import json
import sys

path, docs, issues = sys.argv[1:]
with open(path, encoding="utf-8") as f:
    config = json.load(f)
# `ujust bluefin-cli` is Bluefin's own recipe; the rest are generic.
config["commands"] = [c for c in config.get("commands", []) if "bluefin" not in c.get("cmd", "")]
# "issues" and "docs" are umotd's translated labels ("Report an issue",
# "Documentation"); any other name prints verbatim.
config["links"] = [{"name": "issues", "url": issues}, {"name": "docs", "url": docs}]
config["tips-presets"] = []
# Upstream's prefix is a Bluefin icon glyph.
config["prefix"] = ""
with open(path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY
	echo "Login banner: ${umotd} links ${issues} ${docs}"
fi

if [[ -f "$uwelcome" ]]; then
	# Upstream's file minus `ujust bluefin-cli`, `ujust report` (Bluefin's
	# report flow) and the Bluefin glyph, with our links. TOML has no writer
	# in the Python standard library, and the file is this small.
	cat >"$uwelcome" <<TOML
# Written by build_scripts/tunaos-login-banner.sh.
version = 1
color = "auto"

[motd]
messages = []
commands = []

[greeting]
prefix = ""

[[commands]]
cmd = "ujust --choose"
desc = "cmd_list"

[[commands]]
cmd = "uwelcome toggle"
desc = "banner_toggle"

[[commands]]
cmd = "brew help"
desc = "cli_pkg"

[[links]]
name = "issues"
url = "${issues}"

[[links]]
name = "docs"
url = "${docs}"
TOML
	echo "Login banner: ${uwelcome} links ${issues} ${docs}"
fi

# The applied state: whatever the banner reads must not name another project.
for config in "$umotd" "$uwelcome"; do
	[[ -f "$config" ]] || continue
	if grep -inE 'bluefin|aurora|bazzite|universal ?blue|ublue-os' "$config"; then
		echo "ERROR: ${config} still names another project (lines above)" >&2
		exit 1
	fi
done
