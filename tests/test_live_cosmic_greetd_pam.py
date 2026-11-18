"""The COSMIC live adapter gives greetd PAM services where the distro ships none.

sailfin-cosmic (openSUSE Tumbleweed), iso-builder run 43541246573: the serial dump
shows greetd.service in start-limit-hit after "greeter exited without creating a
session", and `ls /etc/pam.d/greetd*` finds nothing. PAM then falls back to `other`
(deny) and the live session never starts (tunaOS#4538).

Falsification: delete the PAM loop from desktop-cosmic.sh and the first test fails; make
the loop overwrite an existing distro service and the second test fails.
"""

import re
import subprocess
from pathlib import Path

ADAPTER = Path(__file__).parents[1] / "live-iso/common/src/desktop-cosmic.sh"


def _pam_loop() -> str:
    text = ADAPTER.read_text()
    match = re.search(r"^for _svc in greetd greetd-greeter; do\n.*?^done\n", text, re.S | re.M)
    assert match, "desktop-cosmic.sh no longer writes the greetd PAM services"
    return match.group(0)


def _run(root: Path, existing: tuple[str, ...]) -> None:
    script = _pam_loop().replace("/etc/pam.d", f"{root}/etc/pam.d").replace("/usr/lib/pam.d", f"{root}/usr/lib/pam.d")
    for name in existing:
        path = root / "usr/lib/pam.d" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# distro\n")
    subprocess.run(["bash", "-c", script], check=True)


def test_missing_services_are_written(tmp_path):
    _run(tmp_path, ())
    for name in ("greetd", "greetd-greeter"):
        body = (tmp_path / "etc/pam.d" / name).read_text()
        assert "pam_permit.so" in body and "pam_systemd.so" in body


def test_distro_services_are_left_alone(tmp_path):
    _run(tmp_path, ("greetd", "greetd-greeter"))
    assert not (tmp_path / "etc/pam.d/greetd").exists()
    assert not (tmp_path / "etc/pam.d/greetd-greeter").exists()
