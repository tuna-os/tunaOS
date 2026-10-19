"""Real dpkg dependency checks in a private package database, never host packages.

No maintainer scripts or file payloads are installed. The wrapper redirects only
root/database and relaxes the root-user check for this unprivileged fixture.
RPM/pacman/Portage qualification is not established by this test.
"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

HELPER = Path(__file__).resolve().parents[1] / "build_scripts/lib/fork-removals.sh"


@pytest.mark.skipif(not all(shutil.which(x) for x in ("dpkg", "dpkg-query", "dpkg-deb")),
                    reason="native dpkg toolchain unavailable")
def test_native_dpkg_dependency_refusal_and_exact_removal(tmp_path):
    database_root = tmp_path / "root"
    database_root.mkdir()
    commands = {name: shutil.which(name) for name in ("dpkg", "dpkg-query", "dpkg-deb")}
    for name, depends in (("fixture-library", ""), ("fixture-app", "fixture-library"), ("fixture-spare", "")):
        control = tmp_path / name / "DEBIAN"
        control.mkdir(parents=True)
        (control / "control").write_text(
            f"Package: {name}\nVersion: 1.0\nArchitecture: all\nMaintainer: Fixture <fixture@example.invalid>\n"
            + (f"Depends: {depends}\n" if depends else "") + "Description: Empty qualification fixture\n")
        archive = tmp_path / f"{name}.deb"
        subprocess.run([commands["dpkg-deb"], "--build", str(control.parent), str(archive)], check=True,
                       capture_output=True)
        subprocess.run([commands["dpkg"], f"--root={database_root}", "--force-not-root", "--install", str(archive)],
                       check=True, capture_output=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("dpkg", "dpkg-query"):
        path = bindir / name
        flags = f'--root="{database_root}" --force-not-root' if name == "dpkg" else f'--admindir="{database_root}/var/lib/dpkg"'
        path.write_text(f'#!/bin/sh\nexec "{commands[name]}" {flags} "$@"\n')
        path.chmod(0o755)

    def remove(package):
        return subprocess.run(["bash", "-c", 'source "$1"; tunaos_qualify_fork_removals apt "$2"',
                               "test", str(HELPER), package],
                              env=dict(os.environ, PATH=f"{bindir}:/usr/sbin:/usr/bin:/sbin:/bin",
                                       TUNAOS_FORK_REMOVAL_QUALIFICATION="1"), text=True, capture_output=True)

    def installed():
        output = subprocess.check_output([commands["dpkg-query"], f"--admindir={database_root}/var/lib/dpkg",
                                          "-W", "-f=${Package} ${db:Status-Status}\\n"], text=True)
        return {line.split()[0] for line in output.splitlines() if line.endswith(" installed")}

    original = installed()
    assert original == {"fixture-library", "fixture-app", "fixture-spare"}
    result = remove("fixture-library")
    assert result.returncode != 0
    assert "dependency problems" in result.stderr
    assert installed() == original
    result = remove("fixture-missing")
    assert result.returncode != 0
    assert installed() == original
    result = remove("fixture-spare")
    assert result.returncode == 0, result.stderr
    assert installed() == original - {"fixture-spare"}
    assert remove("fixture-spare").returncode != 0
    assert remove("fixture-app").returncode == 0
    assert remove("fixture-library").returncode == 0
    assert installed() == set()
