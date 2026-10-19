#!/usr/bin/env python3
"""Read-only accessibility observations plus real QMP pointer/keyboard input.

No widget setters, accessibility actions, demo variables, or autoinstall API.
Password fields are identified by role/focus; their text is never read.
"""

import json
import re
import tempfile
import time
from pathlib import Path

# Runs in the admitted guest, before dropping to its desktop user. The socket
# is resolved through the exact pinned process's mount namespace. SO_PEERCRED
# identifies the per-instance proxy; a host PID and a bus PID are not synonyms.
PROXY_BINDING = r"""
import socket
import struct

def bind_accessibility(expected):
    if expected not in instances():
        raise ValueError("pinned installer process changed before accessibility observation")
    proc = PROC_ROOT / str(expected["pid"])
    def stamp(path):
        return path.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]
    start = stamp(proc)
    endpoint = proc / "root/run/flatpak/at-spi-bus"
    before = endpoint.stat()
    if not stat.S_ISSOCK(before.st_mode) or before.st_uid != uid:
        raise ValueError("installer accessibility endpoint is not its user socket")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(3)
        peer.connect(str(endpoint))
        proxy_pid, proxy_uid, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    proxy = PROC_ROOT / str(proxy_pid)
    if (proxy_pid <= 0 or proxy_pid == expected["pid"] or proxy_uid != uid
            or proxy.stat().st_uid != uid
            or proxy.joinpath("exe").resolve().name != "xdg-dbus-proxy"):
        raise ValueError("installer accessibility peer is not its user proxy")
    proxy_start = stamp(proxy)
    after = endpoint.stat()
    if ((before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or start != stamp(proc) or expected not in instances()):
        raise ValueError("installer accessibility binding changed during observation")
    return {"host_pid": expected["pid"], "bus_pid": proxy_pid, "uid": uid,
            "application": expected["application"], "app_commit": expected["app_commit"],
            "process_start": start, "proxy_start": proxy_start,
            "socket_device": before.st_dev, "socket_inode": before.st_ino}
"""

