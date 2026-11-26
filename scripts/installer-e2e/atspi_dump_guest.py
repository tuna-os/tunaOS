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


def find_apps(atspi, substr):
    """Applications on the AT-SPI desktop whose name has SUBSTR."""
    desktop = atspi.get_desktop(0)
    found = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        with contextlib.suppress(Exception):
            name = (app.get_name() or "").lower()
            if substr in name:
                found.append(app)
    return found


def press(atspi, substr, path):
    """Run the first action of the node at PATH (as `dump` printed it).

    On a Wayland session the extents of a node are not screen coordinates
    (the first real run got [0, 0, 42, 42] for the Next button, run
    45594835162), so a pointer click from the host cannot hit it. The
    action interface needs no coordinates.
    """
    apps = find_apps(atspi, substr)
    if not apps:
        print(f"press: no application matches {substr!r}", file=sys.stderr)
        return 1
    node = node_at(apps[0], path)
    if node is None:
        print(f"press: no node at {path}", file=sys.stderr)
        return 1
    action = node.get_action_iface()
    names = []
    if action is not None:
        names = [(action.get_action_name(i) or "").lower() for i in range(action.get_n_actions())]
    if not names:
        print(f"press: the node at {path} has no action", file=sys.stderr)
        return 1
    # Qt lists SetFocus next to Press and Toggle, in no fixed order; the first
    # action is the answer only when no name says what it does.
    index = next((i for w in ("press", "click", "activate", "toggle")
                  for i, name in enumerate(names) if w in name), 0)
    return 0 if action.do_action(index) else 1


def node_at(app, path):
    """The node at PATH of the application, or None."""
    node = app
    for index in path.split(".")[1:]:
        node = node.get_child_at_index(int(index))
        if node is None:
            return None
    return node


def focus(atspi, substr, path):
    """Give the node at PATH the keyboard focus, for a key event from the host."""
    apps = find_apps(atspi, substr)
    node = node_at(apps[0], path) if apps else None
    component = node.get_component_iface() if node is not None else None
    if component is None or not component.grab_focus():
        print(f"focus: the node at {path} takes no focus", file=sys.stderr)
        return 1
    return 0


def set_text(atspi, substr, path, text):
    """Replace the text of the entry at PATH."""
    apps = find_apps(atspi, substr)
    node = node_at(apps[0], path) if apps else None
    editable = node.get_editable_text_iface() if node is not None else None
    if editable is None or not editable.set_text_contents(text):
        print(f"settext: the node at {path} takes no text", file=sys.stderr)
        return 1
    return 0


def select(atspi, substr, path):
    """Select the list row at PATH through the selection of its parent.

    A GTK3 list row has no action: io.elementary.initial-setup keeps
    "Select" off until a row of its list is selected.
    """
    apps = find_apps(atspi, substr)
    parent_path, _, index = path.rpartition(".")
    parent = node_at(apps[0], parent_path) if apps and parent_path else None
    selection = parent.get_selection_iface() if parent is not None else None
    if selection is None or not selection.select_child(int(index)):
        print(f"select: the node at {path} cannot be selected", file=sys.stderr)
        return 1
    return 0


def main(argv):
    words = {"dump": 3, "press": 4, "focus": 4, "settext": 5, "select": 4}
    if len(argv) < 2 or len(argv) < words.get(argv[1], sys.maxsize):
        print(
            f"usage: {argv[0]} dump APP | press APP PATH | focus APP PATH | settext APP PATH TEXT | select APP PATH",
            file=sys.stderr,
        )
        return 2
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    substr = argv[2].lower()
    if argv[1] == "press":
        return press(Atspi, substr, argv[3])
    if argv[1] == "focus":
        return focus(Atspi, substr, argv[3])
    if argv[1] == "settext":
        return set_text(Atspi, substr, argv[3], argv[4])
    if argv[1] == "select":
        return select(Atspi, substr, argv[3])
    # Only the first application: `press` resolves a path in that one.
    found = find_apps(Atspi, substr)[:1]
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


def description_of(node):
    with contextlib.suppress(Exception):
        return node.get_description() or ""
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
            "description": description_of(node),
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
