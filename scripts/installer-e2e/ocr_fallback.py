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

import itertools
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
# The accent of the niri frontend ("Install now", "Continue"), measured on
# the karnataka pod run of medium 45822993049: with the COSMIC accent
# alone the walk found no button and stopped on the welcome page.
NIRI_ACCENT = (208, 188, 255)
ACCENTS = (ACCENT, NIRI_ACCENT)


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


def entry_x(rgb, width, y, left, right, min_width=120):
    """The x to click in the outlined entry of the form row at `y`, or None.

    An outlined entry has two vertical border lines: columns whose pixels at
    `y` and 12 rows above and below all differ from the row background (the
    pixel 6 left of the label). Label letters are shorter than that. The
    entry is the first pair of such columns, right of the label at `left` and
    left of `right`, at least `min_width` apart with background between them.
    A maximized niri window puts its entries far left of the forward button
    (pod run on medium 45986432375, usb-2-ocr-06-again.png): a click at a
    fixed offset from that button missed every entry.
    """

    def px(x, row):
        o = (row * width + x) * 3
        return rgb[o], rgb[o + 1], rgb[o + 2]

    bg = px(max(left - 6, 0), y)

    def far(x, row):
        return sum(abs(a - b) for a, b in zip(px(x, row), bg)) > 9

    edge = None
    for x in range(left, min(right, width)):
        if all(far(x, row) for row in (y - 12, y, y + 12)):
            if edge is not None and x - edge >= min_width:
                return edge + 30
            edge = x
        elif far(x, y):
            edge = None
    return None


def accent_button(rgb, width, height, accents=ACCENTS, bottom=715):
    """The center of the lowest solid accent block that has the size of a button, or None.

    `rgb` is the raw screen; `accents` are the accent colors of the
    frontends. The window border and the progress line are accent too, but
    not 50 to 200 pixels wide on six rows; the dock is below `bottom`.
    """

    def is_accent(offset):
        return any(
            all(abs(rgb[offset + c] - accent[c]) <= 12 for c in range(3)) for accent in accents
        )

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


MODHEX = "cbdefghijklnrtuv"
RECOVERY_KEY_RE = re.compile(rf"(?:[{MODHEX}]{{8}}-){{7}}[{MODHEX}]{{8}}")
# What tesseract makes of a key word in the whole-page pass (l is read as 1
# or |): only used to find the lines of the key, never to read it.
_KEY_WORD_RE = re.compile(rf"[{MODHEX}01|-]+")
# Scales of the crop that is read again. Letters of 11 pixels read differently
# at each scale (t, f and l), so the readings vote.
_KEY_SCALES = (2, 3, 4, 5, 6, 8)
# Letters that the readings do not agree on, at most. Each choice is one more
# key to try on the disk.
_KEY_MAX_UNSURE = 4


def _key_rows(found):
    """The lines of the page that hold (part of) a recovery key, top to bottom.

    The page pass of tesseract reads the key badly (run 45925317913 lost two
    groups, run 45836370728 gave the wrapped second line a row of its own)
    but it shows where the lines are. A line that has at least 20 key letters
    and two hyphens holds the key. A line next to it that has only key
    letters (and 8 or more of them) is the wrapped rest."""
    lines = []
    for word in sorted(found, key=lambda w: (w[2], w[1])):
        if lines and abs(lines[-1][0][2] - word[2]) <= 8:
            lines[-1].append(word)
        else:
            lines.append([word])
    lines = [sorted(line, key=lambda w: w[1]) for line in lines]

    def letters(line):
        return sum(len(w[0].replace("-", "")) for w in line)

    def keyish(line):
        return all(_KEY_WORD_RE.fullmatch(w[0].lower()) for w in line)

    seeds = [
        i
        for i, line in enumerate(lines)
        if sum(len(w[0]) for w in line if _KEY_WORD_RE.fullmatch(w[0].lower())) >= 20
        and sum(w[0].count("-") for w in line) >= 2
    ]
    if not seeds:
        return []
    chosen = set(seeds)
    grew = True
    while grew:
        grew = False
        for i, line in enumerate(lines):
            if i in chosen or not keyish(line) or letters(line) < 8:
                continue
            for j in chosen:
                pitch = max(w[4] for w in lines[j]) * 2
                if abs(line[0][2] - lines[j][0][2]) <= pitch:
                    chosen.add(i)
                    grew = True
                    break
    return [lines[i] for i in sorted(chosen)][:4]


def _image_size(png_path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(png_path)],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    width, height = (int(n) for n in out.strip().split(","))
    return width, height


