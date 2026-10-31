"""tunaOS#3391: KDE image builds executed mutable third-party source content as root.

The KDE image build path fetched third-party source and udev rules from mutable
references (ledif/kcm_ublue release tag, berarma/oversteer master branch, and
bazaar-org/krunner-bazaar tag archive) as root during image build.

All sources must use immutable commit pins in image-versions.yaml or build scripts,
validate the commit hashes before download/execution, and maintain Renovate git-refs
metadata so dependency updates remain reviewable.

Falsification: structural -- restoring release tags, branch heads, or removing
SHA validation causes these tests to fail.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS_YAML = ROOT / "image-versions.yaml"
KCM_SCRIPT = ROOT / "build_scripts" / "desktop" / "kcm-ublue.sh"
RENOVATE_JSON = ROOT / "renovate.json"


def test_kcm_ublue_pin_is_immutable_commit():
    text = VERSIONS_YAML.read_text(encoding="utf-8")
    match = re.search(r'^\s*kcm_ublue:\s*"([^\"]+)"', text, re.MULTILINE)
    assert match, "image-versions.yaml must pin kcm_ublue"
    pin = match.group(1)
    assert re.fullmatch(r"[0-9a-f]{40}", pin), (
        f"kcm_ublue must be a 40-character commit SHA, got: {pin}"
    )
    assert not pin.startswith("v"), f"kcm_ublue must not be a release tag: {pin}"


def test_oversteer_udev_pin_is_immutable_commit():
    text = VERSIONS_YAML.read_text(encoding="utf-8")
    match = re.search(r'^\s*oversteer_udev:\s*"([^\"]+)"', text, re.MULTILINE)
    assert match, "image-versions.yaml must pin oversteer_udev"
    pin = match.group(1)
    assert re.fullmatch(r"[0-9a-f]{40}", pin), (
        f"oversteer_udev must be a 40-character commit SHA, got: {pin}"
    )
    assert pin != "master", "oversteer_udev must not use mutable master branch"


def test_krunner_bazaar_ref_is_immutable_commit():
    text = KCM_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r'^\s*KRUNNER_BAZAAR_REF="([^\"]+)"', text, re.MULTILINE)
    assert match, "kcm-ublue.sh must pin KRUNNER_BAZAAR_REF"
    pin = match.group(1)
    assert re.fullmatch(r"[0-9a-f]{40}", pin), (
        f"KRUNNER_BAZAAR_REF must be a 40-character commit SHA, got: {pin}"
    )


def test_kcm_ublue_download_uses_commit_archive_not_branch_tag():
    script = KCM_SCRIPT.read_text(encoding="utf-8")
    assert "--branch" not in script, (
        "kcm-ublue.sh must not clone kcm_ublue with --branch"
    )
    assert 'archive/${KCM_UBLUE_REF}.tar.gz' in script, (
        "kcm-ublue.sh must download kcm_ublue via commit archive URL"
    )
    validation_idx = script.index('KCM_UBLUE_REF" =~ ^[0-9a-f]{40}$')
    download_idx = script.index('archive/${KCM_UBLUE_REF}.tar.gz')
    assert validation_idx < download_idx, (
        "KCM_UBLUE_REF validation must precede archive download"
    )


def test_oversteer_download_uses_commit_not_master_branch():
    script = KCM_SCRIPT.read_text(encoding="utf-8")
    assert "oversteer/master" not in script, (
        "kcm-ublue.sh must not fetch oversteer rules from mutable master branch"
    )
    assert "oversteer/${OVERSTEER_REF}" in script, (
        "kcm-ublue.sh must fetch oversteer rules using ${OVERSTEER_REF}"
    )
    validation_idx = script.index('OVERSTEER_REF" =~ ^[0-9a-f]{40}$')
    download_idx = script.index('oversteer/${OVERSTEER_REF}')
    assert validation_idx < download_idx, (
        "OVERSTEER_REF validation must precede rule download"
    )


def test_renovate_extracts_kde_source_pins_from_image_versions():
    result = subprocess.run([
        "node", "-e", """
const fs = require('fs');
const config = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const manager = config.customManagers.find(m => m.description === 'Update pinned GitHub source commits in image-versions.yaml');
if (!manager) {
    console.error('Manager not found');
    process.exit(1);
}
const source = fs.readFileSync(process.argv[2], 'utf8');
const matches = [...source.matchAll(new RegExp(manager.matchStrings[0], 'g'))];
console.log(JSON.stringify(matches.map(m => ({...m.groups, packageName: manager.packageNameTemplate.replace('{{{depName}}}', m.groups.depName)}))));
""", str(RENOVATE_JSON), str(VERSIONS_YAML)], capture_output=True, text=True, check=True)
    dependencies = json.loads(result.stdout)
    deps_by_name = {d["depName"]: d for d in dependencies}

    assert "ledif/kcm_ublue" in deps_by_name
    kcm = deps_by_name["ledif/kcm_ublue"]
    assert kcm["datasource"] == "git-refs"
    assert re.fullmatch(r"[0-9a-f]{40}", kcm["currentDigest"])
    assert kcm["packageName"] == "https://github.com/ledif/kcm_ublue"

    assert "berarma/oversteer" in deps_by_name
    oversteer = deps_by_name["berarma/oversteer"]
    assert oversteer["datasource"] == "git-refs"
    assert re.fullmatch(r"[0-9a-f]{40}", oversteer["currentDigest"])
    assert oversteer["packageName"] == "https://github.com/berarma/oversteer"


def test_falsification_rejects_mutable_references():
    mutable_tag_yaml = 'downloads:\n  kcm_ublue: "v0.6.1"\n'
    assert not re.search(r'^\s*kcm_ublue:\s*"[0-9a-f]{40}"', mutable_tag_yaml, re.MULTILINE)

    mutable_master_script = 'curl -fsSLo file "https://raw.githubusercontent.com/berarma/oversteer/master/data/udev/rule"'
    assert "oversteer/master" in mutable_master_script
