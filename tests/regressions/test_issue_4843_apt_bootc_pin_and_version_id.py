"""tunaOS#4843: apt images track bootc past the Arch ceiling; rolling bases get a VERSION_ID.

Debian sid and Arch images shipped no VERSION_ID, so bootc named GRUB BLS
entries from the deployment digest and the default order after `bootc upgrade`
was arbitrary (wootc E2E 44798646505, 44798653922). bootc 1.16.10 also
reported a queued rollback that was not queued; 1.16.11 fixes it but is held
for Arch only.

Falsification: source-pattern -- reverting any edit turns it red: dropping
`bootc_apt` (or setting it below v1.16.11), removing `matchCurrentVersion` from
the renovate ceiling, pointing build-image-inner.sh or build-toolchain.yml back
at `bootc`, or deleting the VERSION_ID stamp from 90-image-info.sh.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split("."))


def test_apt_pin_is_above_the_rollback_bug_and_arch_ceiling_stays() -> None:
    d = yaml.safe_load((ROOT / "image-versions.yaml").read_text())["downloads"]
    assert _ver(d["bootc_apt"]) >= (1, 16, 11)  # 1.16.10 misreports a queued rollback
    assert d["bootc"] == "v1.16.10"  # Arch has no libselinux


def test_renovate_ceiling_does_not_hold_the_apt_pin() -> None:
    rules = json.loads((ROOT / "renovate.json").read_text())["packageRules"]
    (rule,) = [r for r in rules if "bootc-dev/bootc" in r.get("matchPackageNames", [])]
    assert rule["matchCurrentVersion"] == "<=1.16.10"


def test_apt_builds_and_toolchain_read_the_apt_pin() -> None:
    inner = (ROOT / "scripts/build-image-inner.sh").read_text()
    assert re.search(r"Containerfile\.debian \| Containerfile\.ubuntu\) BOOTC_PIN=bootc_apt", inner)
    wf = (ROOT / ".github/workflows/build-toolchain.yml").read_text()
    assert "get bootc_apt" in wf


def test_image_info_stamps_version_id_only_when_missing() -> None:
    src = (ROOT / "build_scripts/90-image-info.sh").read_text()
    assert "grep -q '^VERSION_ID='" in src
    assert "VERSION_ID_FALLBACK" in src
