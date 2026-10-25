"""tunaOS#3810: Fedora ELN replaced gnome-keyring with oo7.

wahoo:tuna failed Build Image in run 39989009540 (job 120596055953) with
`No match for argument: gnome-keyring`. Measured against
dl.fedoraproject.org/pub/eln/1 on 2026-10-24: no ELN repository publishes
gnome-keyring or gnome-keyring-pam; oo7-daemon obsoletes gnome-keyring < 51,
pam_oo7 obsoletes gnome-keyring-pam < 51, and ELN's gdm requires pam_oo7.

Falsification: the ELN sections must name the oo7 provider and its PAM
module, every other target keeps gnome-keyring, and the desktop contract
rejects an ELN image without oo7 and a non-ELN image without gnome-keyring.
"""
from functools import cache
from pathlib import Path
import importlib.util
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Load the config module by path: it has no sibling imports, and putting
# scripts/ on sys.path would leak into every test that runs after this one.
_spec = importlib.util.spec_from_file_location(
    "tunaos_config_3810", ROOT / "scripts/lib/tunaos_config.py"
)
tunaos_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tunaos_config)

CHECK = ROOT / "build_scripts/checks/verify-desktop-experience.sh"
OO7 = {"oo7-daemon", "pam_oo7"}
KEYRING = {"gnome-keyring", "gnome-keyring-pam"}


@cache
def desktops():
    return tunaos_config.load()["desktops"]


def packages(desktop, target):
    section = desktops()[desktop]["packages"][target]
    return {name for key in ("required", "optional") for name in section.get(key, [])}


@pytest.mark.parametrize("desktop", ["gnome", "tuna"])
def test_eln_names_the_oo7_secret_service_and_its_pam_module(desktop):
    names = packages(desktop, "eln")
    assert OO7 <= names, desktop
    assert not KEYRING & names, f"ELN publishes no {sorted(KEYRING & names)}"


@pytest.mark.parametrize(
    "desktop,target",
    [("gnome", "zypper"), ("tuna", "el10"), ("tuna", "fedora"), ("tuna", "rawhide")],
)
def test_other_targets_keep_gnome_keyring(desktop, target):
    names = packages(desktop, target)
    assert "gnome-keyring" in names
    assert not OO7 & names


def test_oo7_is_confined_to_eln():
    for desktop, value in desktops().items():
        for target in value.get("packages", {}):
            if target != "eln":
                assert not OO7 & packages(desktop, target), (desktop, target)


def contract_functions():
    """The helper region the contract delimits with begin/end markers.

    It holds only function definitions and the waiver counter, so sourcing it
    runs nothing; no shell parsing is needed to find a function boundary.
    """
    lines = CHECK.read_text().splitlines()
    begin = lines.index("# contract-helpers: begin")
    end = lines.index("# contract-helpers: end")
    assert begin < end, "the contract-helpers markers are out of order"
    return "\n".join(lines[begin + 1 : end])


def image(
    tmp_path, os_id, files, *, quoted_id=False, variant_id=None, executable=True,
    directories=(), env=None
):
    (tmp_path / "usr/lib").mkdir(parents=True)
    value = f'"{os_id}"' if quoted_id else os_id
    os_release = f"NAME=test\nID={value}\n"
    if variant_id is not None:
        os_release += f"VARIANT_ID={variant_id}\n"
    (tmp_path / "usr/lib/os-release").write_text(os_release)
    for relative in files:
        path = tmp_path / relative
        if relative in directories:
            path.mkdir(parents=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        if executable and path.name in {"oo7-daemon", "gnome-keyring-daemon"}:
            path.chmod(0o755)
    script = contract_functions() + (
        f'\nrequire_secret_service "{tmp_path}"\necho "satisfied waived=$TUNAOS_CONTRACT_WAIVED"\n'
    )
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", **(env or {})}
    )


OO7_FILES = ["usr/libexec/oo7-daemon", "usr/lib64/security/pam_oo7.so"]
KEYRING_FILES = ["usr/bin/gnome-keyring-daemon"]


@pytest.mark.parametrize(
    "os_id,files,quoted_id,variant_id",
    [
        ("eln", OO7_FILES, False, None),
        ("eln", ["usr/libexec/oo7-daemon", "usr/lib/security/pam_oo7.so"], True, None),
        ("fedora", OO7_FILES, False, "eln"),
        ("fedora", KEYRING_FILES, False, None),
        ("almalinux", KEYRING_FILES, False, None),
    ],
)
def test_the_contract_accepts_each_base_native_provider(
    tmp_path, os_id, files, quoted_id, variant_id
):
    result = image(
        tmp_path, os_id, files, quoted_id=quoted_id, variant_id=variant_id
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "satisfied waived=0\n"


@pytest.mark.parametrize(
    "os_id,files",
    [
        ("eln", []),
        ("eln", KEYRING_FILES),
        ("eln", ["usr/libexec/oo7-daemon"]),
        ("eln", ["usr/lib64/security/pam_oo7.so"]),
        ("fedora", []),
        ("fedora", OO7_FILES),
    ],
)
def test_the_contract_rejects_a_missing_native_provider(tmp_path, os_id, files):
    result = image(tmp_path, os_id, files)
    assert result.returncode == 1
    assert "satisfied" not in result.stdout


def test_the_contract_rejects_a_non_executable_daemon(tmp_path):
    result = image(tmp_path, "fedora", KEYRING_FILES, executable=False)
    assert result.returncode == 1
    assert "satisfied" not in result.stdout


def test_the_contract_rejects_an_executable_directory(tmp_path):
    result = image(
        tmp_path,
        "fedora",
        KEYRING_FILES,
        directories=KEYRING_FILES,
    )
    assert result.returncode == 1
    assert "satisfied" not in result.stdout


@pytest.mark.parametrize(
    "os_id,files,waived",
    [
        ("fedora", [], 1),
        ("fedora", OO7_FILES, 1),
        ("eln", ["usr/lib64/security/pam_oo7.so"], 1),
        ("eln", KEYRING_FILES, 2),
    ],
)
def test_hummingbird_bootstrap_waiver_still_applies(tmp_path, os_id, files, waived):
    # Every require_* honours the hummingbird bootstrap waiver except on
    # cosmic (tunaOS#2513); the executable check must not be the exception.
    result = image(tmp_path, os_id, files, env={"IS_HUMMINGBIRD": "true", "desktop": "gnome"})
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"satisfied waived={waived}\n"


def test_hummingbird_cosmic_gets_no_waiver(tmp_path):
    result = image(tmp_path, "fedora", [], env={"IS_HUMMINGBIRD": "true", "desktop": "cosmic"})
    assert result.returncode == 1
    assert "satisfied" not in result.stdout


@pytest.mark.parametrize("case", ["gnome", "tuna"])
def test_gnome_and_tuna_contracts_use_the_secret_service_check(case):
    source = CHECK.read_text()
    match = re.search(rf"^[ \t]*{case}\)[ \t]*$.*?^[ \t]*;;[ \t]*$", source, re.M | re.S)
    assert match, f"the desktop contract has no {case} case"
    assert "require_secret_service" in match.group(0)
    assert "gnome-keyring-daemon" not in match.group(0)
