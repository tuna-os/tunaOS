"""Stingray is the one rolling non-LTS Ubuntu variant (tunaOS#3337).

LTS Ubuntu releases get their own fish (gurnard, grouper). Interim releases do
not: stingray follows the `ubuntu:rolling` tag, so the next interim release is
a Renovate digest bump on the same variant, never a new per-release id.
"""

import re
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"


def _variants():
    return {v["id"]: v for v in yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["variants"]}


def test_exactly_one_variant_tracks_the_ubuntu_rolling_tag():
    rolling = [vid for vid, v in _variants().items()
               if v["base_image"].startswith("docker.io/library/ubuntu:rolling@sha256:")]
    assert rolling == ["stingray"]


def test_the_interim_variant_carries_no_release_name():
    stingray = _variants()["stingray"]
    for alias in stingray.get("aliases", []):
        assert not re.search(r"\d", alias), alias
    assert not re.search(r"\d|stonking", stingray["description"].lower()), stingray["description"]
    assert stingray.get("tag_suffix", "") == ""


def test_the_interim_variant_stays_dispatch_only_until_capacity_sign_off():
    stingray = _variants()["stingray"]
    assert stingray["experimental"] is True
    assert "schedule" not in stingray
    assert not (ROOT / ".github/workflows/build-stingray.yml").read_text(encoding="utf-8").count("schedule:")
    assert {f["id"] for f in stingray["flavors"] if f.get("build_image")} == {"base", "gnome", "kde", "xfce"}
    assert not any(f.get("build_iso") for f in stingray["flavors"])


def test_every_stingray_flavor_builds_from_the_ubuntu_containerfile():
    for flavor in ("base", "gnome", "kde", "xfce"):
        out = subprocess.run([str(ROOT / "scripts/resolve-flavor.sh"), "stingray", flavor],
                             check=True, capture_output=True, text=True, cwd=ROOT).stdout
        assert 'CONTAINERFILE="Containerfile.ubuntu"' in out, (flavor, out)
