#!/usr/bin/env python3
"""Render each variant's name as a two-tone ASCII lettermark for fastfetch.

    scripts/branding/make-fastfetch-logos.py

Writes system_files/usr/share/tunaos/fastfetch/<variant>.txt. The letters (█)
are colour $1, the variant's accent; the shading (╗║╚═...) is $2, a dim grey.
90-image-info.sh points fastfetch at the variant's file. Needs pyfiglet; the
output is committed, builds never run this.

The name is the one os-release shows (PRETTY_NAME): bonito-rawhide publishes
as bonito and flounder-sid as flounder, so they share a word and differ in
colour.
"""

from pathlib import Path

import pyfiglet

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "system_files/usr/share/tunaos/fastfetch"
TSV = REPO / "build_scripts/lib/variant-identity.tsv"
MAX_WIDTH = 76  # fit an 80-column terminal with fastfetch's padding
SHADE = set("╗╔╝╚║═")

DISPLAY = {"bonito-rawhide": "Bonito", "flounder-sid": "Flounder"}
# Too wide for one line in any block font: stack it.
STACK = {"hummingbird": ["Humming", "bird"]}


def render(word):
    for font in ("ansi_shadow", "ansi_regular"):
        art = pyfiglet.figlet_format(word, font=font, width=400)
        lines = [l.rstrip() for l in art.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        if max(len(l) for l in lines) <= MAX_WIDTH:
            return lines
    return lines


def two_tone(line):
    out, cur = [], None
    for ch in line:
        tone = "$2" if ch in SHADE else "$1" if ch != " " else cur
        if tone != cur and ch != " ":
            out.append(tone)
            cur = tone
        out.append(ch)
    return "".join(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for row in TSV.read_text().splitlines():
        if not row or row.startswith("#"):
            continue
        vid = row.split("\t")[0]
        word = DISPLAY.get(vid, vid.capitalize())
        if vid in STACK:
            lines = [l for part in STACK[vid] for l in render(part)]
        else:
            lines = render(word)
        (OUT / f"{vid}.txt").write_text("\n".join(two_tone(l) for l in lines) + "\n")
        print(f"{vid}: {word} ({max(len(l) for l in lines)} cols)")


if __name__ == "__main__":
    main()
