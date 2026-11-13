"""An XFCE image whose display manager is GDM offers only the XFCE session.

Arch's gdm package pulls in gnome-shell and gnome-session, and GDM's fallback
prefers GNOME. marlin-xfce (iso-builder run 43429585359) autologged liveuser
into GNOME Shell: the frames show "Marlin Installer" under a GNOME top bar.
"""
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build_scripts" / "desktop" / "xfce-gdm-session.sh"


def _run(root):
    return subprocess.run(["bash", str(SCRIPT)], env={"TUNAOS_XFCE_GDM_ROOT": str(root), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True, timeout=10)


def _sessions(root, **dirs):
    for directory, names in dirs.items():
        path = root / "usr/share" / directory.replace("_", "-")
        path.mkdir(parents=True, exist_ok=True)
        for name in names:
            (path / name).write_text("[Desktop Entry]\n")


def _left(root):
    return sorted(str(p.relative_to(root / "usr/share")) for p in (root / "usr/share").rglob("*.desktop"))


def test_gnome_sessions_are_removed_and_xfce_stays(tmp_path):
    """Falsification: without the removal GDM autologin lands in GNOME Shell."""
    _sessions(tmp_path, wayland_sessions=["gnome-wayland.desktop", "gnome.desktop"],
              xsessions=["gnome-xorg.desktop", "xfce.desktop"])
    assert _run(tmp_path).returncode == 0
    assert _left(tmp_path) == ["xsessions/xfce.desktop"]


def test_the_xfce_wayland_session_is_kept(tmp_path):
    _sessions(tmp_path, wayland_sessions=["gnome.desktop", "xfce-wayland.desktop"])
    assert _run(tmp_path).returncode == 0
    assert _left(tmp_path) == ["wayland-sessions/xfce-wayland.desktop"]


def test_no_xfce_session_fails_instead_of_leaving_no_session(tmp_path):
    """Falsification: deleting GNOME's entries first would ship an image with
    no session at all."""
    _sessions(tmp_path, wayland_sessions=["gnome.desktop"])
    result = _run(tmp_path)
    assert result.returncode != 0
    assert _left(tmp_path) == ["wayland-sessions/gnome.desktop"]


def test_the_xfce_arch_desktop_runs_it():
    text = (SCRIPT.parents[2] / "tunaos.toml").read_text()
    block = text[text.index("[desktops.xfce-arch]"):text.index("[desktops.xfce-arch.packages]")]
    assert '"xfce-gdm-session"' in block
    assert '"xorg-server"' in text[text.index("[desktops.xfce-arch.packages.pacman]"):text.index("[desktops.xfce-arch.packages.cachyos]")]
