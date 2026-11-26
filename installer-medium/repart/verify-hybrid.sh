#!/usr/bin/env bash
# Prove the medium is hybrid: a GPT for USB and an El Torito boot image for CD (tunaOS#4913).
#
# Usage: installer-medium/repart/verify-hybrid.sh OUT.ISO [--dry-run]
#
# Fails when the file has no GPT with an ESP, or no El Torito boot catalog
# (UEFI platform entry), so a medium that boots from one lane only is never
# published. Needs sfdisk and xorriso (CI has both); reads the file only.
set -euo pipefail

IMG="${1:?usage: verify-hybrid.sh OUT.ISO [--dry-run]}"
if [[ "${2:-}" = "--dry-run" ]]; then
	echo "sfdisk --json ${IMG}: require label gpt and an EFI System partition"
	echo "xorriso -indev ${IMG} -report_el_torito plain: require a UEFI El Torito boot image (dry run: nothing read)"
	exit 0
fi
ESP_TYPE="C12A7328-F81F-11D2-BA4B-00A0C93EC93B"

table="$(sfdisk --json "${IMG}")"
python3 -I - "${table}" "${ESP_TYPE}" <<'PY'
import json, sys
pt = json.loads(sys.argv[1])["partitiontable"]
if pt.get("label") != "gpt":
    sys.exit(f"verify-hybrid: partition table is {pt.get('label')!r}, USB boots need gpt")
if not any(p["type"].upper() == sys.argv[2] for p in pt["partitions"]):
    sys.exit("verify-hybrid: no EFI System partition in the GPT")
PY

report="$(xorriso -indev "${IMG}" -report_el_torito plain 2>&1)"
grep -Eqi 'platform.*(0xef|UEFI)|El Torito boot img.*UEFI' <<<"${report}" || {
	echo "verify-hybrid: no UEFI El Torito boot image; CD boots would fail" >&2
	echo "${report}" >&2
	exit 1
}
echo "verify-hybrid: ${IMG} has a GPT with an ESP and a UEFI El Torito image"