def _key_box(png_path, row, width):
    """(left, right, top, height, dark) of a key line: the ink around the words found.

    The band is as high as the words. The background is the median of the
    band, ink is what differs from it, and the line grows from the words
    while the next ink is within two letters; the window border or a button
    is farther off. `dark` says the background is dark (light letters)."""
    top = max(0, min(w[2] for w in row) - 2)
    height = max(w[2] + w[4] for w in row) + 2 - top
    gray = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(png_path), "-vf",
         f"crop={width}:{height}:0:{top},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout
    lines = [gray[y * width : (y + 1) * width] for y in range(height)]
    left, right = min(w[1] for w in row), max(w[1] + w[3] for w in row)
    inside = sorted(v for line in lines for v in line[left:right])
    background = inside[len(inside) // 2]
    ink = [any(abs(line[x] - background) > 48 for line in lines) for x in range(width)]
    pitch = max(1, sum(w[3] for w in row) // max(1, sum(len(w[0]) for w in row)))
    x, quiet = left, 0
    while x > 0 and quiet <= 2 * pitch:
        x -= 1
        quiet = 0 if ink[x] else quiet + 1
        left = x if ink[x] else left
    x, quiet = right, 0
    while x < width - 1 and quiet <= 2 * pitch:
        x += 1
        quiet = 0 if ink[x] else quiet + 1
        right = x if ink[x] else right
    return max(0, left - 8), min(width, right + 9), top, height, background < 128


def _read_line(png_path, box, scale):
    """One tesseract reading of a line crop, limited to the modhex letters and the hyphen."""
    left, right, top, height, dark = box
    small = f"{png_path}.key.png"
    graph = (
        f"crop={right - left}:{height}:{left}:{top},scale=iw*{scale}:-1:flags=lanczos,"
        f"format=gray{',negate' if dark else ''},pad=iw+40:ih+40:20:20:color=white"
    )
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(png_path), "-vf", graph, small],
            check=True, timeout=60,
        )
        result = subprocess.run(
            ["tesseract", small, "stdout", "--psm", "7", "-c",
             f"tessedit_char_whitelist={MODHEX}-"],
            capture_output=True, text=True, timeout=120, check=False,
        )
    finally:
        Path(small).unlink(missing_ok=True)
    return "".join((result.stdout or "").split())


def recovery_key_candidates(png_path, found=None):
    """The recovery keys a screenshot can show, most likely first; [] when it shows none.

    A systemd recovery key is eight groups of eight modhex letters
    (cbdefghijklnrtuv). The page pass of tesseract drops groups and reads l
    as i (run 45925317913, CD of bonito:cosmic), so it only finds the
    lines. Each line is cropped, enlarged at six scales (light or dark
    letters as the background says) and read again with the letters limited
    to that alphabet. Only readings of the exact shape count. l and i are
    both modhex, so the alphabet cannot tell them apart; the readings vote.
    Where they all agree there is one key. Where they differ in up to four
    letters, every combination of what was read is a candidate, the most
    voted first, and stage 6 tries them on the disk, which is the only
    judge. More doubt than that gives []: unverified, not a guess."""
    if not ocr_available():
        return []
    found = words(png_path) if found is None else found
    rows = _key_rows(found)
    if not rows:
        return []
    width, _ = _image_size(png_path)
    boxes = [_key_box(png_path, row, width) for row in rows]
    readings = []
    for scale in _KEY_SCALES:
        parts = [_read_line(png_path, box, scale) for box in boxes]
        # A key that wraps at a hyphen can come with or without it.
        for text in ("".join(parts), "-".join(p.strip("-") for p in parts)):
            if RECOVERY_KEY_RE.fullmatch(text):
                readings.append(text)
                break
    if not readings:
        return []
    unsure = [i for i in range(len(readings[0])) if len({r[i] for r in readings}) > 1]
    if len(unsure) > _KEY_MAX_UNSURE:
        return []
    candidates = {}
    for combo in itertools.product(*({r[i] for r in readings} for i in unsure)):
        key = list(readings[0])
        votes = 0
        for i, letter in zip(unsure, combo):
            key[i] = letter
            votes += sum(1 for r in readings if r[i] == letter)
        candidates["".join(key)] = votes
    if not unsure:
        return [readings[0]]
    return sorted(candidates, key=lambda k: (-candidates[k], k))


def shows_recovery_key(found):
    """True when one line reads as a recovery key: eight groups of about eight letters.

    tesseract splits the key at its hyphens and reads l as 1."""
    for word in found:
        line = [w for w in found if abs(w[2] - word[2]) <= 8]
        joined = "".join(w[0] for w in sorted(line, key=lambda w: w[1])).lower()
        if re.search(r"(?:[a-z01|]{7,9}-){5,}[a-z01|]{6,9}", joined):
            return True
    return False