# Executed as the already authenticated desktop user. Atspi is the platform's
# normal accessibility observer, not a process injection or application test API.
SNAPSHOT = r"""
import json
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
Atspi.set_timeout(1500, 3000)
allowed = __PIDS__
# Dict form is the verified host-process -> bus-peer mapping. Lists are used
# only by source-shaped collector fixtures, without a Flatpak proxy.
peers = allowed if isinstance(allowed, dict) else {pid: pid for pid in allowed}
if len(set(peers.values())) != len(peers):
    raise ValueError("accessibility process bindings collide")
by_peer = {peer: host for host, peer in peers.items()}
roots = {host: 0 for host in peers}
observed_bus_pids = []
rows = []
objects = []
root = Atspi.get_desktop(0)
def visit(node, parent, depth):
    if depth > 24 or len(rows) >= 1800:
        raise ValueError("accessibility tree exceeds bound")
    bus_pid = node.get_process_id()
    if bus_pid not in by_peer:
        raise ValueError("accessibility descendant changed process binding")
    pid = by_peer[bus_pid]
    key = len(rows)
    role = node.get_role_name().casefold()
    state = node.get_state_set()
    states = {label: state.contains(value) for label, value in (
        ("showing", Atspi.StateType.SHOWING), ("visible", Atspi.StateType.VISIBLE),
        ("enabled", Atspi.StateType.ENABLED), ("sensitive", Atspi.StateType.SENSITIVE),
        ("focused", Atspi.StateType.FOCUSED), ("checked", Atspi.StateType.CHECKED),
        ("active", Atspi.StateType.ACTIVE), ("defunct", Atspi.StateType.DEFUNCT))}
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
    rows.append({"id": key, "parent": parent, "pid": pid, "bus_pid": bus_pid, "role": role,
                 "name": name, "states": states, "bounds": bounds, "role_id": int(node.get_role())})
    objects.append(node)
    count = node.get_child_count()
    if count > 1800:
        raise ValueError("accessibility child count exceeds bound")
    for index in range(count):
        child = node.get_child_at_index(index)
        if child is not None:
            visit(child, key, depth + 1)
if root.get_child_count() > 64:
    raise ValueError("accessibility application count exceeds bound")
for index in range(root.get_child_count()):
    app = root.get_child_at_index(index)
    if app is not None:
        observed_bus_pids.append(app.get_process_id())
    if app is not None and app.get_process_id() in by_peer:
        roots[by_peer[app.get_process_id()]] += 1
        visit(app, None, 0)
if isinstance(allowed, dict) and any(count != 1 for count in roots.values()):
    raise ValueError("accessibility process must have exactly one application root")
relation_targets = 0
for index, node in enumerate(objects):
    relations = {}
    unresolved = {}
    relation_set = node.get_relation_set() or []
    if len(relation_set) > 32:
        raise ValueError("accessibility relation set exceeds bound")
    for relation in relation_set:
        kind = relation.get_relation_type()
        label = {Atspi.RelationType.LABELLED_BY: "labelled_by",
                 Atspi.RelationType.DESCRIBED_BY: "described_by"}.get(kind)
        if label is None:
            continue
        if label in relations:
            raise ValueError("duplicate accessibility label relation")
        count = relation.get_n_targets()
        if count < 0 or count > 32:
            raise ValueError("accessibility relation exceeds bound")
        relation_targets += count
        if relation_targets > 4096:
            raise ValueError("accessibility relation target total exceeds bound")
        targets = []
        for offset in range(count):
            target = relation.get_target(offset)
            # GI wrappers need not be hashable or the same Python instance.
            match = next((i for i, candidate in enumerate(objects) if candidate == target), None)
            if match is None:
                # Relations are non-hierarchical. An unrelated off-tree label
                # must not destroy the snapshot; selected controls reject it.
                unresolved[label] = unresolved.get(label, 0) + 1
            else:
                targets.append(match)
        relations[label] = targets
    rows[index]["relations"] = relations
    rows[index]["unresolved_relations"] = unresolved
print(json.dumps({"schema_version": 1, "nodes": rows}))
"""


PROBE_FAILURE_MESSAGES = frozenset(
    re.findall(r'raise ValueError\("([^"\n]+)"\)', SNAPSHOT + PROXY_BINDING)
)


def diagnostic_program(program, filename):
    """Return bounded structural trace facts without exception values or locals."""
    return (
        "import json, traceback, hashlib\n"
        + "try:\n    exec(compile(" + repr(program) + ", " + repr(filename) + ", 'exec'))\n"
        + "except Exception as error:\n"
        + "    frames = traceback.extract_tb(error.__traceback__)[-12:]\n"
        + "    message = str(error)\n"
        + "    peers = globals().get('observed_bus_pids', [])\n"
        + "    peers = peers if isinstance(peers, list) and len(peers) <= 64 and all(type(p) is int and p > 0 for p in peers) else []\n"
        + "    allowed = " + repr(sorted(PROBE_FAILURE_MESSAGES)) + "\n"
        + "    print(json.dumps({'schema_version': 1, 'probe_error': {\n"
        + "        'exception_type': type(error).__name__[:80],\n"
        + "        'observed_bus_pids': peers,\n"
        + "        'message': message if message in allowed else '<omitted>',\n"
        + "        'message_sha256': hashlib.sha256(message.encode()).hexdigest(),\n"
        + "        'traceback': [{'file': f.filename if f.filename in "
        + repr(['<fork-accessibility>', '<fork-accessibility-launch>', '<string>'])
        + " else '<external>', 'line': f.lineno} for f in frames]}}))\n"
    )


def select(snapshot, name, roles, *, focused=False, pid=None):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ValueError("invalid accessibility observation")
    candidates = [
        node
        for node in snapshot.get("nodes", [])
        if (pid is None or node.get("pid") == pid)
        and node.get("name", "").casefold() == name.casefold()
        and node.get("role") in roles
        and all(
            node.get("states", {}).get(k) is True
            for k in ("visible", "showing", "enabled", "sensitive")
        )
        and node.get("states", {}).get("defunct") is not True
        and (not focused or node["states"].get("focused") is True)
    ]
    if len(candidates) != 1:
        raise ValueError("expected one visible enabled " + name + " control")
    complete_labels(candidates[0])
    return candidates[0]


