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

import shutil
import subprocess

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
