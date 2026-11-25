"""99tunaos-identity must set PRETTY_NAME even when dracut wrote none.

Debian's dracut writes NAME but no PRETTY_NAME to initrd-release, so a sed
substitution left it empty and verify-initrd-hostname.sh failed every
flounder canary build.
"""
import subprocess
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent / "build_scripts/dracut/99tunaos-identity/module-setup.sh"


def test_pretty_name_is_added_when_dracut_wrote_none(tmp_path):
    (tmp_path / "usr/lib").mkdir(parents=True)
    (tmp_path / "usr/lib/os-release").write_text('DEFAULT_HOSTNAME="flounder"\n')
    release = tmp_path / "usr/lib/initrd-release"
    release.write_text('NAME="Debian GNU/Linux"\nID=debian\n')
    subprocess.run(
        ["bash", "-c", f'initdir="{tmp_path}"; dracutsysrootdir="{tmp_path}"; source "{MODULE}"; install'],
        check=True,
    )
    lines = release.read_text().splitlines()
    assert 'NAME="Flounder"' in lines
    assert 'PRETTY_NAME="Flounder (Initramfs)"' in lines
    assert 'DEFAULT_HOSTNAME="flounder"' in lines


def test_module_is_force_added_to_dracut(tmp_path):
    """dracut skips unlisted modules unless dracutmodules=all (grouper, dracut 110)."""
    script = MODULE.parents[2] / "initrd-hostname.sh"
    (tmp_path / "usr/lib").mkdir(parents=True)
    (tmp_path / "usr/lib/os-release").write_text('NAME="X"\n')
    subprocess.run(["bash", str(script)], check=True, capture_output=True,
                   env={"PATH": "/usr/bin:/bin", "TUNAOS_SYSROOT": str(tmp_path),
                        "IMAGE_NAME": "grouper"})
    conf = (tmp_path / "usr/lib/dracut/dracut.conf.d/40-tunaos-identity.conf").read_text()
    assert "add_dracutmodules+=\" tunaos-identity \"" in conf
