"""QEMU-key plus OCR fallback for toolkits without AT-SPI (tunaOS#4910).

niri (Quickshell) and cosmic (libcosmic accesskit) expose no tested AT-SPI
tree, so driver.py cannot match there. This module falls back to what
scripts/installer-walkthrough.py does: drive focus with QEMU keys and read
the screen with tesseract OCR. It stays standalone: walkthrough.py runs its
walk on import, so nothing here imports it.

The fallback never replaces a matcher; the harness records which path each
cell used, per the shared/flow test contract ("record that" rule 6).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

# QEMU HMP sendkey steps per installer page, escalated like the walkthrough:
# try the default action first, then sweep focus outward. Space activates a
# focused button in both GTK and Qt when Return does not fire it.
FALLBACK_KEYS = {
    "welcome": ("ret", "spc"),
    "disk": ("tab", "tab", "tab", "spc"),
    "confirm": ("tab", "ret"),
    "progress": (),
    "recovery-key": ("tab", "spc"),
    "done": ("ret",),
}

OCR_MIN_WORD_CHARS = 8


def ocr_available():
    """True when tesseract is installed for the OCR fallback path."""
    return shutil.which("tesseract") is not None


def ocr_text(png_path, psm="11"):
    """OCR one screenshot; empty string when tesseract is missing."""
    if not ocr_available():
        return ""
    result = subprocess.run(
        ["tesseract", str(png_path), "stdout", "--psm", psm],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return (result.stdout or "").lower()


def readable(text):
    """True when OCR output holds words, not line noise (walkthrough rule)."""
    words = [
        w
        for w in "".join(c if c.isalpha() else " " for c in (text or "").lower()).split()
        if len(w) >= 3
    ]
    return sum(len(w) for w in words) >= OCR_MIN_WORD_CHARS


def keys_for(page_id):
    """HMP sendkey steps for one page id, empty tuple when unknown."""
    return FALLBACK_KEYS.get(page_id, ())


def classify_text(text):
    """The installer page from OCR words. Failure still beats done."""
    from atspi_match import Page

    lowered = (text or "").lower()
    if "installation failed" in lowered or "error during installation" in lowered:
        return Page.FAILURE
    if "recovery key" in lowered:
        return Page.RECOVERY_KEY
    if (
        " is installed" in lowered
        or "restart now to complete the installation" in lowered
        or "restart system" in lowered
        or ("finished!" in lowered and "reboot now" in lowered)
    ):
        return Page.COMPLETE
    if "confirm installation" in lowered:
        return Page.INSTALL_CONFIRMATION
    if "installing" in lowered:
        return Page.PROGRESS
    return Page.WAIT


# The step counter in the header of the native frontends, as OCR reads it: the
# middle dot comes out as "-", "." or "*".
STEP_RE = re.compile(r"step\s+(\d+)\s+of\s+(\d+)\s*\W+\s*([a-z][a-z ]+)", re.IGNORECASE)
# The accent of the default COSMIC theme, measured on run 45624842877. The
# forward button is the only solid accent block of its size; tesseract does
# not read its label (dark text on the accent).
ACCENT = (99, 208, 223)


def words(png_path, scale=2):
    """OCR words with their boxes in screen pixels: [(text, x, y, w, h)]."""
    big = f"{png_path}.ocr.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(png_path), "-vf",
         f"scale=iw*{scale}:-1:flags=lanczos,negate", big],
        check=True, timeout=120,
    )
    result = subprocess.run(
        ["tesseract", big, "stdout", "--psm", "11", "tsv"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    Path(big).unlink(missing_ok=True)
    return parse_tsv(result.stdout, scale)


def parse_tsv(text, scale=2):
    """The words of a tesseract TSV above the noise, boxes divided by `scale`."""
    out = []
    for line in (text or "").splitlines()[1:]:
        cells = line.split("\t")
        if len(cells) < 12 or not cells[11].strip() or float(cells[10]) < 30:
            continue
        x, y, w, h = (int(c) // scale for c in cells[6:10])
        out.append((cells[11].strip(), x, y, w, h))
    return out


def page_text(found):
    """The words of a page in reading order, in lower case."""
    return " ".join(w[0] for w in found).lower()


def step_name(found):
    """The step in the header ("account"), or "". Only the header line counts."""
    for word in found:
        if word[0].lower() != "step":
            continue
        line = [w for w in found if abs(w[2] - word[2]) <= 8 and 0 <= w[1] - word[1] < 400]
        match = STEP_RE.search(" ".join(w[0] for w in sorted(line, key=lambda w: w[1])))
        if match:
            return match.group(3).strip().lower()
    return ""


def label_at(found, *label):
    """The vertical center and left edge of the first place where `label` is, or None."""
    want = [part.lower() for part in label]
    for i, word in enumerate(found):
        run = found[i : i + len(want)]
        before = found[i - 1] if i else ("", 0, -100, 0, 0)
        # "Password" is not the second word of "Confirm password".
        if before[0].lower() == "confirm" and abs(before[2] - word[2]) <= 8:
            continue
        if [w[0].lower() for w in run] == want and all(abs(w[2] - word[2]) <= 8 for w in run):
            return word[2] + word[4] // 2, word[1]
    return None


def accent_button(rgb, width, height, accent=ACCENT, bottom=715):
    """The center of the lowest solid accent block that has the size of a button, or None.

    `rgb` is the raw screen. The window border and the progress line are
    accent too, but not 50 to 200 pixels wide on six rows; the dock is below
    `bottom`.
    """

    def is_accent(offset):
        return all(abs(rgb[offset + c] - accent[c]) <= 12 for c in range(3))

    groups = []
    for y in range(0, min(bottom, height)):
        x = 0
        while x < width:
            if not is_accent((y * width + x) * 3):
                x += 1
                continue
            start = x
            while x < width and is_accent((y * width + x) * 3):
                x += 1
            if not 50 <= x - start <= 200:
                continue
            center = (start + x) // 2
            for group in groups:
                if y - group["bottom"] <= 24 and abs(center - group["x"]) <= 12:
                    group["bottom"], group["rows"] = y, group["rows"] + 1
                    break
            else:
                groups.append({"x": center, "top": y, "bottom": y, "rows": 1})
    buttons = [g for g in groups if g["rows"] >= 6 and g["bottom"] - g["top"] >= 18]
    if not buttons:
        return None
    best = max(buttons, key=lambda g: g["bottom"])
    return best["x"], (best["top"] + best["bottom"]) // 2


def raw_rgb(png_path):
    """The pixels of a screenshot as RGB bytes."""
    return subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(png_path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout
