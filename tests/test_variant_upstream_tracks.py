"""Keep the rolling/experimental availability contract machine-readable.

The distinction is operational, not cosmetic: a red release-track build is a
regression, while a moving upstream can temporarily be incompatible without
violating an uninterrupted-green promise.  Issue #1754 originally carried the
only complete list, which let the policy and matrix drift independently.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
POLICY = ROOT / "VARIANT-LIFECYCLE.md"

NON_RELEASE_TRACKS = {
    "bonito-rawhide": "rolling",
    "flounder-sid": "rolling",
    "guppy": "rolling",
    "hummingbird": "experimental",
    "marlin": "rolling",
    "sailfin": "rolling",
    "wahoo": "experimental",
}


def test_non_release_upstream_tracks_are_explicit_and_complete():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    actual = {
        variant["id"]: variant["upstream_track"]
        for variant in config["variants"]
        if "upstream_track" in variant
    }

    assert actual == NON_RELEASE_TRACKS
    assert set(actual.values()) <= {"rolling", "experimental"}


def test_every_non_release_track_has_a_documented_availability_contract():
    policy = POLICY.read_text(encoding="utf-8")

    for variant in NON_RELEASE_TRACKS:
        assert f"`{variant}`" in policy
    assert "no next-night promotion or uninterrupted-green promise" in policy
    assert "No uptime, flavor-completeness, or continued-publication promise" in policy
    assert "Promotion is fail-closed on every track" in policy
