"""tunaOS#2750: Yellowfin had GNOME Shell but no schema and GDM crashed.

The pinned ed95623a image contains gnome-shell-50.0-3, whose false common
provider let DNF omit the RPM containing org.gnome.shell.gschema.xml.
Falsification: behavioural — missing, unreadable, or uncompiled schemas fail
through the real gate function; an installed compiled schema passes.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "build_scripts/checks/verify-desktop-experience.sh"


def function():
    source = CHECK.read_text()
    match = re.search(r"^require_gnome_shell_schema\(\) \{.*?^\}", source, re.M | re.S)
    assert match, "the desktop gate has no compiled schema check"
    return match.group(0)


def run_gate(tmp_path, command=None, hummingbird=False):
    tools = tmp_path / "bin"
    tools.mkdir()
    if command is not None:
        executable = tools / "gsettings"
        executable.write_text("#!/bin/sh\n" + command + "\n")
        executable.chmod(0o755)
    env = {"PATH": str(tools), "IS_HUMMINGBIRD": str(hummingbird).lower()}
    script = "set -euo pipefail\ndesktop=gnome\nwaive() { echo WAIVED; }\n" + function() + "\nrequire_gnome_shell_schema"
    return subprocess.run(["/bin/bash", "-c", script], env=env, capture_output=True, text=True)


def test_gnome_branch_invokes_the_check():
    branch = CHECK.read_text().split('case "$desktop" in\ngnome)', 1)[1].split(";;", 1)[0]
    assert re.search(r"^\s*require_gnome_shell_schema\s*$", branch, re.M)


@pytest.mark.parametrize("command", [None, "exit 1", "echo favorite-apps; exit 1"])
def test_absent_or_failed_schema_lookup_is_fatal(tmp_path, command):
    result = run_gate(tmp_path, command)
    assert result.returncode != 0
    assert "compiled GSettings schema: org.gnome.shell" in result.stderr
    assert "WAIVED" not in result.stdout


def test_lookup_queries_exact_shell_schema(tmp_path):
    result = run_gate(tmp_path, '[ "$#" = 2 ] && [ "$1" = list-keys ] && [ "$2" = org.gnome.shell ]')
    assert result.returncode == 0, result.stderr


def test_hummingbird_waiver_remains_explicit(tmp_path):
    result = run_gate(tmp_path, "exit 1", hummingbird=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "WAIVED"
    assert "compiled GSettings schema: org.gnome.shell" in result.stderr


def test_xml_alone_fails_but_compiled_schema_passes(tmp_path):
    compiler, reader = shutil.which("glib-compile-schemas"), shutil.which("gsettings")
    if not compiler or not reader:
        pytest.skip("GLib tools unavailable")
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "org.gnome.shell.gschema.xml").write_text(
        '<schemalist><schema id="org.gnome.shell" path="/org/gnome/shell/">'
        '<key name="favorite-apps" type="as"><default>[]</default></key>'
        '</schema></schemalist>'
    )
    env = {**os.environ, "GSETTINGS_SCHEMA_DIR": str(schemas), "XDG_DATA_DIRS": str(tmp_path / "empty"), "GSETTINGS_BACKEND": "memory"}
    script = "set -euo pipefail\ndesktop=gnome\nIS_HUMMINGBIRD=false\n" + function() + "\nrequire_gnome_shell_schema"
    missing = subprocess.run(["/bin/bash", "-c", script], env=env, capture_output=True, text=True)
    assert missing.returncode != 0, "XML alone must not satisfy the compiled-schema check"
    subprocess.run([compiler, str(schemas)], check=True)
    present = subprocess.run(["/bin/bash", "-c", script], env=env, capture_output=True, text=True)
    assert present.returncode == 0, present.stderr
