"""tunaOS#2616: flounder-sid failed when the kernel was already in place.

Debian sid's kernel package began installing /usr/lib/modules/<kver>/vmlinuz
as the same file as /boot/vmlinuz-<kver>. Containerfile.debian ran a bare
`cp /boot/vmlinuz-* .../vmlinuz`, and `cp` exits 1 on "are the same file",
so every flounder-sid build died at that step (run 36075110945).

Falsification: behavioural — the real RUN line from Containerfile.debian
runs under /bin/sh against a scratch root where the destination is a hard
link to the source. The bare `cp` it replaced exits 1 there (checked); the
fixed line exits 0. A second case checks the copy still happens when the
destination is missing (trixie, where the kernel sits only in /boot).
"""

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTAINERFILE = (ROOT / "Containerfile.debian").read_text(encoding="utf-8")


def _kernel_copy_run() -> str:
    m = re.search(
        r"^RUN (dest=\"\$\(find /usr/lib/modules.*?test -s \"\$dest\")\n",
        CONTAINERFILE,
        re.S | re.M,
    )
    assert m, "the kernel copy RUN step is not in Containerfile.debian"
    return m.group(1).replace("\\\n", "\n")


def _run(tmp_path: Path, script: str) -> subprocess.CompletedProcess:
    body = script.replace("/usr/lib/modules", f"{tmp_path}/usr/lib/modules")
    body = body.replace("/boot/", f"{tmp_path}/boot/")
    return subprocess.run(["sh", "-c", body], capture_output=True, text=True)


def _root(tmp_path: Path, linked: bool) -> Path:
    kver = "7.2.7+deb14-amd64"
    (tmp_path / "boot").mkdir()
    moddir = tmp_path / "usr/lib/modules" / kver
    moddir.mkdir(parents=True)
    src = tmp_path / "boot" / f"vmlinuz-{kver}"
    src.write_bytes(b"\x7fkernel image")
    if linked:
        os.link(src, moddir / "vmlinuz")
    return moddir / "vmlinuz"


def test_an_identical_kernel_in_place_does_not_fail_the_build(tmp_path):
    dest = _root(tmp_path, linked=True)
    proc = _run(tmp_path, _kernel_copy_run())
    assert proc.returncode == 0, proc.stderr
    assert dest.read_bytes() == b"\x7fkernel image"


def test_the_kernel_is_still_copied_when_missing(tmp_path):
    dest = _root(tmp_path, linked=False)
    proc = _run(tmp_path, _kernel_copy_run())
    assert proc.returncode == 0, proc.stderr
    assert dest.read_bytes() == b"\x7fkernel image"


def test_the_old_bare_copy_fails_on_the_same_file(tmp_path):
    # Premise: without this, the first test proves nothing.
    _root(tmp_path, linked=True)
    old = 'cp /boot/vmlinuz-* "$(find /usr/lib/modules -maxdepth 1 -type d | tail -1)/vmlinuz"'
    assert _run(tmp_path, old).returncode != 0
