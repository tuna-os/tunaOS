"""Frontend-neutral AT-SPI matchers for the image-installer e2e (tunaOS#4910).

Rules ported from Utah's raw_e2e.py (projectbluefin/utah#1437) and the test
contract in tuna-os/installer shared/flow/README.md (PR #447):

1. Dump the tree inside the guest, click from the host. This module only
   matches; scripts/qmp_input.py builds the host-side click events.
2. One name can belong to many nodes. Qualify press targets by role AND
   sensitive, and prefer the node in the topmost dialog.
3. The recovery key is a label whose name IS the key. Match it by shape
   (8 groups of 8 letters), never by a node named "Recovery Key".
4. Classify the page from its text on every poll. Test for failure before
   done. Never use fixed click lists.
5. glib renders sizes with a non-breaking space. Normalise NBSP (U+00A0)
   and narrow NBSP (U+202F) before every comparison.

Where a toolkit has no AT-SPI (niri, cosmic), driver.py falls back to QEMU
key events and OCR, as scripts/installer-walkthrough.py does.
"""

from __future__ import annotations

import re
from enum import Enum

# The recovery key shape from shared/flow/screens.yaml: a text label whose
# value is the key, "8 groups of 8 letters".
RECOVERY_KEY_RE = re.compile(r"\b(?:[a-z]{8}-){7}[a-z]{8}\b", re.IGNORECASE)

DIALOG_ROLES = ("dialog", "window", "frame")
PRESS_ROLES = ("push button", "button")


class Page(Enum):
    """The page the installer shows, from its accessible text only."""

    WAIT = "waiting"
    NEXT = "next"
    DISK = "disk"
    DISK_CONFIRMATION = "disk-confirmation"
    INSTALL_CONFIRMATION = "install-confirmation"
    PROGRESS = "progress"
    RECOVERY_KEY = "recovery-key"
    COMPLETE = "complete"
    FAILURE = "failure"


def canon_space(text):
    """Plain spaces for glib's NBSP size formatting (Utah canon_space)."""
    return (text or "").replace("\u00a0", " ").replace("\u202f", " ")


def norm(text):
    """Case-folded name match: mnemonics ("_Next") never block a match."""
    return (text or "").replace("_", "").strip().lower()


def is_sensitive(node):
    """True when AT-SPI reports the node sensitive (clickable now)."""
    return "sensitive" in node.get("states", [])


def is_showing(node):
    """True when AT-SPI reports the node showing on screen."""
    return "showing" in node.get("states", [])


def text_of(node):
    """Every user-facing word on the node, normalised for comparison."""
    return canon_space(f"{node.get('name', '')} {node.get('text', '')}")


def dialog_depth(node, by_path):
    """Depth of the nearest ancestor dialog, or -1 when the node is in none."""
    parts = node.get("path", "").split(".")
    depth = -1
    for i in range(1, len(parts)):
        ancestor = by_path.get(".".join(parts[:i]))
        if ancestor and ancestor.get("role") in DIALOG_ROLES:
            depth = i
    return depth


def topmost_first(nodes):
    """Nodes in the topmost dialog first; the QR dialog beats the page."""
    by_path = {n["path"]: n for n in nodes if n.get("path")}
    return sorted(nodes, key=lambda n: dialog_depth(n, by_path), reverse=True)


def qualify(nodes, name, role=None, sensitive=True):
    """The node named `name`, qualified by role AND sensitivity.

    Several nodes can share a name (recovery page: a panel, a button and a
    label are all "Done"). A sensitive panel must never stand in for a
    still-insensitive button, so press targets pass a button role and keep
    sensitive=True. The topmost dialog wins: its nodes come first.
    """
    want = norm(name)
    for node in topmost_first(nodes):
        if role is not None and node.get("role") != role:
            continue
        got = norm(node.get("name", ""))
        match = want[1:] in got if want.startswith("~") else got == want
        if match and (not sensitive or is_sensitive(node)):
            return node
    return None


def has_text(nodes, text):
    """True when any node's name or text contains `text` (spacing-safe)."""
    want = canon_space(text).lower()
    return any(want in text_of(n).lower() for n in nodes)


def find_recovery_key(nodes):
    """The label whose value matches the recovery-key shape, or None."""
    for node in nodes:
        if node.get("role") == "label" and RECOVERY_KEY_RE.search(text_of(node)):
            return node
    return None


def classify_page(nodes):
    """The page from its accessible text. Failure always beats done."""
    text = "\n".join(norm(n.get("name", "")) for n in nodes)
    failed = (
        "installation failed" in text
        or "error during installation" in text
        or ("recovery key" in text and "failed" in text)
    )
    if failed:
        return Page.FAILURE
    if find_recovery_key(nodes) is not None or "recovery key" in text:
        return Page.RECOVERY_KEY
    if (
        " is installed" in text
        or "restart now to complete the installation" in text
        or "restart system" in text
        or ("finished!" in text and "reboot now" in text)
    ):
        return Page.COMPLETE
    if "confirm installation" in text:
        return Page.INSTALL_CONFIRMATION
    if "confirm changes" in text:
        return Page.DISK_CONFIRMATION
    if "install location" in text or ("select" in text and "disk" in text):
        return Page.DISK
    if "installing" in text or ("copying" in text and "files" in text):
        return Page.PROGRESS
    if any(norm(n.get("name", "")) == "next" for n in nodes):
        return Page.NEXT
    return Page.WAIT
