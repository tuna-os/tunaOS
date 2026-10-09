"""tunaOS#3110: the Marlin acceptance screenshot showed the gtkgreet clock
and Username label as dark text directly over the dark TunaOS wallpaper.
The stylesheet targeted ``box#window-box``, but gtkgreet names that GtkBox
``window``; this test holds the real widget selectors and an accessible text to
panel contrast ratio in every TunaOS script that emits the stylesheet.

Falsification: structural — restore the nonexistent ``box#window-box`` selector
or a low-contrast foreground in either script and this test fails.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GREETER_SCRIPTS = (
    ROOT / "build_scripts/desktop/greetd-gtkgreet.sh",
    ROOT / "build_scripts/desktop/xfce-greeter.sh",
)


def _stylesheet(script: Path) -> str:
    text = script.read_text()
    match = re.search(
        r"cat >/etc/greetd/gtkgreet\.css <<'(?P<end>[A-Z_]+)'\n"
        r"(?P<css>.*?)\n(?P=end)$",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"{script}: cannot find the emitted gtkgreet stylesheet"
    return match.group("css")


def _hex_colour(css: str, selector: str, property_name: str) -> str:
    block = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.DOTALL)
    assert block, f"missing gtkgreet selector {selector!r}"
    value = re.search(rf"{re.escape(property_name)}:\s*(#[0-9a-fA-F]{{6}})", block.group("body"))
    assert value, f"{selector!r} does not set {property_name} to an opaque colour"
    return value.group(1)


def _relative_luminance(colour: str) -> float:
    channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    light, dark = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_gtkgreet_clock_and_prompt_have_a_high_contrast_panel():
    for script in GREETER_SCRIPTS:
        css = _stylesheet(script)
        assert "box#window-box" not in css
        panel = _hex_colour(css, "box#window", "background-color")
        text = _hex_colour(css, "box#body label", "color")
        assert "label#clock," in css
        assert _contrast(text, panel) >= 7, f"{script}: gtkgreet text contrast is below WCAG AAA"
