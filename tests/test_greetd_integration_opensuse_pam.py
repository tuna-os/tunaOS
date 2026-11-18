"""openSUSE's greetd gets the PAM service it lacks, built on SUSE's common-* stacks.

openSUSE's greetd package ships /usr/lib/pam.d/greetd but no `greetd-greeter`
(greetd-0.10.3-2.6 file list), so every greeter start fell to PAM `other` (deny) on
sailfin:cosmic (tunaOS#4538). The EL10 branch of greetd-system-integration.sh keys on
`greetd` alone and would `substack` Fedora's `system-auth`, which SUSE does not have.

Falsification: delete the openSUSE block and test_tumbleweed_adds_only_the_missing_greeter_service
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


def test_tumbleweed_adds_only_the_missing_greeter_service(tmp_path):
    """The real Tumbleweed layout: vendor greetd PAM present, greetd-greeter absent."""
    _run(tmp_path, TUMBLEWEED, existing=("greetd",))
    greeter = (tmp_path / "etc/pam.d/greetd-greeter").read_text()
    assert "pam_permit.so" in greeter and "pam_systemd.so" in greeter
    assert not (tmp_path / "etc/pam.d/greetd").exists()


def test_a_greetd_without_any_pam_gets_both_over_common_stacks(tmp_path):
    _run(tmp_path, TUMBLEWEED)
    greetd = (tmp_path / "etc/pam.d/greetd").read_text()
    assert "common-auth" in greetd and "common-session" in greetd
    assert "system-auth" not in greetd
    assert (tmp_path / "etc/pam.d/greetd-greeter").exists()


def test_other_distros_are_left_to_the_el_block(tmp_path):
    _run(tmp_path, FEDORA)
    assert not (tmp_path / "etc/pam.d/greetd").exists()
    assert not (tmp_path / "etc/pam.d/greetd-greeter").exists()


def test_distro_pam_is_never_overwritten(tmp_path):
    _run(tmp_path, TUMBLEWEED, existing=("greetd", "greetd-greeter"))
    assert not (tmp_path / "etc/pam.d/greetd").exists()
    assert not (tmp_path / "etc/pam.d/greetd-greeter").exists()


def test_opensuse_block_precedes_the_el_block():
    text = SCRIPT.read_text()
    suse = text.index("suse")
    el = text.index("installing the image-owned account")
    assert suse < el, "the EL block must run after the openSUSE block so it sees the PAM service"
