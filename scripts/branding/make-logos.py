#!/usr/bin/env python3
"""Write each variant's mark from its `emoji` in tunaos.toml.

    scripts/branding/make-logos.py [--output DIR]

The mark is the variant's Noto Emoji (Apache License 2.0), copied from
scripts/branding/emoji/<codepoints>.svg with an attribution header. Writes
system_files/usr/share/tunaos/logos/<variant>.svg; 90-image-info.sh installs it
as the os-release LOGO and the lettermarks embed it. Standard library only.

A fork that picks a new emoji adds that emoji's Noto SVG to
scripts/branding/emoji/ (https://github.com/googlefonts/noto-emoji, svg/).
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EMOJI = REPO / "scripts/branding/emoji"
OUT = REPO / "system_files/usr/share/tunaos/logos"
VS16 = 0xFE0F  # emoji presentation selector; Noto file names omit it

_spec = importlib.util.spec_from_file_location("tunaos_config", REPO / "scripts/lib/tunaos_config.py")
tunaos_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tunaos_config)


def codepoints(emoji):
    return [ord(c) for c in emoji if ord(c) != VS16]


def logo(variant, emoji):
    points = codepoints(emoji)
    source = EMOJI / ("_".join(f"{p:x}" for p in points) + ".svg")
    if not source.is_file():
        raise SystemExit(f"{variant}: no Noto Emoji SVG for {emoji!r} at {source.relative_to(REPO)}; "
                         "add it from https://github.com/googlefonts/noto-emoji (svg/)")
    # Noto ships some files as ISO-8859-1 with an editor comment; keep the
    # drawing, replace the prologue with UTF-8 and our attribution.
    body = re.sub(r"\A<\?xml[^>]*\?>\s*(?:<!--[\s\S]*?-->\s*)*", "", source.read_text(encoding="iso-8859-1"))
    if not body.endswith("\n"):
        body += "\n"
    marks = "+".join(f"U+{p:04X}" for p in points)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            f"<!-- {marks} from Noto Emoji (https://github.com/googlefonts/noto-emoji), "
            f"Apache License 2.0. TunaOS mark for {variant}. -->\n" + body)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for variant, settings in tunaos_config.load(REPO / "tunaos.toml")["variants"].items():
        (args.output / f"{variant}.svg").write_text(logo(variant, settings["emoji"]), encoding="utf-8")
        print(variant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
