#!/usr/bin/env python3
"""Build a TunaOS Plymouth theme from a Noto Emoji.

    scripts/branding/make-plymouth-theme.py <theme> <Title> <codepoint>

Fetches Noto's animated GIF for the codepoint (every frame, 200x200 RGBA
PNGs), or its static PNG when Noto has no animation, and writes
system_files/usr/share/plymouth/themes/<theme>/ with a script copied from the
rocket theme. That is how the existing themes were made (38068874). Needs
Pillow and network access; the output is committed, builds never run this.
"""

import io
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageSequence

REPO = Path(__file__).resolve().parents[2]
THEMES = REPO / "system_files/usr/share/plymouth/themes"
TEMPLATE = THEMES / "rocket"
SIZE = 200
NOTO = "https://fonts.gstatic.com/s/e/notoemoji/latest/{cp}/512.{ext}"


def fetch(cp, ext):
    try:
        with urllib.request.urlopen(NOTO.format(cp=cp, ext=ext), timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def frames(cp):
    gif = fetch(cp, "gif")
    if gif:
        img = Image.open(io.BytesIO(gif))
        return [f.convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS) for f in ImageSequence.Iterator(img)]
    png = fetch(cp, "png")
    if not png:
        sys.exit(f"Noto has neither a GIF nor a PNG for {cp}")
    return [Image.open(io.BytesIO(png)).convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)]


def main():
    theme, title, cp = sys.argv[1:4]
    out = THEMES / theme
    out.mkdir(parents=True, exist_ok=True)
    imgs = frames(cp)
    for i, im in enumerate(imgs, 1):
        im.save(out / f"{theme}-{i:04d}.png", optimize=True)

    script = (TEMPLATE / "rocket.script").read_text()
    script = script.replace("Rocket emoji", f"{title} emoji")
    script = re.sub(r"FRAME_COUNT = \d+;", f"FRAME_COUNT = {len(imgs)};", script)
    script = re.sub(r"FRAME_RATE  = \d+;", f"FRAME_RATE  = {2 if len(imgs) > 1 else 1};", script)
    script = script.replace('Image("rocket-"', f'Image("{theme}-"')
    (out / f"{theme}.script").write_text(script)

    (out / f"{theme}.plymouth").write_text(
        f"""[Plymouth Theme]
Name=TunaOS {title}
Description=TunaOS boot animation ({title})
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/{theme}
ScriptFile=/usr/share/plymouth/themes/{theme}/{theme}.script
"""
    )
    print(f"{theme}: {len(imgs)} frame(s)")


if __name__ == "__main__":
    main()