def complete_labels(node):
    unresolved = node.get("unresolved_relations", {})
    if (not isinstance(unresolved, dict)
        or any(key not in {"labelled_by", "described_by"}
               or type(count) is not int or not 1 <= count <= 32
               for key, count in unresolved.items())):
        raise ValueError("invalid unresolved accessibility relations")
    if unresolved:
        raise ValueError("selected control has an unresolved label relation")


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
    if len(found) > 1:
        raise ValueError("ambiguous visible text within accessibility control")
    if not found:
        raise ValueError("accessibility control is not paired with its visible text")
    return found[0]


def tree(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ValueError("invalid accessibility observation")
    rows = snapshot.get("nodes")
    if not isinstance(rows, list) or len(rows) > 1800:
        raise ValueError("accessibility tree exceeds bound")
    nodes = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or type(row.get("id")) is not int
            or row["id"] < 0
            or row["id"] in nodes
            or type(row.get("pid")) is not int
            or row["pid"] <= 0
        ):
            raise ValueError("invalid accessibility node identity")
        parent = row.get("parent")
        if parent is not None and (
            type(parent) is not int or parent not in nodes or nodes[parent]["pid"] != row["pid"]
        ):
            raise ValueError("invalid accessibility ancestry")
        nodes[row["id"]] = row
    return nodes


def ancestors(node, nodes):
    result = []
    while node.get("parent") is not None:
        node = nodes[node["parent"]]
        result.append(node)
        if len(result) > 24:
            raise ValueError("accessibility ancestry exceeds bound")
    return result


def showing(node, *, enabled=False):
    keys = ("visible", "showing", "enabled", "sensitive") if enabled else ("visible", "showing")
    return node.get("states", {}).get("defunct") is not True and all(
        node.get("states", {}).get(key) is True for key in keys
    )


def inside(child, parent, size):
    x, y, w, h = rect(child, size)
    px, py, pw, ph = rect(parent, size)
    if not (px <= x and py <= y and x + w <= px + pw and y + h <= py + ph):
        raise ValueError("control is outside its bound accessible row/window")


def in_window(node, window, snapshot, size):
    if node["id"] != window["id"] and window not in ancestors(node, tree(snapshot)):
        raise ValueError("control does not descend from the active installer window")
    inside(node, window, size)


class InactiveInstallerError(ValueError):
    """An ordinary unfocused window may be activated with a bound heading click."""


def active_app(snapshot, pid, size):
    nodes = tree(snapshot)
    frames = [
        n
        for n in nodes.values()
        if n["pid"] == pid
        and n.get("role") in ("frame", "window")
        and showing(n)
        and n.get("states", {}).get("active") is True
    ]
    if not frames:
        raise InactiveInstallerError("installer does not have one active visible window")
    if len(frames) != 1:
        raise ValueError("installer has ambiguous active windows")
    frame = frames[0]
    rect(frame, size)
    focused = [
        n
        for n in nodes.values()
        if n["pid"] == pid
        and showing(n)
        and n.get("states", {}).get("focused") is True
        and frame in ancestors(n, nodes)
    ]
    if not focused:
        if frame.get("states", {}).get("focused") is True:
            raise ValueError("installer frame focus does not prove focused input descendant")
        raise InactiveInstallerError("installer window has no observed input focus")
    return frame


