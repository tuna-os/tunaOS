#!/usr/bin/env python3
"""Materialize identity assets for the blocked, opt-in GNOME staging adapter."""
import base64
import hashlib
import importlib.util
import io
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("fork_identity", Path(__file__).resolve().parents[1] / "build_scripts/lib/fork-identity.py")
IDENTITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IDENTITY)


def prepare(branding, cell, directory, source):
    from PIL import Image, ImageDraw, ImageFont
    name = branding.get("name", "")
    if not IDENTITY.valid_name(name) or "logo" not in branding:
        raise ValueError("identity staging needs both name (1..64 ASCII letters/digits/spaces/._-) and logo")
    if cell["flavor"] != "gnome" or cell["routing"]["CONTAINERFILE"] not in (
            "Containerfile.el10", "Containerfile.debian", "Containerfile.ubuntu"):
        raise ValueError("identity staging currently supports only direct RPM/Debian/Ubuntu GNOME")
    path = directory / branding["logo"]
    with path.open("rb") as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    if not 0 < len(data) <= 4 * 1024 * 1024:
        raise ValueError("identity logo must be 1 byte..4 MiB")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
            raise ValueError("identity logo must be a single-frame PNG")
        if not all(1 <= n <= 2048 for n in image.size):
            raise ValueError("identity logo dimensions must be 1..2048 pixels")
        image.load()
        logo = image.convert("RGBA")
    # Pillow's bundled Aileron font is deterministic and needs no network or
    # unreceipted host font. PNG pixels, not font lookups, reach the image.
    try:
        font = ImageFont.load_default(size=48)
    except TypeError as exc:
        raise ValueError("identity staging requires Pillow 10.1+ for its bundled font") from exc
    logo.thumbnail((128, 128))
    width = int(font.getlength(name)) + 160
    lettermark = Image.new("RGBA", (width, 160))
    lettermark.alpha_composite(logo, (0, (160 - logo.height) // 2))
    ImageDraw.Draw(lettermark).text((152, 80), name, font=font, anchor="lm", fill="white")
    lettermark.thumbnail((640, 160))
    assets, blobs = {}, {}
    for kind, image in (("logo", logo), ("lettermark", lettermark)):
        output = io.BytesIO()
        image.save(output, format="PNG")
        png = output.getvalue()
        # Existing desktop consumers use SVG paths. Self-contained raster SVG
        # has no scripts, fonts, remote references or author-supplied XML.
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
               f'width="{image.width}" height="{image.height}" viewBox="0 0 {image.width} {image.height}">'
               f'<image width="{image.width}" height="{image.height}" xlink:href="data:image/png;base64,'
               + base64.b64encode(png).decode("ascii") + '"/></svg>\n').encode()
        digest = hashlib.sha256(svg).hexdigest()
        target = f"fork-identity-assets/{digest}.svg"
        assets[kind] = {"path": target, "sha256": digest}
        if kind == "lettermark":
            png_digest = hashlib.sha256(png).hexdigest()
            png_path = f"fork-identity-assets/{png_digest}.png"
            assets["splash"] = {"path": png_path, "sha256": png_digest}
            blobs[png_path] = png
        blobs[target] = svg
    # Reuse the shipped prompt/keyboard callbacks, including encrypted-root
    # password entry. A logo-only script would hide the unlock prompt.
    script = (Path(__file__).resolve().parents[1] / "system_files/usr/share/plymouth/themes/tunaos/tunaos.script").read_text()
    script = script.replace("FRAME_COUNT = 72;", "FRAME_COUNT = 1;")
    script = script.replace('Image("fish-" + ZeroPad(i) + ".png")', 'Image("splash.png")')
    script = script.replace("# TunaOS Plymouth boot animation", "# Fork Plymouth boot splash")
    script = script.replace("# Displays the TunaOS fish emoji animation centered on a black background.", "# Displays the generated fork lettermark; preserves the stock prompt callbacks.")
    data_script = script.encode()
    digest = hashlib.sha256(data_script).hexdigest()
    path_script = f"fork-identity-assets/{digest}.script"
    assets["splash_script"] = {"path": path_script, "sha256": digest}
    blobs[path_script] = data_script
    manifest = {"schema_version": 1, "status": "staging-only", "name": name,
                "variant": cell["variant"], "flavor": cell["flavor"], "platform": cell["platform"],
                "sources": {"sha256": source}, "logo_input_sha256": hashlib.sha256(data).hexdigest(),
                "assets": assets, "blocked_consumers": IDENTITY.BLOCKERS}
    return manifest, blobs
