"""tunaOS#4104: bonito-rawhide's initramfs must carry its own splash, dragon.

bonito-rawhide publishes as `bonito`, so build-image-inner.sh hands its build
IMAGE_NAME=bonito and IMAGE_NAME_VARIANT=bonito-rawhide. 26-packages-post.sh
passed IMAGE_NAME to plymouth-set-theme.sh as an explicit argument, which the
selector prefers to IMAGE_NAME_VARIANT, so Rawhide selected Bonito's
fishing-pole right before dracut copied the theme into the initramfs (source
path at 193cc0ef, build_scripts/26-packages-post.sh:50). flounder-sid, the
other variant with a publish_name, lost its radioactive splash the same way.
verify-branding.sh accepted it: any image with the generic tunaos theme passed
"TunaOS plymouth theme active".

The real 26-packages-post.sh runs here with its literal filesystem roots
redirected into a fixture image (the tests/test_anime_finalization.py
technique), so the real selector and the real initramfs check both run. Only
the network, the package database, systemd and dracut are stubbed. The dracut
stub packs what plymouth-populate-initrd packs: plymouthd.conf, the configured
theme, the plugin its ModuleName names and default.plymouth. The fake lsinitrd
unpacks that. No image is built.

Falsification: behavioural. Restore `"${IMAGE_NAME:-}"` as the selector's
argument in 26-packages-post.sh and the Rawhide and flounder-sid rows select
their publish-name sibling's theme. The check-level tests mutate one real
initramfs, one way each, and require build_scripts/checks/
verify-plymouth-initramfs.sh to reject it. They also require that a Bonito
fishing-pole initramfs fails a Rawhide check, and the reverse.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "build_scripts"
THEMES = ROOT / "system_files/usr/share/plymouth/themes"
KVER = "6.99.0-1.fc44.x86_64"
INITRAMFS = f"usr/lib/modules/{KVER}/initramfs.img"

IDENTITY = {
    row[0]: row[5]
    for row in (line.split("\t") for line in
                (SCRIPTS / "lib/variant-identity.tsv").read_text().splitlines()
                if line and not line.startswith("#"))
}
PUBLISH = {
    vid: cfg.get("publish_name", vid)
    for vid, cfg in tomllib.loads((ROOT / "tunaos.toml").read_text())["variants"].items()
}

# Literal roots at the start of a path, not inside one and not the shebang.
ROOTS = re.compile(r"(?<![\w.!/$-])/(usr|etc|var|lib)/")

STUBS = {
    # 26-packages-post.sh downloads fonts and a PDF; give it a valid empty
    # archive so its real tar step runs.
    "curl": """#!/bin/bash
