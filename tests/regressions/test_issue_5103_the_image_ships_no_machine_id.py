"""tunaOS#5103: an image ships `uninitialized`, never a committed machine-id.

On main, gurnard:pantheon (image 0a0084e4) carried
`be863cc89364403bae054fb1b547aacf` in /etc/machine-id, committed by an apt
postinst while the image built. fishermand refused the install on both lanes of
run 45993359445: "postfix: medium carries a machine-id (be863cc8...); it is not
pristine".

Falsification: without the call in finalize.sh the last test fails; a check that
leaves the committed id in place fails the first test.
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "build_scripts/checks/pristine-machine-id.sh"
FINALIZE = ROOT / "build_scripts/bootc/finalize.sh"


def run(path):
    return subprocess.run(
        ["bash", str(CHECK)], env={**os.environ, "MACHINE_ID_FILE": str(path)}, capture_output=True, text=True
    )


@pytest.mark.parametrize("before", ["be863cc89364403bae054fb1b547aacf\n", "", "uninitialized\n"])
def test_a_committed_machine_id_is_reset(tmp_path, before):
    f = tmp_path / "machine-id"
    f.write_text(before)
    assert run(f).returncode == 0
    assert f.read_text() == "uninitialized\n"


def test_a_file_that_cannot_be_written_stops_the_build(tmp_path):
    f = tmp_path / "missing-dir" / "machine-id"
    assert run(f).returncode != 0


def test_finalize_resets_it_after_the_image_is_bootcified():
    text = FINALIZE.read_text()
    assert text.index("bootc/mount-system.sh") < text.index("checks/pristine-machine-id.sh")
    assert text.index("checks/pristine-machine-id.sh") < text.index("bootc container lint")


def test_every_apt_build_path_resets_it():
    """flounder:base (Debian trixie) carried 157f394e... too: Debian has no
    finalize.sh, so 99-cleanup.sh (end of base-no-de) resets it. install-desktop.sh is a hashed
    input of the package observation (scripts/lib/package_catalogs.py) and is not touched."""
    for rel in ("build_scripts/99-cleanup.sh",):
        text = (ROOT / rel).read_text()
        assert "checks/pristine-machine-id.sh" in text, rel
        assert "apt" in text[text.index("checks/pristine-machine-id.sh") - 200 : text.index("checks/pristine-machine-id.sh")]
