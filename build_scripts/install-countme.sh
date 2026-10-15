#!/usr/bin/env bash
# Reassert after upstream copies. The image contract checks effective units
# and metadata rather than only COPY or script invocation.
set -euo pipefail

countme_root="${TUNAOS_COUNTME_ROOT:-/}"
countme_context="${TUNAOS_COUNTME_CONTEXT:-/run/context}"
if ! command -v python3 >/dev/null 2>&1; then
	source "${countme_context}/build_scripts/lib.sh"
	case "${PKG_MGR}" in
	pacman) pkg_install python ;;
	emerge) pkg_install dev-lang/python ;;
	*) pkg_install python3 ;;
	esac
fi

for countme_file in \
	usr/libexec/tunaos-countme \
	usr/bin/tunaos-countme \
	usr/share/tunaos/countme-allowlist.json \
	usr/lib/systemd/system/tunaos-countme.service \
	usr/lib/systemd/system/tunaos-countme.timer; do
	countme_mode=0644
	[[ "$countme_file" == usr/libexec/* || "$countme_file" == usr/bin/* ]] && countme_mode=0755
	install -Dm"$countme_mode" "${countme_context}/files/${countme_file}" "${countme_root}/${countme_file}"
done

# /usr masks avoid changes to administrator choices in /etc.
mkdir -p "${countme_root}/usr/lib/systemd/system" "${countme_root}/usr/lib/systemd/system-preset"
for countme_unit in bluefin-countme dakota-countme bluefin-lts-countme; do
	for countme_type in service timer; do
		ln -sfn /dev/null "${countme_root}/usr/lib/systemd/system/${countme_unit}.${countme_type}"
		rm -f "${countme_root}/usr/lib/systemd/system/timers.target.wants/${countme_unit}.${countme_type}"
		rm -f "${countme_root}/etc/systemd/system/timers.target.wants/${countme_unit}.${countme_type}"
	done
done
cat >"${countme_root}/usr/lib/systemd/system-preset/00-tunaos-countme.preset" <<'EOF'
disable bluefin-countme.*
disable dakota-countme.*
disable bluefin-lts-countme.*
enable tunaos-countme.timer
EOF

# Direct builds must preserve original identity rather than guess a desktop.
# This writes no consent marker and no installation epoch into an image.
COUNTME_ROOT="$countme_root" COUNTME_VARIANT="${IMAGE_NAME_VARIANT:-}" \
	COUNTME_FLAVOR="${TUNAOS_IMAGE_FLAVOR:-}" python3 - <<'PY'
import json
import os
from pathlib import Path
import re

root = Path(os.environ["COUNTME_ROOT"])
variant, flavor = os.environ["COUNTME_VARIANT"], os.environ["COUNTME_FLAVOR"]
if not all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", s) for s in (variant, flavor)):
    raise SystemExit("Countme: original variant and full flavor are required")
target = root / "usr/share/tunaos/countme.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({"schema": 1, "variant": variant, "flavor": flavor}) + "\n")
target.chmod(0o644)
PY

# Enable the timer in the vendor tree; /etc opt-out masks survive image updates.
mkdir -p "${countme_root}/usr/lib/systemd/system/timers.target.wants"
ln -sfn ../tunaos-countme.timer "${countme_root}/usr/lib/systemd/system/timers.target.wants/tunaos-countme.timer"
