#!/usr/bin/env bash
# Backend qualification only: official small bases, no image build or promotion.
set -Eeuo pipefail

family="${1:?usage: test-native-fork-removals.sh rpm|pacman EVIDENCE_DIRECTORY}"
evidence="${2:?evidence directory required}"
case "$family" in
rpm) image='docker.io/library/almalinux:10' ;;
pacman) image='docker.io/library/archlinux:base' ;;
*)
	echo "unsupported native family: $family" >&2
	exit 2
	;;
esac
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Refuse reused output so stale pass records cannot qualify a new run.
mkdir -- "$evidence"
evidence="$(cd -- "$evidence" && pwd)"
git -C "$repo" rev-parse HEAD >"$evidence/source-commit.txt"
printf '%s\n' "$image" >"$evidence/requested-image.txt"
# Resolve the mutable official tag once, record its digest, then run the ID.
timeout --kill-after=15s 180s docker pull "$image" 2>&1 | tee "$evidence/pull.log"
docker image inspect "$image" >"$evidence/container-inspect.json"
image_id="$(docker image inspect --format '{{.Id}}' "$image")"
[[ "$image_id" =~ ^sha256:[a-f0-9]{64}$ ]] || {
	echo 'missing immutable image ID' >&2
	exit 1
}

# Variables in the command below expand inside the disposable container.
# shellcheck disable=SC2016
timeout --kill-after=15s 600s docker run --rm --init --memory=2g --cpus=2 --pids-limit=256 \
	--security-opt=no-new-privileges \
	--mount "type=bind,src=$repo,dst=/src,readonly" \
	--mount "type=bind,src=$evidence,dst=/evidence" \
	--workdir /src \
	--env "TUNAOS_NATIVE_REMOVAL_REQUIRED=$family" \
	--env "TUNAOS_NATIVE_REMOVAL_IMAGE_ID=$image_id" \
	--env TUNAOS_NATIVE_REMOVAL_EVIDENCE=/evidence \
	--env PYTHONDONTWRITEBYTECODE=1 \
	"$image_id" bash -Eeuo pipefail -c '
case "$TUNAOS_NATIVE_REMOVAL_REQUIRED" in
rpm)
    timeout --kill-after=10s 240s dnf -y --setopt=install_weak_deps=False install rpm-build python3-pytest
    rpm -qa --queryformat "%{NAME} %{VERSION}-%{RELEASE}.%{ARCH}\\n" | sort > /evidence/container-packages.txt
    cat /etc/dnf/dnf.conf /etc/yum.repos.d/*.repo > /evidence/package-sources.txt
    ;;
pacman)
    timeout --kill-after=10s 240s pacman -Syu --noconfirm python-pytest
    pacman -Q > /evidence/container-packages.txt
    cat /etc/pacman.conf /etc/pacman.d/mirrorlist > /evidence/package-sources.txt
    ;;
esac
sha256sum build_scripts/lib/fork-removals.sh build_scripts/lib/fork-removal-inventory.py tests/test_fork_removals_native_families.py > /evidence/test-sources.sha256
cat /etc/os-release > /evidence/os-release.txt
timeout --kill-after=10s 300s python3 -m pytest -q -rs -p no:cacheprovider \
    tests/test_fork_removals_native_families.py -k "(test_native_exact_removal or test_native_protected_inventory) and $TUNAOS_NATIVE_REMOVAL_REQUIRED" \
    --basetemp=/tmp/tuna-native-removals --junitxml=/evidence/results.xml
' 2>&1 | tee "$evidence/native-test.log"

# A green pytest exit with skips is not native proof. Require exact case counts.
python3 - "$evidence" "$family" <<'PY'
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = Path(sys.argv[1])
family = sys.argv[2]
managers = {"rpm": ("dnf", "zypper"), "pacman": ("pacman",)}[family]
expected = {f"{family}-{manager}{suffix}": steps
            for manager in managers for suffix, steps in (("", 12 if family == "rpm" else 9), ("-protected", 3))}
cases = ET.parse(root / "results.xml").findall(".//testcase")
assert len(cases) == len(expected), f"wrong case count: {len(cases)}"
assert all(not list(case) for case in cases), "native tests failed, errored or skipped"
for name, steps in expected.items():
    data = json.loads((root / f"{name}.json").read_text())
    assert data.get("passed") is True, f"missing native pass evidence for {name}"
    assert len(data["steps"]) == steps, f"missing transaction evidence for {name}"
print(f"Native {family}: {len(cases)} executed, zero skipped; exact inventories saved.")
PY
