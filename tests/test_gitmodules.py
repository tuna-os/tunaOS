from configparser import ConfigParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GRADIA = 'submodule "system_files/usr/share/gnome-shell/extensions/gradia-integration@alexandervanhee.github.io"'


def test_gitmodules_declares_only_the_checked_out_gradia_integration():
    config = ConfigParser()
    config.read(REPO_ROOT / ".gitmodules")

    assert config.sections() == [GRADIA]
    module = config[GRADIA]
    assert module["path"] == "system_files/usr/share/gnome-shell/extensions/gradia-integration@alexandervanhee.github.io"
    assert module["url"] == "https://github.com/AlexanderVanhee/gradia-capture.git"