while [[ $# -gt 0 ]]; do
  if [[ "$1" == -o ]]; then tar -cJf "$2" --files-from /dev/null; shift; fi
  shift
done
""",
    "rpm": f"#!/bin/sh\necho kernel-{KVER}\n",
    "systemctl": "#!/bin/sh\nexit 0\n",
    "depmod": "#!/bin/sh\nexit 0\n",
    "fc-cache": "#!/bin/sh\nexit 0\n",
    "plymouthd": "#!/bin/sh\nexit 0\n",
    # The selector must write the link itself; a distro helper is optional.
    "plymouth-set-default-theme": "#!/bin/sh\nexit 0\n",
    "lsinitrd": """#!/usr/bin/env python3
import sys, tarfile
args = sys.argv[1:]
assert args[0] == "--unpack", args
tarfile.open(args[1]).extractall(".", filter="tar")
""",
}

# What plymouth-populate-initrd puts in the initramfs for the configured theme.
DRACUT = """#!/usr/bin/env python3
import os, re, sys, tarfile
from pathlib import Path
root = Path({root!r})
out = sys.argv[sys.argv.index("-f") + 1]
conf = root / "etc/plymouth/plymouthd.conf"
theme = re.findall(r"^Theme=(.*)$", conf.read_text(), re.M)[-1]
with open({log!r}, "a") as log:
    log.write(theme + "\\n")
themes = "usr/share/plymouth/themes"
definition = root / themes / theme / f"{{theme}}.plymouth"
# A distro theme (the selector kept it) is not in this fixture image.
module = (re.search(r"^ModuleName=(.*)$", definition.read_text(), re.M).group(1)
          if definition.exists() else "none")
with tarfile.open(out, "w") as tar:
    for rel in ("etc/plymouth/plymouthd.conf", f"{{themes}}/{{theme}}",
                f"usr/lib64/plymouth/{{module}}.so", f"{{themes}}/default.plymouth"):
        if os.path.lexists(root / rel):
            tar.add(root / rel, arcname=rel)
"""


class Build:
    """A fixture image plus the build context 26-packages-post.sh runs from."""

    def __init__(self, tmp_path, variant, image_name=None):
        self.tmp = tmp_path
        self.root = tmp_path / "root"
        self.context = tmp_path / "context" / "build_scripts"
        self.stubs = tmp_path / "stubs"
        self.dracut_log = tmp_path / "dracut.log"
        self.env = {
            "PATH": f"{self.stubs}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "IMAGE_NAME": image_name or PUBLISH[variant],
            "IMAGE_NAME_VARIANT": variant,
            "PLYMOUTH_SYSROOT": str(self.root),
        }
        r = self.root
        (r / "usr/lib/modules" / KVER).mkdir(parents=True)
        (r / "lib").symlink_to("usr/lib")
        (r / "usr/lib/os-release").write_text('NAME="Fedora Linux"\nVERSION_ID=44\n')
        (r / "etc/dracut.conf.d").mkdir(parents=True)
        (r / "etc/plymouth").mkdir()
        # The distro's own choice, which the selector must replace.
        (r / "etc/plymouth/plymouthd.conf").write_text("[Daemon]\nTheme=bgrt\n")
        (r / "usr/lib64/plymouth").mkdir(parents=True)
        for plugin in ("script.so", "text.so", "details.so"):
            (r / "usr/lib64/plymouth" / plugin).write_bytes(b"\x7fELF fixture plugin")
        # 00-copy-files.sh lays down every theme, and default.plymouth -> tunaos.
        shutil.copytree(THEMES, r / "usr/share/plymouth/themes", symlinks=True)
        (r / "usr/bin").mkdir(parents=True)
        self._exe(r / "usr/bin/dracut", DRACUT.format(root=str(r), log=str(self.dracut_log)))

        (self.context / "lib").mkdir(parents=True)
        for adapter in ("identity.env", "variant-aliases.tsv", "variant-identity.tsv"):
            shutil.copyfile(SCRIPTS / "lib" / adapter, self.context / "lib" / adapter)
        for script in ("26-packages-post.sh", "plymouth-set-theme.sh"):
            source = ROOTS.sub(lambda m: f"{r}/{m.group(1)}/", (SCRIPTS / script).read_text())
            source = source.replace("/run/context", str(tmp_path / "context"))
            self._exe(self.context / script, source)
        self._exe(self.context / "install-remora.sh", "#!/bin/sh\nexit 0\n")
        check = SCRIPTS / "checks/verify-plymouth-initramfs.sh"
        (self.context / "checks").mkdir()
        self._exe(self.context / "checks" / check.name, check.read_text())
        self.stubs.mkdir()
        for name, body in STUBS.items():
            self._exe(self.stubs / name, body)

    @staticmethod
    def _exe(path, text):
        path.write_text(text)
        path.chmod(0o755)

    def post_packages(self):
        return subprocess.run(["bash", str(self.context / "26-packages-post.sh")],
                              env=self.env, capture_output=True, text=True)

    def check(self, variant, initramfs=None, path=None):
        env = dict(self.env, PATH=path or self.env["PATH"])
        return subprocess.run(
            ["bash", str(self.context / "checks/verify-plymouth-initramfs.sh"), variant,
             str(initramfs or self.root / INITRAMFS)],
            env=env, capture_output=True, text=True)

    def selected(self):
        conf = (self.root / "etc/plymouth/plymouthd.conf").read_text()
        link = (self.root / "usr/share/plymouth/themes/default.plymouth").readlink()
        return re.findall(r"^Theme=(.*)$", conf, re.M)[-1], str(link)

    def mutate_initramfs(self, edit):
        """Unpack the built initramfs, apply edit(tree), pack it back."""
        tree = self.tmp / "unpacked"
        shutil.rmtree(tree, ignore_errors=True)
        img = self.root / INITRAMFS
        with tarfile.open(img) as tar:
            tar.extractall(tree, filter="tar")
        edit(tree)
        with tarfile.open(img, "w") as tar:
            for child in sorted(tree.iterdir()):
                tar.add(child, arcname=child.name)


def built(tmp_path, variant, image_name=None):
    build = Build(tmp_path, variant, image_name)
    result = build.post_packages()
    assert result.returncode == 0, result.stdout + result.stderr
    return build


# ---------------------------------------------------------------- caller --

@pytest.mark.parametrize("variant", sorted(IDENTITY))
def test_post_packages_selects_each_variants_own_theme_before_dracut(tmp_path, variant):
    """Every declared variant, built under its publish name, as CI builds it."""
    build = built(tmp_path, variant)
    theme = IDENTITY[variant]
    assert build.selected() == (theme, f"{theme}/{theme}.plymouth")
    # dracut ran once, after the selection, and saw this variant's theme.
    assert build.dracut_log.read_text().split() == [theme]


def test_rawhide_publishing_as_bonito_boots_dragon_not_fishing_pole(tmp_path):
    assert PUBLISH["bonito-rawhide"] == "bonito"
    build = built(tmp_path, "bonito-rawhide")
    assert build.selected() == ("dragon", "dragon/dragon.plymouth")
    assert build.dracut_log.read_text().split() == ["dragon"]


def test_bonito_still_boots_fishing_pole(tmp_path):
    """Positive control: a globally forced theme cannot satisfy both."""
    build = built(tmp_path, "bonito")
    assert build.selected() == ("fishing-pole", "fishing-pole/fishing-pole.plymouth")
    assert build.dracut_log.read_text().split() == ["fishing-pole"]


def test_a_distro_alias_still_resolves_through_the_caller(tmp_path):
    """IMAGE_NAME_VARIANT unset, IMAGE_NAME the distro alias: the alias table
    still maps it to its owner's theme."""
    build = Build(tmp_path, "bonito", image_name="fedora")
    del build.env["IMAGE_NAME_VARIANT"]
    result = build.post_packages()
    assert result.returncode == 0, result.stdout + result.stderr
    assert build.selected()[0] == "fishing-pole"


# ------------------------------------------------- initramfs check, positive --

@pytest.mark.parametrize("variant", ["bonito", "bonito-rawhide"])
def test_post_packages_runs_the_initramfs_check_and_it_passes(tmp_path, variant):
    build = built(tmp_path, variant)
    result = build.check(variant)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"TUNAOS_PLYMOUTH_OK variant={variant} theme={IDENTITY[variant]}" in result.stdout


def test_the_caller_fails_the_build_when_the_initramfs_is_wrong(tmp_path):
    """26-packages-post.sh must run the check on the image dracut just wrote."""
    build = Build(tmp_path, "bonito-rawhide")
    # A dracut that ignores the selection and packs Bonito's art.
    dracut = build.root / "usr/bin/dracut"
    dracut.write_text(dracut.read_text().replace(
        'theme = re.findall(r"^Theme=(.*)$", conf.read_text(), re.M)[-1]',
        'theme = "fishing-pole"'))
    result = build.post_packages()
    assert result.returncode != 0
    assert "TUNAOS_PLYMOUTH_FAIL variant=bonito-rawhide theme=dragon" in result.stderr


# ------------------------------------------------- initramfs check, negative --

def test_bonito_initramfs_fails_the_rawhide_check_and_the_reverse(tmp_path):
    bonito = built(tmp_path / "b", "bonito")
    rawhide = built(tmp_path / "r", "bonito-rawhide")
    swapped = rawhide.check("bonito-rawhide", initramfs=bonito.root / INITRAMFS)
    assert swapped.returncode != 0
    assert "initramfs plymouthd.conf Theme='fishing-pole', want 'dragon'" in swapped.stderr
    assert "initramfs lacks usr/share/plymouth/themes/dragon/dragon.plymouth" in swapped.stderr
    reverse = bonito.check("bonito", initramfs=rawhide.root / INITRAMFS)
    assert reverse.returncode != 0
    assert "Theme='dragon', want 'fishing-pole'" in reverse.stderr


def _theme(tree, name):
    return tree / "usr/share/plymouth/themes" / name


def _wrong_conf(tree):
    (tree / "etc/plymouth/plymouthd.conf").write_text("[Daemon]\nTheme=fishing-pole\n")


def _wrong_default(tree):
    link = _theme(tree, "default.plymouth")
    link.unlink()
    link.symlink_to("tunaos/tunaos.plymouth")


def _no_default(tree):
    _theme(tree, "default.plymouth").unlink()


def _only_the_generic_fish(tree):
    shutil.rmtree(_theme(tree, "dragon"))
    shutil.copytree(THEMES / "tunaos", _theme(tree, "tunaos"))


def _sibling_theme_too(tree):
    shutil.copytree(THEMES / "fishing-pole", _theme(tree, "fishing-pole"))


def _no_plugin(tree):
    (tree / "usr/lib64/plymouth/script.so").unlink()


def _no_script(tree):
    (_theme(tree, "dragon") / "dragon.script").unlink()


def _missing_frame(tree):
    (_theme(tree, "dragon") / "dragon-0042.png").unlink()


def _stale_frame(tree):
    shutil.copyfile(THEMES / "fishing-pole/fishing-pole-0001.png",
                    _theme(tree, "dragon") / "dragon-0001.png")


def _stray_asset(tree):
    shutil.copyfile(THEMES / "fishing-pole/fishing-pole-0001.png",
                    _theme(tree, "dragon") / "fishing-pole-0001.png")


@pytest.mark.parametrize("edit, reason", [
    (_wrong_conf, "initramfs plymouthd.conf Theme='fishing-pole', want 'dragon'"),
    (_wrong_default, "initramfs default.plymouth -> 'tunaos/tunaos.plymouth', want dragon/dragon.plymouth"),
    (_no_default, "initramfs has no default.plymouth link"),
    (_only_the_generic_fish, "initramfs lacks usr/share/plymouth/themes/dragon/dragon.plymouth"),
    (_sibling_theme_too, "initramfs carries other variants' themes: fishing-pole"),
    (_no_plugin, "initramfs lacks the script.so plugin dragon needs"),
    (_no_script, "initramfs lacks ScriptFile '/usr/share/plymouth/themes/dragon/dragon.script'"),
    (_missing_frame, "initramfs lacks 1 of the 57 frames dragon animates"),
    (_stale_frame, "initramfs dragon assets differ from the image's"),
    (_stray_asset, "initramfs dragon assets differ from the image's"),
], ids=lambda v: v.__name__.lstrip("_") if callable(v) else "")
def test_initramfs_check_rejects(tmp_path, edit, reason):
    build = built(tmp_path, "bonito-rawhide")
    build.mutate_initramfs(edit)
    result = build.check("bonito-rawhide")
    assert result.returncode == 1, result.stdout
    assert reason in result.stderr
    assert "TUNAOS_PLYMOUTH_FAIL variant=bonito-rawhide theme=dragon" in result.stderr


def test_initramfs_check_rejects_a_wrong_image_root_selection(tmp_path):
    build = built(tmp_path, "bonito-rawhide")
    (build.root / "etc/plymouth/plymouthd.conf").write_text("[Daemon]\nTheme=tunaos\n")
    result = build.check("bonito-rawhide")
    assert result.returncode == 1
    assert "image plymouthd.conf Theme='tunaos', want 'dragon'" in result.stderr


def test_initramfs_check_fails_without_an_initramfs(tmp_path):
    build = built(tmp_path, "bonito-rawhide")
    result = build.check("bonito-rawhide", initramfs=tmp_path / "absent.img")
    assert result.returncode == 1
    assert "missing or empty initramfs" in result.stderr


def test_initramfs_check_fails_when_lsinitrd_is_unavailable(tmp_path):
    if shutil.which("lsinitrd", path="/usr/bin:/bin"):
        pytest.skip("host lsinitrd on /usr/bin:/bin; cannot hide it")
    build = built(tmp_path, "bonito-rawhide")
    (build.stubs / "lsinitrd").unlink()
    result = build.check("bonito-rawhide")
    assert result.returncode == 1
    assert "lsinitrd is unavailable" in result.stderr


# ------------------------------------------- no splash support: BLOCKED, said --

def test_an_image_without_the_script_plugin_is_blocked_not_passed(tmp_path):
    """hummingbird's --skip-unavailable package set does not ask for
    plymouth-plugin-script. The selector keeps the distro splash; the check
    names that instead of passing it, and the build carries on with a warning."""
    build = Build(tmp_path, "bonito-rawhide")
    (build.root / "usr/lib64/plymouth/script.so").unlink()
    result = build.post_packages()
    assert result.returncode == 0, result.stdout + result.stderr
    assert build.selected() == ("bgrt", "tunaos/tunaos.plymouth")
    assert ("TUNAOS_PLYMOUTH_BLOCKED variant=bonito-rawhide theme=dragon "
            "reason=the_image_lacks_the_plymouth_script_plugin_dragon_needs") in result.stderr
    assert "::warning::no TunaOS boot splash in this image" in result.stdout
    assert build.check("bonito-rawhide").returncode == 2


def test_an_image_without_plymouth_is_blocked_not_passed(tmp_path):
    if shutil.which("plymouthd", path="/usr/bin:/bin"):
        pytest.skip("host plymouthd on /usr/bin:/bin; cannot hide it")
    build = built(tmp_path, "bonito-rawhide")
    (build.stubs / "plymouthd").unlink()
    result = build.check("bonito-rawhide")
    assert result.returncode == 2
    assert "reason=plymouth_is_not_installed_in_the_image" in result.stderr


def test_blocked_is_not_a_way_around_a_wrong_initramfs(tmp_path):
    """With the plugin in the image, a missing plugin in the initramfs is a
    FAIL (exit 1), which the caller does not tolerate."""
    build = built(tmp_path, "bonito-rawhide")
    build.mutate_initramfs(_no_plugin)
    assert build.check("bonito-rawhide").returncode == 1
