"""tunaOS#2485: rolling EL10 images shipped with no working system bus.

skipjack:gnome failed on libselinux 3.11-1.el10 in run 35185567440 and
passed its Gate and desktop contract when only libselinux changed to 3.10 in
run 35191766126. The same 3.11 failure was measured on yellowfin.

Falsification: structural — reverting the declared 3.10 ceiling or either
rolling-variant scope makes this test fail as the pre-fix tree did.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "image-versions.yaml"
BASE_PACKAGES = ROOT / "build_scripts" / "10-base-packages.sh"


def test_both_rolling_el10_bases_apply_the_declared_ceiling_strictly():
    versions = yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))
    pin = versions["packages"]["el10_rolling_libselinux"]
    script = BASE_PACKAGES.read_text(encoding="utf-8")

    assert pin == "3.10-2.el10"
    assert '"$IMAGE_NAME" == "yellowfin"' in script
    assert '"$IMAGE_NAME" == "skipjack"' in script

    block = script.split("# tunaOS#2485:", 1)[1].split(
        "if [[ $IS_HUMMINGBIRD == true ]]", 1
    )[0]
    assert "dnf -y downgrade" in block
    assert "dnf versionlock add" in block
    assert "libselinux libselinux-utils python3-libselinux" in block
    assert "rpm -q --queryformat" in block
    assert "|| true" not in block
