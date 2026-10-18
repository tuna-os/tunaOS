"""tunaOS#3396: KDE image builds consumed a mutable krunner-bazaar tag.

The KDE image build compiled the Bazaar KRunner plugin as root from the
`v1.3.0` tag. A moved tag could therefore put attacker-controlled source into
every affected image. The source is now fetched from a Renovate-maintained
40-character commit pin.

Falsification: structural -- restoring `archive/refs/tags/` or removing the
40-character manifest ref makes this test fail.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_scripts" / "desktop" / "kcm-ublue.sh"
VERSIONS = ROOT / "image-versions.yaml"


def test_krunner_bazaar_download_uses_content_addressed_ref():
    script = SCRIPT.read_text(encoding="utf-8")
    versions = VERSIONS.read_text(encoding="utf-8")

    ref = re.search(r'^\s*krunner_bazaar_src:\s*"([0-9a-f]{40})"\s*$', versions, re.MULTILINE)
    assert ref, "image-versions.yaml must carry a 40-character Bazaar commit pin"

    assert "archive/refs/tags/" not in script
    assert f"archive/${{KRUNNER_BAZAAR_REF}}.tar.gz" in script
    assert "KRUNNER_BAZAAR_REF=" in script


def test_krunner_bazaar_ref_is_validated_before_download():
    script = SCRIPT.read_text(encoding="utf-8")
    validation = script.index('KRUNNER_BAZAAR_REF" =~ ^[0-9a-f]{40}$')
    download = script.index('archive/${KRUNNER_BAZAAR_REF}.tar.gz')

    assert validation < download
