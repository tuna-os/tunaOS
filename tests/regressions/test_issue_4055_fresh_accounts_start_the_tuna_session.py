"""#4055: fresh accounts need version-correct Tuna selection, not fake records.

Published marlin had only DefaultSession=tuna.desktop and launched GNOME
(desktop run 40811792200). Native run 41215443626 then launched Tuna but
created no AccountsService record with inherited Session=tuna. Exact GDM
51.1.1 / AccountsService 26.27.3 source supports empty inheritance plus the
real fallback so stock SetSession changes the value. Older GDM still needs
Session=tuna because it prefers launchable GNOME, including hidden entries.

These behavioral writer/guard tests hold both policies and reject malformed
or shadowing configuration. They do not prove native session persistence.
"""
from pathlib import Path
import os
import re
import shlex
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRITER = ROOT / "build_scripts/desktop/tuna-gdm-default-session.sh"
CHECK = ROOT / "build_scripts/checks/verify-desktop-experience.sh"
PUBLISHED_GDM = "[daemon]\nDefaultSession=tuna.desktop\n[security]\n"
TUNA_GDM = "[daemon]\nFallbackSession=tuna\n"
UPSTREAM_TEMPLATE = "[Template]\n#EnvironmentFiles=/etc/os-release;\n[User]\nSession=\nIcon=${HOME}/.face\n"
TUNA_TEMPLATE = "[User]\nSession=tuna\n"
EMPTY_TEMPLATE = "[User]\nSession=\n"


def install_gdm(root, version="GDM 51.1.1", capability=True, name="gdm", directory="usr/bin", exit_code=0):
    binary = root / directory / name
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(
        "#!/bin/sh\nprintf '%s\\n' " + shlex.quote(version) + "\n"
        + ("# daemon/FallbackSession\n" if capability else "")
        + f"exit {exit_code}\n"
    )
    binary.chmod(0o755)


def contract(root):
    match = re.search(r"^tuna_fresh_account_session_contract\(\) \{.*?^\}", CHECK.read_text(), re.M | re.S)
    assert match, "the desktop gate has no fresh-account session contract"
    script = match.group(0) + '\ntuna_fresh_account_session_contract "$1/etc/gdm/custom.conf" "$1"'
    return subprocess.run(["/bin/bash", "-c", script, "contract", str(root)], capture_output=True, text=True)


