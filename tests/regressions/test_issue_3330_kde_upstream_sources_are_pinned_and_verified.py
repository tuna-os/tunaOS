"""tunaOS#3330: KDE image builds consumed mutable unverified upstream sources.

build_scripts/desktop/kcm-ublue.sh consumed external sources without immutable
integrity verification during rootful KDE image builds:
- ledif/kcm_ublue was cloned by mutable release tag v0.6.1 and built as root.
- bazaar-org/krunner-bazaar was fetched from a mutable tag archive URL.
- berarma/oversteer udev rules were fetched directly from the mutable master branch
  and installed into /usr/lib/udev/rules.d.

Every consumed source is now content-addressed by a Renovate-managed 40-character
commit SHA pin, verified before execution or installation, and fails closed on mismatch.
The oversteer udev rules are downloaded to a temporary directory and verified with
SHA-256 before installation.

Falsification: structural -- reverting kcm_ublue to git clone by tag, restoring
the master branch URL for oversteer, or removing the commit validation or sha256
verification blocks causes these tests to fail.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_scripts" / "desktop" / "kcm-ublue.sh"
VERSIONS = ROOT / "image-versions.yaml"
RENOVATE = ROOT / "renovate.json"

EXPECTED_OVERSTEER_RULES = {
    "99-logitech-wheel-perms.rules": "622c5e38b3b80259dac4d2cf63c0731057f7be635234556099e44d5c1ed24a25",
    "99-fanatec-wheel-perms.rules": "a4b46b034ef9cce7033337b5d444d60c70df3345a0ae7d89aab00987aff980ef",
    "99-thrustmaster-wheel-perms.rules": "c6e3df320d4ce3b5a7e3c852942f15a77f08f435b79483505b80266d7f39ffbc",
}


def test_kcm_ublue_source_is_pinned_and_content_addressed():
    script = SCRIPT.read_text(encoding="utf-8")

    ref = re.search(
        r'^\s*KCM_UBLUE_REF="([0-9a-f]{40})"\s*$',
        script,
        re.MULTILINE,
    )
    assert ref, "kcm-ublue.sh must carry a 40-character kcm_ublue commit pin"

    # Must not clone by mutable branch or tag
    assert "git clone --depth 1 --branch" not in script
    assert "archive/${KCM_UBLUE_REF}.tar.gz" in script

    validation = script.index('KCM_UBLUE_REF" =~ ^[0-9a-f]{40}$')
    download = script.index('archive/${KCM_UBLUE_REF}.tar.gz')
    build = script.index("cmake --build build")
    assert validation < download < build, "validation must occur before download and cmake build"


def test_krunner_bazaar_source_is_pinned_and_content_addressed():
    script = SCRIPT.read_text(encoding="utf-8")

    ref = re.search(
        r'^\s*KRUNNER_BAZAAR_REF="([0-9a-f]{40})"\s*$',
        script,
        re.MULTILINE,
    )
    assert ref, "kcm-ublue.sh must carry a 40-character Bazaar commit pin"
    assert "archive/refs/tags/" not in script
    assert "archive/${KRUNNER_BAZAAR_REF}.tar.gz" in script

    validation = script.index('KRUNNER_BAZAAR_REF" =~ ^[0-9a-f]{40}$')
    download = script.index('archive/${KRUNNER_BAZAAR_REF}.tar.gz')
    assert validation < download


def test_oversteer_rules_are_pinned_and_checksum_verified():
    script = SCRIPT.read_text(encoding="utf-8")

    ref = re.search(
        r'^\s*OVERSTEER_REF="([0-9a-f]{40})"\s*$',
        script,
        re.MULTILINE,
    )
    assert ref, "kcm-ublue.sh must carry a 40-character oversteer commit pin"

    # Reject unverified master branch fetches
    assert "oversteer/master/" not in script
    assert "berarma/oversteer/${OVERSTEER_REF}/data/udev" in script

    validation = script.index('OVERSTEER_REF" =~ ^[0-9a-f]{40}$')
    download = script.index('berarma/oversteer/${OVERSTEER_REF}/data/udev')
    verify = script.index("sha256sum --check")
    install = script.index('install -Dm0644 "${OVERSTEER_TMP}/${rule}"')

    assert validation < download < verify < install, "rules must be validated and checked before installation"

    for rule, sha in EXPECTED_OVERSTEER_RULES.items():
        assert rule in script
        assert sha in script


def test_image_versions_pins_sources():
    versions = VERSIONS.read_text(encoding="utf-8")
    assert re.search(r'^\s*kcm_ublue:\s*"[0-9a-f]{40}"\s*$', versions, re.MULTILINE)
    assert re.search(r'^\s*oversteer:\s*"[0-9a-f]{40}"\s*$', versions, re.MULTILINE)


def test_renovate_extracts_kcm_ublue_and_oversteer():
    config = RENOVATE
    result = subprocess.run([
        "node", "-e", """
const fs = require('fs');
const config = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const manager = config.customManagers.find(m => m.description === 'Update pinned kcm_ublue and oversteer source commits in build scripts');
const source = fs.readFileSync(process.argv[2], 'utf8');
const matches = [...source.matchAll(new RegExp(manager.matchStrings[0], 'g'))];
console.log(JSON.stringify(matches.map(m => ({...m.groups, packageName: manager.packageNameTemplate.replace('{{{depName}}}', m.groups.depName)}))));
""", str(config), str(SCRIPT)], capture_output=True, text=True, check=True)
    dependencies = json.loads(result.stdout)
    assert dependencies == [
        {
            "datasource": "git-refs",
            "depName": "ledif/kcm_ublue",
            "currentValue": "v0.6.1",
            "currentDigest": "75cc31f81f5284bef7a31ff9b8219aae612dff0d",
            "packageName": "https://github.com/ledif/kcm_ublue",
        },
        {
            "datasource": "git-refs",
            "depName": "berarma/oversteer",
            "currentValue": "master",
            "currentDigest": "74c748436a1dff2e42a340b581db0d0e4e0cafb2",
            "packageName": "https://github.com/berarma/oversteer",
        },
    ]