def titled_row(snapshot, name, pid, size):
    """Adw.ActionRow's exact title binds its nearest GtkListBoxRow ancestor."""
    nodes = tree(snapshot)
    titles = [
        n
        for n in nodes.values()
        if n["pid"] == pid
        and showing(n)
        and n.get("name", "").casefold() == name.casefold()
        and n.get("role") in ("label", "list item")
    ]
    matches = {}
    for title in titles:
        lineage = [title] + ancestors(title, nodes)
        rows = [n for n in lineage if n.get("role") == "list item"]
        if not rows:
            continue
        row = rows[0]
        if showing(row, enabled=True):
            inside(title, row, size)
            matches.setdefault(row["id"], (row, []))[1].append(title)
    if len(matches) != 1:
        raise ValueError("expected one visible titled action row: " + name)
    row, titles = next(iter(matches.values()))
    labels = [title for title in titles if title["role"] == "label"]
    if len(labels) > 1:
        raise ValueError("action row title label is ambiguous")
    title = labels[0] if labels else row
    complete_labels(row)
    complete_labels(title)
    if row.get("name", "").casefold() not in ("", name.casefold()):
        raise ValueError("action row has a contradictory accessible name")
    labelled_by = row.get("relations", {}).get("labelled_by")
    # Adw.ActionRow explicitly labels itself with its title GtkLabel. Require
    # that relation when its own computed name is empty, and reject conflicts.
    if labelled_by is not None:
        if labelled_by != [title["id"]] or title["role"] != "label":
            raise ValueError("action row title relation is absent or contradictory")
    elif row.get("name", "").casefold() != name.casefold():
        raise ValueError("action row title has no exact accessibility binding")
    return row, title


def row_switch(snapshot, name, pid, size):
    nodes = tree(snapshot)
    row, title = titled_row(snapshot, name, pid, size)
    switches = [
        n
        for n in nodes.values()
        if n["pid"] == pid
        and n.get("role") in ("check box", "toggle button", "switch")
        and showing(n, enabled=True)
        and next((a for a in ancestors(n, nodes) if a.get("role") == "list item"), None) == row
    ]
    if len(switches) != 1:
        raise ValueError("expected exactly one switch in the titled encryption row")
    switch = switches[0]
    complete_labels(switch)
    # An unnamed suffix is valid; a different explicit label is not.
    if switch.get("name", "").casefold() not in ("", name.casefold()):
        raise ValueError("encryption suffix has another accessible label")
    labelled_by = switch.get("relations", {}).get("labelled_by")
    if labelled_by is not None and labelled_by != [title["id"]]:
        raise ValueError("encryption suffix has a contradictory title relation")
    inside(switch, row, size)
    return row, title, switch


DIAGNOSTIC_NAMES = {
    "",
    "Welcome to Harbor Canary",
    "Install Harbor Canary",
    "Power Off",
    "Credits",
    "Type to search",
    "Disk Encryption",
    "Encrypt this disk",
    "Use hardware-backed encryption",
    "Create User",
    "Name",
    "Username",
    "Password",
    "Confirm Password",
    "Next",
    "Back",
    "Install",
    "Choose an Image",
    "Harbor Canary",
    "Confirm installation",
    "Install Location",
    "Authentication Required",
    "canary",
    "Harbor Canary is installed",
}


