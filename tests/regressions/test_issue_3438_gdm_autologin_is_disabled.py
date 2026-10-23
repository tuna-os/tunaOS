"""tunaOS#3438: Tuna GDM must keep the interactive login screen enabled.

Falsification: exercise the real keyfile parser with active true values,
whitespace and case variants, plus false and commented values.
"""
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "build_scripts/checks/verify-desktop-experience.sh"


def function():
    source = CHECK.read_text()
    match = re.search(r"^gdm_autologin_enabled\(\) \{.*?^\}", source, re.M | re.S)
    assert match, "the desktop gate has no GDM autologin check"
    return match.group(0)


def run_check(tmp_path, content):
    config = tmp_path / "custom.conf"
    config.write_text(content)
    script = function() + f"\nif gdm_autologin_enabled {config}; then exit 0; else exit 1; fi"
    return subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True)


@pytest.mark.parametrize(
    "content",
    [
        "AutomaticLoginEnable=true\n",
        " AutomaticLoginEnable\t=\t TRUE # inline comment\n",
        "aUtOmAtIcLoGiNeNaBlE = tRuE\n",
    ],
)
def test_active_gdm_autologin_values_are_rejected(tmp_path, content):
    result = run_check(tmp_path, content)
    assert result.returncode == 0


@pytest.mark.parametrize(
    "content",
    [
        "AutomaticLoginEnable=false\n",
        "AutomaticLoginEnable = false # disabled\n",
        "# AutomaticLoginEnable=true\n",
        "  # AutomaticLoginEnable=true\n",
    ],
)
def test_disabled_or_commented_gdm_autologin_values_are_allowed(tmp_path, content):
    result = run_check(tmp_path, content)
    assert result.returncode != 0
