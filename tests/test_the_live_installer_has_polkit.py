"""The live image must carry polkit, or no non-GNOME installer ever opens.

grouper (Ubuntu) has no flatpak in its base, so customize-live.sh installs it
with `apt-get install --no-install-recommends flatpak`. Ubuntu's flatpak only
*Recommends* polkitd, so the live image ended up with no polkit daemon. The
grouper KDE, XFCE and COSMIC pilot ISOs then booted to a desktop with no
installer (tunaOS#4459). Measured as liveuser inside the running COSMIC
session (iso-builder diag run 42689145647):

    $ flatpak run org.tunaos.InstallerCosmic
    error: Not allowed to query parental controls data for user 1000

Ubuntu's flatpak links libmalcontent, accounts-daemon authorizes the
parental-controls read through polkit, and with no polkit the read is denied,
so flatpak refuses to start the app. The frontends also escalate through
`flatpak-spawn --host pkexec`, which needs pkexec on the host.

These tests run the script's own ensure_polkit against fake package managers,
so they check what it actually installs rather than that a string appears.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "live-iso" / "common" / "src" / "customize-live.sh"
SVC = "usr/share/dbus-1/system-services/org.freedesktop.PolicyKit1.service"


def ensure_polkit_fn() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("\tensure_polkit() {")
    end = text.index("\n\t}\n", start) + len("\n\t}\n")
    return "\n".join(line[1:] if line.startswith("\t") else line
                     for line in text[start:end].splitlines())


def fake_bin(tmp_path: Path, name: str, body: str) -> None:
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    f = b / name
    f.write_text("#!/bin/bash\n" + body + "\n", encoding="utf-8")
    f.chmod(0o755)


def run(tmp_path: Path) -> subprocess.CompletedProcess:
    # Only the fake bin dir plus the coreutils the function needs; no real
    # package manager or pkexec from the host can leak in.
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    for t in ("bash", "cat", "touch", "mkdir", "dirname"):
        src = subprocess.run(["bash", "-c", f"command -v {t}"],
                             capture_output=True, text=True).stdout.strip()
        if src:
            (tools / t).symlink_to(src)
    env = {"PATH": f"{tmp_path / 'bin'}:{tools}",
           "TUNA_POLKIT_ROOT": str(tmp_path / "root"),
           "LOG": str(tmp_path / "log")}
    script = ensure_polkit_fn() + "\nensure_polkit\n"
    return subprocess.run([str(tools / "bash"), "-c", script], env=env,
                          capture_output=True, text=True, timeout=30)


def install_effect(pkgs_make_pkexec: bool = True) -> str:
    # What a successful install leaves behind: pkexec on PATH and the
    # polkit D-Bus activation file.
    lines = [
        'echo "$0 $*" >> "$LOG"',
        'case "$*" in *install*)',
        '  mkdir -p "$TUNA_POLKIT_ROOT/usr/share/dbus-1/system-services"',
        f'  touch "$TUNA_POLKIT_ROOT/{SVC}"',
    ]
    if pkgs_make_pkexec:
        lines.append('  printf "#!/bin/bash\\n" > "$(dirname "$0")/pkexec"; '
                     'chmod 755 "$(dirname "$0")/pkexec"')
    lines.append(";; esac")
    return "\n".join(lines)


def test_apt_base_gets_polkitd_and_pkexec(tmp_path):
    fake_bin(tmp_path, "apt-get", install_effect())
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    log = (tmp_path / "log").read_text()
    install = [l for l in log.splitlines() if " install " in l]
    assert install, log
    assert "polkitd" in install[0].split() and "pkexec" in install[0].split()


def test_rpm_base_gets_polkit(tmp_path):
    fake_bin(tmp_path, "dnf5", install_effect())
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "install -y polkit" in (tmp_path / "log").read_text()


def test_present_polkit_installs_nothing(tmp_path):
    fake_bin(tmp_path, "pkexec", "")
    fake_bin(tmp_path, "apt-get", 'echo "$0 $*" >> "$LOG"')
    svc = tmp_path / "root" / SVC
    svc.parent.mkdir(parents=True)
    svc.touch()
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "log").exists()


def test_pkexec_alone_is_not_enough(tmp_path):
    # pkexec without the daemon is exactly the broken grouper state for the
    # parental-controls check, so it must still trigger the install.
    fake_bin(tmp_path, "pkexec", "")
    fake_bin(tmp_path, "apt-get", install_effect(pkgs_make_pkexec=False))
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "polkitd" in (tmp_path / "log").read_text()


def test_unfixable_base_fails(tmp_path):
    r = run(tmp_path)
    assert r.returncode != 0


def test_the_build_stops_when_polkit_cannot_be_installed():
    text = SCRIPT.read_text(encoding="utf-8")
    call = text.index("\tif ! ensure_polkit; then")
    assert "exit 1" in text[call:call + 300]
    # And it runs before the installer flatpak is pulled, next to flatpak's
    # own ensure step, so a base that cannot get polkit fails early.
    assert text.index("\tif ! ensure_flatpak; then") < call
    assert call < text.index("flatpak install --system --noninteractive -y tuna-os")
