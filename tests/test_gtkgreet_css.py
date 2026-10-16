"""The gtkgreet stylesheets must select widgets gtkgreet actually names.

gtkgreet 0.8 names its login box "window" (window.c:
gtk_widget_set_name(ctx->window_box, "window")). A rule for any other name
never applies: the clock and prompts then sit unframed on the wallpaper in
the theme's dark text (tunaOS#3110).
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GTKGREET_WIDGET_NAMES = {"window", "clock", "body", "input-field", "command-selector"}


def stylesheet(script):
    text = (ROOT / "build_scripts/desktop" / script).read_text()
    return re.search(r"cat >/etc/greetd/gtkgreet\.css <<'(\w+)'\n(.*?)\n\1\n", text, re.S).group(2)


def test_gtkgreet_stylesheets_frame_the_named_login_box():
    for script in ("greetd-gtkgreet.sh", "xfce-greeter.sh"):
        css = stylesheet(script)
        assert re.search(r"^box#window \{[^}]*background-color:", css, re.M), script
        selectors = re.findall(r"^([^{}\n]+)\{", re.sub(r"/\*.*?\*/", "", css, flags=re.S), re.M)
        names = {name for selector in selectors for name in re.findall(r"#([\w-]+)", selector)}
        assert names <= GTKGREET_WIDGET_NAMES, f"{script} styles unknown gtkgreet widgets {names - GTKGREET_WIDGET_NAMES}"
