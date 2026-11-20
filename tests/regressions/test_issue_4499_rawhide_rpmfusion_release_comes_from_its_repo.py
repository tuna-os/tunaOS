"""tunaOS#4499: Rawhide installs RPM Fusion's release packages from RPM Fusion's rawhide repo.

Every Build Bonito-rawhide run from 2026-11-04 failed `base` with
`TUNAOS_WISHLIST_FAIL misses=5` (run 42873889865): gstreamer1-plugins-good,
-ugly, -libav, -bad-free and lame were never installed. 10-base-packages.sh
installed `rpmfusion-*-release-rawhide.noarch.rpm` by URL, and RPM Fusion stopped
publishing that file (`Status code: 403` from download1, 404 from the mirrors).
Without RPM Fusion, `gstreamer1-plugins-ugly` is `No match for argument`, and
both multimedia transactions abort. The rawhide release package
(`rpmfusion-free-release-46-0.4`) is in
`free/fedora/development/rawhide/Everything/$basearch/os/`.

The test runs the real RPM Fusion step of 10-base-packages.sh with a stub dnf
and records what it asks dnf to install.

Falsification: behavioural. With the by-URL `-release-${FEDORA_VER}` install
restored for Rawhide, dnf is asked for
`rpmfusion-free-release-rawhide.noarch.rpm` and the Rawhide case fails.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_scripts/10-base-packages.sh"


def rpmfusion_step() -> str:
    text = SCRIPT.read_text()
    start = text.index('FEDORA_VER="$(detect_fedora_ver)"')
    end = text.index("# RPM Fusion multimedia set", start)
    return text[start:end]


def dnf_calls(tmp_path: Path, fedora_ver: str) -> list[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "dnf-calls"
    dnf = bin_dir / "dnf"
    dnf.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {calls}\n")
    dnf.chmod(0o755)
    script = textwrap.dedent(f"""\
        detect_fedora_ver() {{ echo {fedora_ver}; }}
        """) + rpmfusion_step()
    subprocess.run(["bash", "-euo", "pipefail", "-c", script], check=True,
                   env=os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"})
    return calls.read_text().splitlines()


def test_rawhide_installs_the_release_packages_from_the_rawhide_repo(tmp_path):
    calls = dnf_calls(tmp_path, "rawhide")
    assert not any("release-rawhide.noarch.rpm" in c for c in calls), calls
    install = next(c for c in calls if "rpmfusion-free-release " in c + " ")
    for tree in ("free", "nonfree"):
        assert (f"https://download1.rpmfusion.org/{tree}/fedora/development/rawhide/"
                "Everything/$basearch/os/") in install
    assert install.split()[-2:] == ["rpmfusion-free-release", "rpmfusion-nonfree-release"]


@pytest.mark.parametrize("version", ["44", "45"])
def test_a_numbered_release_keeps_the_published_release_rpms(tmp_path, version):
    calls = dnf_calls(tmp_path, version)
    assert any(f"rpmfusion-free-release-{version}.noarch.rpm" in c
               and f"rpmfusion-nonfree-release-{version}.noarch.rpm" in c for c in calls), calls
    assert not any("--repofrompath" in c for c in calls), calls