def safe_snapshot(snapshot):
    """Keep only structural facts and known static labels, never field values."""
    nodes = tree(snapshot)
    safe = []
    for node in nodes.values():
        role = node.get("role")
        if not isinstance(role, str) or not re.fullmatch(r"[a-z -]{1,80}", role):
            raise ValueError("invalid accessibility role")
        bounds = node.get("bounds")
        if bounds is not None and (
            not isinstance(bounds, list)
            or len(bounds) != 4
            or any(type(v) is not int or abs(v) > 2**31 for v in bounds)
        ):
            raise ValueError("invalid accessibility bounds")
        states = node.get("states", {})
        if not isinstance(states, dict) or len(states) > 32:
            raise ValueError("invalid accessibility states")
        name = node.get("name", "")
        if not isinstance(name, str) or len(name) > 512:
            raise ValueError("invalid accessibility name")
        safe.append(
            {
                "id": node["id"],
                "parent": node.get("parent"),
                "pid": node["pid"],
                "role": role,
                "name": name if name in DIAGNOSTIC_NAMES else "<omitted>",
                "bounds": bounds,
                "states": {
                    k: states[k]
                    for k in (
                        "visible",
                        "showing",
                        "enabled",
                        "sensitive",
                        "focused",
                        "checked",
                        "active",
                        "defunct",
                    )
                    if type(states.get(k)) is bool
                },
            }
        )
    for original, item in zip(nodes.values(), safe, strict=True):
        if type(original.get("role_id")) is int and 0 <= original["role_id"] <= 1024:
            item["role_id"] = original["role_id"]
        relations = original.get("relations", {})
        if not isinstance(relations, dict) or len(relations) > 32:
            raise ValueError("invalid accessibility relations")
        unresolved = original.get("unresolved_relations", {})
        if (not isinstance(unresolved, dict)
            or any(key not in {"labelled_by", "described_by"}
                   or type(count) is not int or not 1 <= count <= 32
                   for key, count in unresolved.items())):
            raise ValueError("invalid unresolved accessibility relations")
        item["unresolved_relations"] = unresolved
        item["relations"] = {}
        for key in ("labelled_by", "described_by"):
            if key in relations:
                targets = relations[key]
                if (
                    not isinstance(targets, list)
                    or len(targets) > 32
                    or any(type(t) is not int or t not in nodes for t in targets)
                ):
                    raise ValueError("invalid accessibility relation targets")
                item["relations"][key] = targets
    result = {"schema_version": 1, "nodes": safe}
    if len(json.dumps(result, ensure_ascii=True)) > 512 * 1024:
        raise ValueError("safe accessibility evidence exceeds bound")
    return result


