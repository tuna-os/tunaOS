"""The niri config TunaOS ships must be KDL niri can parse.

marlin-niri live session (iso-builder run 43548977235, live-serial journal):

    niri: error loading config / error parsing KDL
    found `}` ... config.kdl:42:1
    43 |     default-column-width { fixed 900 }

niri then ignored the config and used its built-in default, so the
`spawn-at-startup "flatpak" "run" "org.tunaos.InstallerNiri"` line the live
adapter seeds was never read and no installer window appeared (waybar only).
KDL 1 needs a `;` before the `}` of a one-line block.

Falsification: restore `default-column-width { fixed 900 }` (no `;`) in
system_files/usr/share/niri/config.kdl and test_one_line_blocks_end_with_a_semicolon
fails; with the python `kdl` package installed test_the_shipped_config_parses
fails too.
"""
import re
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[1] / 'system_files/usr/share/niri/config.kdl'


def test_one_line_blocks_end_with_a_semicolon():
    bad = [(n, line) for n, line in enumerate(CONFIG.read_text().splitlines(), 1)
           if re.search(r'\{[^{}]*[^;{}\s]\s*\}\s*$', line) and not line.lstrip().startswith('//')]
    assert not bad, f'one-line KDL blocks need a ; before the }}: {bad}'


def test_no_unknown_top_level_preferred_scale():
    # niri has no top-level preferred-scale node; scale lives under `output`.
    assert not re.search(r'^preferred-scale\b', CONFIG.read_text(), re.M)


def test_the_shipped_config_parses():
    kdl = pytest.importorskip('kdl')
    kdl.parse(CONFIG.read_text())
