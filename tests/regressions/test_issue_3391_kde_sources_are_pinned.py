"""tunaOS#3391: KDE image builds execute mutable third-party source content as root.

The KDE image build fetched third-party source code and udev rules from mutable
release tags and the master branch tip as root during image builds. An upstream
tag move or branch rewrite could change code executed and installed with root
privileges. The build now pins kcm_ublue and oversteer_udev to immutable
40-character commit SHAs in image-versions.yaml with Renovate metadata, and
fetches content-addressed sources instead of mutable refs.

Falsification: structural -- restoring mutable tag v0.6.1 in image-versions.yaml,
git clone --branch in kcm-ublue.sh, or the master branch URL for oversteer udev
rules makes this test fail.
"""

from __future__ import annotations

import re
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_scripts" / "desktop" / "kcm-ublue.sh"
VERSIONS = ROOT / "image-versions.yaml"


def test_kcm_ublue_is_pinned_to_commit_sha_in_image_versions():
    data = yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))
    ref = data["downloads"]["kcm_ublue"]
    assert re.match(r"^[0-9a-f]{40}$", ref), (
        f"kcm_ublue must be a 40-character commit SHA, got {ref!r}"
    )


def test_oversteer_udev_is_pinned_to_commit_sha_in_image_versions():
    data = yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))
    ref = data["downloads"]["oversteer_udev"]
    assert re.match(r"^[0-9a-f]{40}$", ref), (
        f"oversteer_udev must be a 40-character commit SHA, got {ref!r}"
    )


def test_renovate_tracks_kcm_ublue_and_oversteer_git_refs():
    text = VERSIONS.read_text(encoding="utf-8")
    assert re.search(
        r"#\s*renovate:\s*datasource=git-refs\s+depName=ledif/kcm_ublue\s*\n\s*kcm_ublue:\s*\"[0-9a-f]{40}\"",
        text,
    ), "image-versions.yaml must have Renovate git-refs metadata for ledif/kcm_ublue"
    assert re.search(
        r"#\s*renovate:\s*datasource=git-refs\s+depName=berarma/oversteer\s*\n\s*oversteer_udev:\s*\"[0-9a-f]{40}\"",
        text,
    ), "image-versions.yaml must have Renovate git-refs metadata for berarma/oversteer"


def test_kcm_ublue_does_not_use_git_clone_branch_with_mutable_tag():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "git clone --depth 1 --branch" not in script
    assert "https://github.com/ledif/kcm_ublue/archive/${KCM_UBLUE_REF}.tar.gz" in script


def test_oversteer_udev_does_not_fetch_from_master_branch():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "berarma/oversteer/master" not in script
    assert "berarma/oversteer/${OVERSTEER_REF}/data/udev" in script


def test_kde_sources_validate_sha_before_download():
    script = SCRIPT.read_text(encoding="utf-8")
    # kcm_ublue SHA validation precedes download
    kcm_val = script.index('KCM_UBLUE_REF" =~ ^[0-9a-f]{40}$')
    kcm_dl = script.index('https://github.com/ledif/kcm_ublue/archive/${KCM_UBLUE_REF}.tar.gz')
    assert kcm_val < kcm_dl

    # krunner_bazaar SHA validation precedes download
    kb_val = script.index('KRUNNER_BAZAAR_REF" =~ ^[0-9a-f]{40}$')
    kb_dl = script.index('https://github.com/bazaar-org/krunner-bazaar/archive/${KRUNNER_BAZAAR_REF}.tar.gz')
    assert kb_val < kb_dl

    # oversteer SHA validation precedes download
    ov_val = script.index('OVERSTEER_REF" =~ ^[0-9a-f]{40}$')
    ov_dl = script.index('berarma/oversteer/${OVERSTEER_REF}/data/udev')
    assert ov_val < ov_dl
