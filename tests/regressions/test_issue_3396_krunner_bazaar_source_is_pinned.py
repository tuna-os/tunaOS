"""tunaOS#3396: KDE image builds consumed a mutable krunner-bazaar tag.

The KDE image build compiled the Bazaar KRunner plugin as root from a
mutable version tag. A moved tag could therefore put attacker-controlled source into
every affected image. The source is now fetched from a Renovate-maintained
40-character commit pin in the build script.

Falsification: structural -- restoring `archive/refs/tags/` or removing the
40-character source ref makes this test fail.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_scripts" / "desktop" / "kcm-ublue.sh"


def test_krunner_bazaar_download_uses_content_addressed_ref():
    script = SCRIPT.read_text(encoding="utf-8")

    ref = re.search(
        r'^\s*KRUNNER_BAZAAR_REF="([0-9a-f]{40})"\s*$',
        script,
        re.MULTILINE,
    )
    assert ref, "kcm-ublue.sh must carry a 40-character Bazaar commit pin"

    assert "archive/refs/tags/" not in script
    assert "archive/${KRUNNER_BAZAAR_REF}.tar.gz" in script



def test_krunner_bazaar_ref_is_validated_before_download():
    script = SCRIPT.read_text(encoding="utf-8")
    validation = script.index('KRUNNER_BAZAAR_REF" =~ ^[0-9a-f]{40}$')
    download = script.index('archive/${KRUNNER_BAZAAR_REF}.tar.gz')

    assert validation < download


def test_renovate_extracts_named_ref_and_content_digest():
    import json
    import subprocess

    config = ROOT / "renovate.json"
    # Run the actual configured JavaScript expression, including named groups.
    result = subprocess.run([
        "node", "-e", """
const fs = require('fs');
const config = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const manager = config.customManagers.find(m => m.description === 'Update pinned GitHub source commits in build scripts');
const source = fs.readFileSync(process.argv[2], 'utf8');
const matches = [...source.matchAll(new RegExp(manager.matchStrings[0], 'g'))];
console.log(JSON.stringify(matches.map(m => ({...m.groups, packageName: manager.packageNameTemplate.replace('{{{depName}}}', m.groups.depName)}))));
""", str(config), str(SCRIPT)], capture_output=True, text=True, check=True)
    dependencies = json.loads(result.stdout)
    assert dependencies == [{
        "datasource": "git-refs", "depName": "bazaar-org/krunner-bazaar",
        "currentValue": re.search(r"ref=(v[0-9.]+)", SCRIPT.read_text()).group(1), "currentDigest": re.search(r'KRUNNER_BAZAAR_REF="([0-9a-f]{40})"', SCRIPT.read_text()).group(1),
        "packageName": "https://github.com/bazaar-org/krunner-bazaar",
    }]
