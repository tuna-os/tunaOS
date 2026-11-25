"""tunaOS#4090: the encrypted-boot passphrase prompt must be able to render.

Measured defect (PR #4296): every shipped plymouth script theme failed to
parse (`local name;` is not plymouth script syntax), and the EL10 initramfs
had no `fc-match`, so label-freetype opened no font. Either one leaves the
LUKS prompt invisible on the display.

Falsification: structural -- re-adding a bare `local x;` declaration to any
theme script, or dropping the fc-match drop-in from plymouth-set-theme.sh,
fails this test.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THEMES = ROOT / "system_files" / "usr" / "share" / "plymouth" / "themes"
SET_THEME = (ROOT / "build_scripts" / "plymouth-set-theme.sh").read_text(encoding="utf-8")

LOCAL_DECL = re.compile(r"^\s*local\b", re.MULTILINE)


def _scripts():
    found = sorted(THEMES.glob("*/*.script"))
    assert found, "no plymouth theme scripts found; the test would pass vacuously"
    return found


def test_no_theme_script_uses_the_unsupported_local_declaration():
    offenders = [
        str(p.relative_to(ROOT)) for p in _scripts() if LOCAL_DECL.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"plymouth script has no `local`; parser rejects: {offenders}"


def test_initramfs_gets_fc_match_and_fonts_conf_for_the_prompt_label():
    assert "45-tunaos-plymouth-fonts.conf" in SET_THEME
    assert 'install_items+=" /usr/bin/fc-match /etc/fonts/fonts.conf "' in SET_THEME
