"""tunaOS#5029: the Debian and Ubuntu initramfs names the variant.

On main, canary flounder:xfce stopped with `initrd-release PRETTY_NAME='',
want 'Flounder (Initramfs)'` (job 139635717891), grouper:tuna and gurnard:tuna
with `PRETTY_NAME='Grouper dracut-110-11ubuntu0.1 (Initramfs)'` and
`'Gurnard dracut-060+5-1ubuntu3.4 (Initramfs)'` (jobs 139650727965,
139648017449). Debian's dracut writes no PRETTY_NAME line, and the identity
module only substituted existing lines. The Ubuntu bootc path builds its
initramfs in bootc/finalize.sh and did not install the module. #4989 fixed
both: the module deletes and appends, and finalize.sh runs initrd-hostname.sh.

Falsification: behavioural. With the old `sed s|^PRETTY_NAME=...|` the first
test leaves PRETTY_NAME absent. Without the initrd-hostname.sh line before
dracut in finalize.sh, the last test fails.
"""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "build_scripts/dracut/99tunaos-identity/module-setup.sh"
FINALIZE = ROOT / "build_scripts/bootc/finalize.sh"

# initrd-release lines as dracut writes them. Debian: no PRETTY_NAME and no
# DEFAULT_HOSTNAME (flounder). Ubuntu: dracut's version in PRETTY_NAME.
DEBIAN = 'NAME="Debian GNU/Linux"\nID=debian\nVERSION_ID="13"\n'
UBUNTU = ('NAME="Ubuntu"\nID=ubuntu\n'
          'PRETTY_NAME="Grouper dracut-110-11ubuntu0.1 (Initramfs)"\n'
          'DRACUT_VERSION=110-11ubuntu0.1\n')


def run_module(tmp_path, release, host):
    initdir = tmp_path / "initdir"
    sysroot = tmp_path / "sysroot"
    (initdir / "usr/lib").mkdir(parents=True)
    (sysroot / "usr/lib").mkdir(parents=True)
    (initdir / "usr/lib/initrd-release").write_text(release)
    (sysroot / "usr/lib/os-release").write_text(f'NAME="{host.capitalize()}"\nDEFAULT_HOSTNAME="{host}"\n')
    subprocess.run(["bash", "-c", f'source "{MODULE}"; install'], check=True,
                   env={"PATH": "/usr/bin:/bin", "initdir": str(initdir),
                        "dracutsysrootdir": str(sysroot)})
    return (initdir / "usr/lib/initrd-release").read_text()


def keys(text):
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out.setdefault(k, []).append(v.strip('"'))
    return out


@pytest.mark.parametrize("release, host", [(DEBIAN, "flounder"), (UBUNTU, "grouper"), (UBUNTU, "gurnard")])
def test_the_module_writes_one_name_line_each(tmp_path, release, host):
    got = keys(run_module(tmp_path, release, host))
    assert got["PRETTY_NAME"] == [f"{host.capitalize()} (Initramfs)"]
    assert got["NAME"] == [host.capitalize()]
    assert got["DEFAULT_HOSTNAME"] == [host]


def test_the_ubuntu_bootc_path_installs_the_module_before_dracut():
    lines = FINALIZE.read_text().splitlines()
    seed = next(i for i, line in enumerate(lines) if line.strip().endswith('build_scripts/initrd-hostname.sh"'))
    dracut = next(i for i, line in enumerate(lines) if line.lstrip().startswith("dracut "))
    assert seed < dracut
