"""openSUSE's greetd gets PAM services built on SUSE's common-* stacks, not system-auth.

sailfin:cosmic (openSUSE Tumbleweed): the live session never started because the
distro greetd ships no `/etc/pam.d/greetd*` (tunaOS#4538). The installed image had the
same gap, and greetd-system-integration.sh would have filled it with the EL10 service,
which `substack`s Fedora's `system-auth`. SUSE has none, so PAM would still deny.

Falsification: delete the openSUSE block and test_opensuse_gets_common_stack_pam
fails; move it after the EL block (or drop its "written first" ordering) and
test_opensuse_block_precedes_the_el_block fails; let it write on Fedora and
test_other_distros_are_left_to_the_el_block fails.
"""

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "build_scripts/desktop/greetd-system-integration.sh"


def _suse_block() -> str:
    text = SCRIPT.read_text()
    match = re.search(r"^if command -v greetd .*?^fi\n", text, re.S | re.M)
    assert match, "greetd-system-integration.sh lost its openSUSE PAM block"
    return match.group(0)


def _run(root: Path, os_release: str, existing: tuple[str, ...] = ()) -> None:
    (root / "os-release").write_text(os_release)
    for name in existing:
        path = root / "usr/lib/pam.d" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# distro\n")
    script = (
        _suse_block()
        .replace("command -v greetd &>/dev/null", "true")
        .replace("/etc/os-release", f"{root}/os-release")
        .replace("/etc/pam.d", f"{root}/etc/pam.d")
        .replace("/usr/lib/pam.d", f"{root}/usr/lib/pam.d")
    )
    subprocess.run(["bash", "-c", script], check=True, capture_output=True)


TUMBLEWEED = 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'
FEDORA = "ID=fedora\n"


def test_opensuse_gets_common_stack_pam(tmp_path):
    _run(tmp_path, TUMBLEWEED)
    greetd = (tmp_path / "etc/pam.d/greetd").read_text()
    assert "common-auth" in greetd and "common-session" in greetd
    assert "system-auth" not in greetd
    greeter = (tmp_path / "etc/pam.d/greetd-greeter").read_text()
    assert "pam_permit.so" in greeter and "pam_systemd.so" in greeter


def test_other_distros_are_left_to_the_el_block(tmp_path):
    _run(tmp_path, FEDORA)
    assert not (tmp_path / "etc/pam.d/greetd").exists()


def test_distro_pam_is_never_overwritten(tmp_path):
    _run(tmp_path, TUMBLEWEED, existing=("greetd",))
    assert not (tmp_path / "etc/pam.d/greetd").exists()


def test_opensuse_block_precedes_the_el_block():
    text = SCRIPT.read_text()
    suse = text.index("suse")
    el = text.index("installing the image-owned account")
    assert suse < el, "the EL block must run after the openSUSE block so it sees the PAM service"
