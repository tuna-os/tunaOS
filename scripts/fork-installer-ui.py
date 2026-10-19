#!/usr/bin/env python3
"""Read-only accessibility observations plus real QMP pointer/keyboard input.

No widget setters, accessibility actions, demo variables, or autoinstall API.
Password fields are identified by role/focus; their text is never read.
"""

import re
import time

# Executed as the already authenticated desktop user. Atspi is the platform's
# normal accessibility observer, not a process injection or application test API.
SNAPSHOT = r"""
import json
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
Atspi.set_timeout(1500, 3000)
allowed = __PIDS__
rows = []
seen = set()
root = Atspi.get_desktop(0)
def visit(node, parent, depth):
    if depth > 24 or len(rows) >= 1800:
        raise ValueError("accessibility tree exceeds bound")
    pid = node.get_process_id()
    if pid not in allowed:
        return
    key = len(rows)
    role = node.get_role_name().casefold()
    state = node.get_state_set()
    states = {label: state.contains(value) for label, value in (
        ("showing", Atspi.StateType.SHOWING), ("visible", Atspi.StateType.VISIBLE),
        ("enabled", Atspi.StateType.ENABLED), ("sensitive", Atspi.StateType.SENSITIVE),
        ("focused", Atspi.StateType.FOCUSED), ("checked", Atspi.StateType.CHECKED))}
    name = node.get_name() or ""
    # Names label controls. Never call Atspi.Text or EditableText: those expose
    # values and would make secret entry part of the observation surface.
    if len(name) > 512:
        name = "<long accessible name omitted>"
    bounds = None
    try:
        box = node.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
        bounds = [box.x, box.y, box.width, box.height]
    except Exception:
        pass
    rows.append({"id": key, "parent": parent, "pid": pid, "role": role,
                 "name": name, "states": states, "bounds": bounds})
    count = node.get_child_count()
    if count > 1800:
        raise ValueError("accessibility child count exceeds bound")
    for index in range(count):
        child = node.get_child_at_index(index)
        if child is not None:
            visit(child, key, depth + 1)
for index in range(root.get_child_count()):
    app = root.get_child_at_index(index)
    if app is not None and app.get_process_id() in allowed:
        visit(app, None, 0)
print(json.dumps({"schema_version": 1, "nodes": rows}))
"""


def select(snapshot, name, roles, *, focused=False):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ValueError("invalid accessibility observation")
    candidates = [
        node
        for node in snapshot.get("nodes", [])
        if node.get("name", "").casefold() == name.casefold()
        and node.get("role") in roles
        and all(
            node.get("states", {}).get(k) is True
            for k in ("visible", "showing", "enabled", "sensitive")
        )
        and (not focused or node["states"].get("focused") is True)
    ]
    if len(candidates) != 1:
        raise ValueError("expected one visible enabled " + name + " control")
    return candidates[0]


def rect(node, size):
    box = node.get("bounds")
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(type(v) is not int for v in box)
        or box[2] <= 0
        or box[3] <= 0
        or box[0] < 0
        or box[1] < 0
        or box[0] + box[2] > size[0]
        or box[1] + box[3] > size[1]
    ):
        raise ValueError("control is outside the visible framebuffer")
    return box


