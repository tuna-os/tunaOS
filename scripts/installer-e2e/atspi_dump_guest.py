#!/usr/bin/env python3
"""Dump one app's AT-SPI tree as JSON. Runs INSIDE the guest session.

Usage: python3 atspi_dump_guest.py dump <app-substring>

Reads the GTK/Qt/libcosmic app's accessibility tree from the live session
bus and prints one JSON list: each node has name, role, states, text, ext
(x, y, w, h) and path. The host (driver.py) matches nodes and clicks over
QMP. Follows Utah iso/raw/atspi_drive.py; needs python3-gi in the medium.
"""

import contextlib
import json
import sys

MAX_NODES = 4000
STATES = (
    "SHOWING",
    "VISIBLE",
    "SENSITIVE",
    "FOCUSABLE",
    "FOCUSED",
    "CHECKED",
    "EDITABLE",
    "SELECTED",
    "ENABLED",
    "ACTIVE",
)


def main(argv):
    if len(argv) < 3 or argv[1] != "dump":
        print(f"usage: {argv[0]} dump <app-substring>", file=sys.stderr)
        return 2
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    substr = argv[2].lower()
    desktop = Atspi.get_desktop(0)
    found = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        with contextlib.suppress(Exception):
            name = (app.get_name() or "").lower()
            if substr in name:
                found.append(app)
    if not found:
        print(json.dumps([]))
        return 0

    out = []
    for app in found:
        walk(app, out, Atspi)
        if len(out) >= MAX_NODES:
            break
    print(json.dumps(out[:MAX_NODES]))
    return 0


def states_of(node, atspi):
    with contextlib.suppress(Exception):
        state_set = node.get_state_set()
        return [s.lower() for s in STATES if state_set.contains(getattr(atspi.StateType, s))]
    return []


def text_of(node):
    with contextlib.suppress(Exception):
        iface = node.get_text_iface()
        if iface:
            return iface.get_all_text() or ""
    return ""


def walk(node, out, atspi, path="0", depth=0):
    if depth > 30 or len(out) >= MAX_NODES:
        return
    role = None
    with contextlib.suppress(Exception):
        role = node.get_role_name()
    if role is None:
        return
    extents = None
    with contextlib.suppress(Exception):
        ext = node.get_extents(0)
        extents = [ext.x, ext.y, ext.width, ext.height]
    name = ""
    with contextlib.suppress(Exception):
        name = node.get_name() or ""
    out.append(
        {
            "name": name,
            "role": role,
            "states": states_of(node, atspi),
            "text": text_of(node),
            "ext": extents,
            "path": path,
        }
    )
    count = 0
    with contextlib.suppress(Exception):
        count = node.get_child_count()
    for i in range(count):
        with contextlib.suppress(Exception):
            walk(node.get_child_at_index(i), out, atspi, f"{path}.{i}", depth + 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
