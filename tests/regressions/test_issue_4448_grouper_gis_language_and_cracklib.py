"""tunaOS#4448: GNOME Initial Setup hangs on grouper after it creates the user.

iso-builder run 42912845462 (grouper:gnome, both legs): accounts-daemon created
the user, logged `Couldn't get validated language: Child process exited with
code 1`, and GNOME Initial Setup made no further request until the harness
powered off 6 minutes later. /etc/default/locale was a dangling symlink to
../locale.conf, and User.SetLanguage never returned without a system locale
(20 s gdbus timeout in a podman repro; 0 s once /etc/locale.conf held
LANG=C.UTF-8). The same journal logged pwquality's missing
/var/cache/cracklib/cracklib_dict.pwd every 6 s: bootc does not seed /var.

Falsification: behavioural. The test runs the real
build_scripts/apt-runtime-defaults.sh against a temporary root built like the
measured image. Remove the locale block and the dangling-link case keeps no
/etc/locale.conf (test fails); remove the cracklib block and the dictionary
stays under /var/cache, which 99-cleanup.sh wipes (test fails).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_scripts" / "apt-runtime-defaults.sh"
CLEANUP = ROOT / "build_scripts" / "99-cleanup.sh"


def _apply(tree: Path) -> None:
    subprocess.run(["bash", str(SCRIPT)], check=True, env={**os.environ, "ROOT": str(tree)})


def _measured_tree(tree: Path) -> None:
    (tree / "etc" / "default").mkdir(parents=True)
    (tree / "etc" / "default" / "locale").symlink_to("../locale.conf")
    dictionary = tree / "var" / "cache" / "cracklib"
    dictionary.mkdir(parents=True)
    (dictionary / "cracklib_dict.pwd").write_bytes(b"pwd")
    (dictionary / "cracklib_dict.pwi").write_bytes(b"pwi")


def test_dangling_default_locale_gets_a_system_locale(tmp_path):
    _measured_tree(tmp_path)
    _apply(tmp_path)
    assert (tmp_path / "etc" / "locale.conf").read_text() == "LANG=C.UTF-8\n"
    assert (tmp_path / "etc" / "default" / "locale").read_text() == "LANG=C.UTF-8\n"


def test_an_existing_locale_is_left_alone(tmp_path):
    (tmp_path / "etc" / "default").mkdir(parents=True)
    (tmp_path / "etc" / "locale.conf").write_text("LANG=de_DE.UTF-8\n")
    (tmp_path / "etc" / "default" / "locale").symlink_to("../locale.conf")
    _apply(tmp_path)
    assert (tmp_path / "etc" / "locale.conf").read_text() == "LANG=de_DE.UTF-8\n"


def test_cracklib_dictionary_moves_to_usr_and_is_relinked_at_boot(tmp_path):
    _measured_tree(tmp_path)
    _apply(tmp_path)
    moved = tmp_path / "usr" / "share" / "cracklib" / "cracklib_dict.pwd"
    assert moved.read_bytes() == b"pwd"
    link = tmp_path / "var" / "cache" / "cracklib"
    assert link.is_symlink() and os.readlink(link) == "../../usr/share/cracklib"
    tmpfiles = (tmp_path / "usr" / "lib" / "tmpfiles.d" / "cracklib-usr.conf").read_text()
    assert "L+ /var/cache/cracklib - - - - ../../usr/share/cracklib" in tmpfiles
    # Idempotent: a second run (a later layer) changes nothing.
    _apply(tmp_path)
    assert moved.read_bytes() == b"pwd" and link.is_symlink()


def test_cleanup_runs_it_before_wiping_var():
    text = CLEANUP.read_text(encoding="utf-8")
    call = text.index("/run/context/build_scripts/apt-runtime-defaults.sh")
    wipe = text.index("find /var -mindepth 1 -maxdepth 1")
    assert call < wipe