def phrase_rows(rows, phrase):
    """Exact consecutive OCR tokens, not substring/fuzzy matching."""
    normalize = lambda word: re.sub(r"[^a-z0-9/]", "", word.casefold())
    wanted = [normalize(word) for word in phrase.split()]
    lines = {}
    for row in rows:
        key = tuple(row.get(k) for k in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(row)
    matches = []
    for line in lines.values():
        tokens = [normalize(row["text"]) for row in line]
        for start in range(len(tokens) - len(wanted) + 1):
            if tokens[start : start + len(wanted)] == wanted:
                matches.append(line[start : start + len(wanted)])
    return matches


def visible_label(node, rows, phrase, size):
    x, y, w, h = rect(node, size)
    matches = phrase_rows(rows, phrase)
    found = []
    for match in matches:
        cx = (
            min(int(r["left"]) for r in match)
            + max(int(r["left"]) + int(r["width"]) for r in match)
        ) / 2
        cy = (
            min(int(r["top"]) for r in match) + max(int(r["top"]) + int(r["height"]) for r in match)
        ) / 2
        if x <= cx <= x + w and y <= cy <= y + h:
            found.append((cx, cy))
    if len(found) != 1:
        raise ValueError("accessibility control is not paired with its visible text")
    return found[0]


class UI:
    def __init__(self, qmp, screenshot, snapshot, words):
        self.qmp, self.screenshot, self.snapshot, self.words = qmp, screenshot, snapshot, words
        self.counter = 0

    def capture(self, label):
        from PIL import Image

        self.counter += 1
        frame = self.screenshot(f"ui-{self.counter:03d}-{label}.png")
        with Image.open(frame) as image:
            size = image.size
        return frame, size, self.words(frame), self.snapshot()

    def click(self, name, roles=("push button",), *, label=None):
        _, size, words, snapshot = self.capture("control")
        node = select(snapshot, name, roles)
        point = visible_label(node, words, label or name, size)
        self.point(point, size)
        return {"name": name, "role": node["role"], "pid": node["pid"], "bounds": node["bounds"]}

    def point(self, point, size):
        x, y = point
        if not (0 <= x < size[0] and 0 <= y < size[1]):
            raise ValueError("pointer target is out of bounds")
        self.qmp.execute(
            "input-send-event",
            {
                "events": [
                    {
                        "type": "abs",
                        "data": {"axis": "x", "value": round(x * 32767 / (size[0] - 1))},
                    },
                    {
                        "type": "abs",
                        "data": {"axis": "y", "value": round(y * 32767 / (size[1] - 1))},
                    },
                    {"type": "btn", "data": {"down": True, "button": "left"}},
                ]
            },
        )
        self.qmp.execute(
            "input-send-event",
            {"events": [{"type": "btn", "data": {"down": False, "button": "left"}}]},
        )
        time.sleep(0.5)

    def field(self, name, value, *, secret=False):
        roles = ("password text",) if secret else ("text", "entry")
        # Entry coordinates need not contain their label on all GTK versions;
        # click its checked center, then independently prove actual input focus.
        _, size, _, snapshot = self.capture("field")
        node = select(snapshot, name, roles)
        x, y, w, h = rect(node, size)
        self.point((x + w / 2, y + h / 2), size)
        focused = select(self.snapshot(), name, roles, focused=True)
        if focused["pid"] != node["pid"]:
            raise ValueError("input focus moved to another application")
        self.qmp.key("ctrl", "a")
        self.qmp.type(value)
        # Never read field text, and never return the supplied value.
        return {"name": name, "role": node["role"], "typed": True, "secret": secret}

    def toggle_off(self, name):
        _, size, words, snapshot = self.capture("encryption")
        # Adw.ActionRow associates its title with the suffix Gtk.Switch. Both
        # must be visible in the same row before touching the switch.
        node = select(snapshot, name, ("check box", "toggle button", "switch"))
        x, y, w, h = rect(node, size)
        matches = phrase_rows(words, name)
        aligned = [
            rows for rows in matches if all(y - h <= int(row["top"]) <= y + 2 * h for row in rows)
        ]
        if len(aligned) != 1 or node["states"].get("checked") is not True:
            raise ValueError("expected checked encryption switch with visible row label")
        self.point((x + w / 2, y + h / 2), size)
        changed = select(self.snapshot(), name, ("check box", "toggle button", "switch"))
        if changed["pid"] != node["pid"] or changed["states"].get("checked") is not False:
            raise ValueError("native encryption switch did not turn off")
        return {"name": name, "checked_before": True, "checked_after": False}

    def authenticate(self, password, shell_pid):
        frame, size, words, snapshot = self.capture("polkit-password")
        if not phrase_rows(words, "Authentication Required") or not phrase_rows(words, "canary"):
            raise ValueError(
                "native polkit dialog does not visibly identify the synthetic administrator"
            )
        entries = [
            node
            for node in snapshot["nodes"]
            if node.get("pid") == shell_pid
            and node.get("role") == "password text"
            and all(
                node.get("states", {}).get(key) is True
                for key in ("visible", "showing", "enabled", "sensitive", "focused")
            )
        ]
        if len(entries) != 1:
            raise ValueError("native polkit password field is not uniquely focused in GNOME Shell")
        x, y, w, h = rect(entries[0], size)
        accounts = [
            node
            for node in snapshot["nodes"]
            if node.get("pid") == shell_pid
            and node.get("role") == "label"
            and node.get("name", "").casefold() == "canary"
            and all(node.get("states", {}).get(key) is True for key in ("visible", "showing"))
        ]
        if len(accounts) != 1:
            raise ValueError(
                "native polkit administrator account label is not unique in GNOME Shell"
            )
        ax, ay, aw, ah = rect(accounts[0], size)
        visible_label(accounts[0], words, "canary", size)
        if not (ay + ah <= y + h and y - ay <= 400 and ax < x + w and ax + aw > x):
            raise ValueError(
                "native polkit account label is not paired with the focused password field"
            )
        self.qmp.type(password)
        self.qmp.key("ret")
        return {
            "dialog": "native GNOME polkit",
            "pid": shell_pid,
            "focused_password_role": True,
            "password_typed": True,
            "frame": frame.name,
        }
