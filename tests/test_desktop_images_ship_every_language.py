"""Every desktop image ships every language (installer run 45755493549).

bonito:tuna's live installer showed an empty language list: libc had no
locale. The fix installs the full locale set once, for every desktop, in
install-desktop.sh. These tests run that block of the script with a stub
pkg_install for each OS section.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts/desktop/install-desktop.sh"
START = "# ── Every language"
END = "# ── No first-run account wizard"


def locale_block() -> str:
    text = SCRIPT.read_text()
    return text[text.index(START) : text.index(END)]


@pytest.mark.parametrize(
    ("os_section", "want"),
    [
        ("el10", "glibc-all-langpacks"),
        ("fedora", "glibc-all-langpacks"),
        ("rawhide", "glibc-all-langpacks"),
        ("eln", "glibc-all-langpacks"),
        ("apt", "locales-all"),
        ("zypper", "glibc-locale"),
        ("pacman", "glibc-locales"),
        ("hummingbird", ""),
        ("emerge", ""),
    ],
)
def test_each_os_section_installs_its_full_locale_set(os_section: str, want: str) -> None:
    program = f'pkg_install() {{ printf "%s\\n" "$@"; }}\n_TD_OS={os_section}\n' + locale_block()
    out = subprocess.run(["bash", "-c", program], check=True, capture_output=True, text=True).stdout
    assert out.split() == ([want] if want else [])


def test_the_block_runs_for_every_desktop_after_the_package_paths() -> None:
    text = SCRIPT.read_text()
    block = text.index(START)
    # After the last OS path closes and after the display manager block, at
    # the top level of the script, with no early exit before it.
    dnf_end = text.index("fi # end DNF path")
    assert dnf_end < text.index("# ── Display manager (all OSes)") < block
    assert "\nexit" not in text[dnf_end:block]
    assert 'case "${_TD_OS}" in\n' in locale_block()