class UI:
    def __init__(
        self, qmp, screenshot, snapshot, words, *, app_pid=None, private=None, evidence=None
    ):
        self.qmp, self.screenshot, self.snapshot, self.words = qmp, screenshot, snapshot, words
        self.counter = 0
        self.app_pid, self.private, self.evidence = app_pid, private, evidence

    def capture(self, label):
        from PIL import Image

        self.counter += 1
        frame = self.screenshot(f"ui-{self.counter:03d}-{label}.png")
        with Image.open(frame) as image:
            size = image.size
        snapshot = self.snapshot()
        if self.evidence is not None:
            self.evidence(
                {"frame": Path(frame).name, "size": list(size), "snapshot": safe_snapshot(snapshot)}
            )
        return frame, size, self.words(frame), snapshot

    def label_point(self, frame, node, rows, phrase, size):
        try:
            return visible_label(node, rows, phrase, size)
        except ValueError as error:
            if self.private is None or "ambiguous" in str(error):
                raise
        # Low-contrast GTK button text is missed by full-frame OCR in run15.
        # Crop only the accessibility-bound label/control and require all exact
        # tokens at high confidence; never expand to a guessed screen region.
        from PIL import Image, ImageOps

        x, y, w, h = rect(node, size)
        with Image.open(frame) as source:
            crop = ImageOps.autocontrast(ImageOps.grayscale(source.crop((x, y, x + w, y + h))))
            crop = crop.resize((w * 4, h * 4), Image.Resampling.LANCZOS)
            with tempfile.TemporaryDirectory(prefix="control-ocr-", dir=self.private) as temporary:
                path = Path(temporary) / "control.png"
                crop.save(path)
                text = self.words(path, psm=7, confidence=0)
        if [r["text"].strip().casefold() for r in text] != phrase.casefold().split() or any(
            float(r["conf"]) < 80 for r in text
        ):
            raise ValueError("bound control crop does not contain the exact visible label")
        return x + w / 2, y + h / 2

    def start_welcome(self, name="Install Harbor Canary"):
        if self.app_pid is None:
            raise ValueError("Welcome navigation requires a bound installer process")
        frame, size, words, snapshot = self.capture("welcome-focus")
        escaped = False
        if phrase_rows(words, "Type to search"):
            self.qmp.key("esc")
            escaped = True
            time.sleep(1)
            frame, size, words, snapshot = self.capture("welcome-after-overview")
        if phrase_rows(words, "Type to search"):
            raise ValueError("GNOME overview is still visible")
        try:
            active_app(snapshot, self.app_pid, size)
        except InactiveInstallerError:
            visible_windows = [
                n
                for n in tree(snapshot).values()
                if n["pid"] == self.app_pid and n.get("role") in ("frame", "window") and showing(n)
            ]
            if len(visible_windows) != 1:
                raise ValueError("Welcome activation requires one unambiguous visible window")
            title = select(snapshot, "Welcome to Harbor Canary", ("label",), pid=self.app_pid)
            windows = [
                n
                for n in ancestors(title, tree(snapshot))
                if n.get("role") in ("frame", "window") and showing(n)
            ]
            if len(windows) != 1:
                raise ValueError("Welcome heading is not bound to one installer window")
            inside(title, windows[0], size)
            self.point(
                self.label_point(frame, title, words, "Welcome to Harbor Canary", size), size
            )
            frame, size, words, snapshot = self.capture("welcome-focused")
        window = active_app(snapshot, self.app_pid, size)
        if phrase_rows(words, "Type to search"):
            raise ValueError("GNOME overview obscures the active installer")
        row, title = titled_row(snapshot, name, self.app_pid, size)
        in_window(row, window, snapshot, size)
        point = self.label_point(frame, title, words, name, size)
        self.point(point, size)
        return {
            "pid": self.app_pid,
            "role": row["role"],
            "name": name,
            "bounds": row["bounds"],
            "overview_escape": escaped,
            "active_window_and_focus_verified": True,
        }

    def click(self, name, roles=("push button",), *, label=None):
        frame, size, words, snapshot = self.capture("control")
        node = select(snapshot, name, roles, pid=self.app_pid)
        if self.app_pid is not None:
            in_window(node, active_app(snapshot, self.app_pid, size), snapshot, size)
        point = self.label_point(frame, node, words, label or name, size)
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
        node = select(snapshot, name, roles, pid=self.app_pid)
        if self.app_pid is not None:
            in_window(node, active_app(snapshot, self.app_pid, size), snapshot, size)
        x, y, w, h = rect(node, size)
        self.point((x + w / 2, y + h / 2), size)
        fresh = self.snapshot()
        focused = select(fresh, name, roles, focused=True, pid=self.app_pid)
        if self.app_pid is not None:
            in_window(focused, active_app(fresh, self.app_pid, size), fresh, size)
        if focused["pid"] != node["pid"]:
            raise ValueError("input focus moved to another application")
        if any(focused.get(key) != node.get(key) for key in ("role", "bounds")):
            raise ValueError("input focus moved away from the exact bound control")
        self.qmp.key("ctrl", "a")
        self.qmp.type(value)
        # Never read field text, and never return the supplied value.
        return {"name": name, "role": node["role"], "typed": True, "secret": secret}

    def toggle_off(self, name):
        frame, size, words, snapshot = self.capture("encryption")
        if self.app_pid is None:
            raise ValueError("encryption control requires a bound installer process")
        window = active_app(snapshot, self.app_pid, size)
        row, title, node = row_switch(snapshot, name, self.app_pid, size)
        in_window(row, window, snapshot, size)
        self.label_point(frame, title, words, name, size)
        if node["states"].get("checked") is not True:
            raise ValueError("expected checked encryption switch with visible row label")
        x, y, w, h = rect(node, size)
        self.point((x + w / 2, y + h / 2), size)
        changed_snapshot = self.snapshot()
        active_app(changed_snapshot, self.app_pid, size)
        changed_row, _, changed = row_switch(changed_snapshot, name, self.app_pid, size)
        in_window(
            changed_row, active_app(changed_snapshot, self.app_pid, size), changed_snapshot, size
        )
        if (
            changed["pid"] != node["pid"]
            or changed["role"] != node["role"]
            or changed["bounds"] != node["bounds"]
            or changed["states"].get("checked") is not False
        ):
            raise ValueError("native encryption switch did not turn off")
        return {
            "name": name,
            "pid": node["pid"],
            "row_bounds": row["bounds"],
            "switch_bounds": node["bounds"],
            "checked_before": True,
            "checked_after": False,
        }

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