def tree(root, gdm=TUNA_GDM, templates=None):
    (root / "etc/gdm").mkdir(parents=True)
    (root / "etc/gdm/custom.conf").write_text(gdm)
    for relative, text in (templates or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def both(directory, text):
    return {f"{directory}/accountsservice/user-templates/{kind}": text for kind in ("standard", "administrator")}


def write_policy(root):
    subprocess.run(["/bin/bash", str(WRITER)], check=True, env=dict(os.environ, TUNAOS_GDM_DEFAULT_ROOT=str(root)))


def test_the_published_tree_fails_the_contract(tmp_path):
    install_gdm(tmp_path)
    tree(tmp_path, PUBLISHED_GDM, both("usr/share", UPSTREAM_TEMPLATE))
    assert contract(tmp_path).returncode != 0


@pytest.mark.parametrize("version, expected", [("47.0", "tuna"), ("48.0", "tuna"), ("50.3", "tuna"), ("51.1.1", "")])
@pytest.mark.parametrize("name,directory", [("gdm", "usr/bin"), ("gdm3", "usr/sbin")])
def test_writer_repairs_published_tree_for_actual_installed_gdm(tmp_path, version, expected, name, directory):
    install_gdm(tmp_path, f"GDM {version}", name=name, directory=directory)
    tree(tmp_path, PUBLISHED_GDM, both("usr/share", UPSTREAM_TEMPLATE))
    write_policy(tmp_path)
    for kind in ("standard", "administrator"):
        text = (tmp_path / f"etc/accountsservice/user-templates/{kind}").read_text()
        assert f"Session={expected}\n" in text.split("[User]", 1)[1]
    assert contract(tmp_path).returncode == 0


@pytest.mark.parametrize("version,template", [("48.0", TUNA_TEMPLATE), ("51.1.1", EMPTY_TEMPLATE)])
@pytest.mark.parametrize("directory", ["run", "etc", "usr/local/share", "usr/share"])
def test_valid_effective_templates_pass(tmp_path, version, template, directory):
    install_gdm(tmp_path, f"GDM {version}")
    tree(tmp_path, templates=both(directory, template))
    assert contract(tmp_path).returncode == 0


@pytest.mark.parametrize("version", ["47.0", "48.0", "50.3", "51.1.1"])
@pytest.mark.parametrize("case", ["missing", "one-missing", "gnome", "wrong-group", "etc-shadow", "run-shadow", "duplicate", "opposite-policy"])
def test_invalid_effective_templates_fail(tmp_path, version, case):
    install_gdm(tmp_path, f"GDM {version}")
    valid = EMPTY_TEMPLATE if version.startswith("51.") else TUNA_TEMPLATE
    opposite = TUNA_TEMPLATE if version.startswith("51.") else EMPTY_TEMPLATE
    templates = {
        "missing": {},
        "one-missing": {"etc/accountsservice/user-templates/standard": valid},
        "gnome": both("etc", "[User]\nSession=gnome\n"),
        "wrong-group": both("etc", valid.replace("[User]", "[Template]") + "[User]\nIcon=fish.png\n"),
        "etc-shadow": {**both("usr/share", valid), **both("etc", opposite)},
        "run-shadow": {**both("etc", valid), **both("run", opposite)},
        "duplicate": both("etc", valid + "Session=gnome\n"),
        "opposite-policy": both("etc", opposite),
    }[case]
    tree(tmp_path, templates=templates)
    assert contract(tmp_path).returncode != 0


@pytest.mark.parametrize("version,template", [("48.0", TUNA_TEMPLATE), ("51.1.1", EMPTY_TEMPLATE)])
@pytest.mark.parametrize("gdm", [
    "[daemon]\n",
    "[daemon]\nFallbackSession=gnome\n",
    "[daemon]\n[Other]\nFallbackSession=tuna\n",
    "[daemon]\nFallbackSession=tuna\nFallbackSession=gnome\n",
    "[daemon]\nFallbackSession=tuna\nDefaultSession=tuna.desktop\n",
])
def test_invalid_fallback_and_obsolete_default_fail(tmp_path, version, template, gdm):
    install_gdm(tmp_path, f"GDM {version}")
    tree(tmp_path, gdm, both("etc", template))
    assert contract(tmp_path).returncode != 0


@pytest.mark.parametrize("version", [None, "unknown", "GDM unknown", "unrelated 51.1.1", "GDM 51"])
@pytest.mark.parametrize("template", [EMPTY_TEMPLATE, TUNA_TEMPLATE])
def test_missing_or_unparseable_gdm_never_bypasses_guard(tmp_path, version, template):
    if version is not None:
        install_gdm(tmp_path, version)
    tree(tmp_path, templates=both("etc", template))
    assert contract(tmp_path).returncode != 0
    write_policy(tmp_path)
    for kind in ("standard", "administrator"):
        assert (tmp_path / f"etc/accountsservice/user-templates/{kind}").read_text() == TUNA_TEMPLATE
    assert contract(tmp_path).returncode != 0


def test_failed_version_command_cannot_select_new_policy(tmp_path):
    install_gdm(tmp_path, exit_code=1)
    tree(tmp_path, templates=both("etc", EMPTY_TEMPLATE))
    assert contract(tmp_path).returncode != 0
    write_policy(tmp_path)
    assert (tmp_path / "etc/accountsservice/user-templates/standard").read_text() == TUNA_TEMPLATE


def test_gdm51_without_compiled_fallback_cannot_admit_empty_templates(tmp_path):
    install_gdm(tmp_path, capability=False)
    tree(tmp_path, templates=both("etc", EMPTY_TEMPLATE))
    assert contract(tmp_path).returncode != 0
    write_policy(tmp_path)
    assert (tmp_path / "etc/accountsservice/user-templates/standard").read_text() == TUNA_TEMPLATE
    assert contract(tmp_path).returncode == 0
