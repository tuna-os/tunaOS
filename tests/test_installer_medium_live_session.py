"""GDM starts the session of the cell's desktop on the live medium (tunaOS#4905).

Falsification: the Brussels ISO asked GDM for `xfwl4`; the image's session is
`xfce-wayland`, and GDM fell back to GNOME. The helper must take the name
from the image and must refuse an image where it finds none.
"""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "installer-medium/live/usr/libexec/medium-live-gdm-session"
loader = importlib.machinery.SourceFileLoader("medium_live_gdm_session", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


def image(tmp_path, desktop, wayland=(), x11=()):
    (tmp_path / "usr/lib/medium-live").mkdir(parents=True)
    (tmp_path / "usr/lib/medium-live/desktop").write_text(desktop + "\n")
    for directory, names in (("wayland-sessions", wayland), ("xsessions", x11)):
        (tmp_path / "usr/share" / directory).mkdir(parents=True)
        for name in names:
            (tmp_path / "usr/share" / directory / f"{name}.desktop").write_text("[Desktop Entry]\n")
    return tmp_path


def record(root):
    return (root / "var/lib/AccountsService/users/liveuser").read_text()


def test_brussels_gets_its_xfce_session_not_gnome(tmp_path):
    root = image(tmp_path, "xfce", wayland=("gnome", "xfce-wayland"), x11=("xfce",))
    assert helper.main(["liveuser", "--root", str(root)]) == 0
    assert "Session=xfce-wayland\n" in record(root)


def test_gnome_takes_the_plain_session_before_classic(tmp_path):
    root = image(tmp_path, "gnome", wayland=("gnome-classic", "gnome"), x11=("gnome-xorg",))
    assert helper.main(["liveuser", "--root", str(root)]) == 0
    assert "Session=gnome\n" in record(root)


def test_one_session_needs_no_record(tmp_path):
    root = image(tmp_path, "tuna", wayland=("shell",))
    assert helper.main(["liveuser", "--root", str(root)]) == 0
    assert not (root / "var/lib/AccountsService").exists()


def test_no_session_for_the_desktop_is_an_error_not_a_default(tmp_path):
    root = image(tmp_path, "xfce", wayland=("gnome", "plasma"))
    with pytest.raises(SystemExit, match="no session for desktop 'xfce'"):
        helper.main(["liveuser", "--root", str(root)])


def test_an_unknown_desktop_is_an_error(tmp_path):
    root = image(tmp_path, "mate", wayland=("mate",))
    with pytest.raises(SystemExit, match="unknown desktop"):
        helper.main(["liveuser", "--root", str(root)])


def test_the_live_setup_calls_the_helper_and_the_image_ships_it():
    setup = (ROOT / "installer-medium/live/usr/libexec/medium-live-setup").read_text()
    assert '/usr/libexec/medium-live-gdm-session "${user}"' in setup
    # Reached, not only invoked: the call comes before the hook loop and no
    # `exit` comes before it.
    head = setup[: setup.index("medium-live-gdm-session")]
    assert "\nexit" not in head
    assert "/usr/libexec/medium-live-gdm-session" in (ROOT / "installer-medium/Containerfile.live").read_text()
