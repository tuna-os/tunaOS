"""tunaOS#5141: the Ubuntu initramfs carries TPM2 support for the LUKS root.

gurnard:pantheon installed fine and then stopped in the dracut emergency shell
on both lanes (runs 46062207664, 46083846171). The capture of run 46088172319
showed /dev/vda2 as crypto_LUKS, nothing in /dev/mapper, /dev/tpm0 present and
no cryptsetup token plugin directory in the initramfs: dracut's tpm2-tss module
returns 255 from check() and nothing pulled it in.

Falsification: without the drop-in the first test fails; a verifier that does
not look for the token plugin fails the second.
"""
import os
import subprocess
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF = ROOT / "build_scripts/bootc/sandbox/usr/lib/dracut/dracut.conf.d/25-tunaos-tpm2.conf"
CHECK = ROOT / "build_scripts/checks/verify-initramfs-tpm2.sh"
FINALIZE = ROOT / "build_scripts/bootc/finalize.sh"


def test_the_drop_in_adds_the_tpm2_module():
    assert 'add_dracutmodules+=" tpm2-tss "' in CONF.read_text()


def run_check(tmp_path, listing):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    lsinitrd = bin_dir / "lsinitrd"
    lsinitrd.write_text(f"#!/usr/bin/bash\ncat <<'EOF'\n{listing}\nEOF\n")
    lsinitrd.chmod(lsinitrd.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return subprocess.run(["bash", str(CHECK), "initramfs.img"], env=env, capture_output=True, text=True)


def test_the_check_wants_the_token_plugin(tmp_path):
    (tmp_path / "ok").mkdir()
    (tmp_path / "bad").mkdir()
    ok = run_check(tmp_path / "ok", "usr/bin/systemd-cryptsetup\nusr/lib/x86_64-linux-gnu/cryptsetup/libcryptsetup-token-systemd-tpm2.so")
    assert ok.returncode == 0
    bad = run_check(tmp_path / "bad", "usr/bin/systemd-cryptsetup\nusr/lib/libcryptsetup.so.12")
    assert bad.returncode != 0 and "5141" in bad.stderr


def test_finalize_runs_the_check_on_the_new_initramfs():
    text = FINALIZE.read_text()
    assert text.index("dracut --force") < text.index("verify-initramfs-tpm2.sh") < text.index("bootc/mount-system.sh")
