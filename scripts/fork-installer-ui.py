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

MAX_NODES = 4096
MAX_DEPTH = 64
MAX_EVIDENCE_BYTES = 2 * 1024 * 1024

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
traversal_metrics = {"visited_nodes": 0, "max_depth": 0}
def visit(node, parent, depth, trail=()):
    traversal_metrics["visited_nodes"] = len(rows)
    traversal_metrics["max_depth"] = max(depth, traversal_metrics["max_depth"])
    if any(node == ancestor for ancestor in trail):
        raise ValueError("accessibility child cycle detected")
    if depth > __MAX_DEPTH__:
        raise ValueError("accessibility depth exceeds bound")
    if len(rows) >= __MAX_NODES__:
        raise ValueError("accessibility node count exceeds bound")
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
    if count < 0 or count > __MAX_NODES__:
        raise ValueError("accessibility child count exceeds bound")
    for index in range(count):
        child = node.get_child_at_index(index)
        if child is not None:
            visit(child, key, depth + 1, trail + (node,))
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
traversal_metrics["visited_nodes"] = len(rows)
print(json.dumps({"schema_version": 1, "nodes": rows, "traversal": traversal_metrics}))
""".replace("__MAX_NODES__", str(MAX_NODES)).replace("__MAX_DEPTH__", str(MAX_DEPTH))


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
        + "    metrics = globals().get('traversal_metrics', {})\n"
        + "    metrics = {k: metrics[k] for k in ('visited_nodes', 'max_depth') if isinstance(metrics, dict) and type(metrics.get(k)) is int and 0 <= metrics[k] <= 100000}\n"
        + "    allowed = " + repr(sorted(PROBE_FAILURE_MESSAGES)) + "\n"
        + "    print(json.dumps({'schema_version': 1, 'probe_error': {\n"
        + "        'exception_type': type(error).__name__[:80],\n"
        + "        'observed_bus_pids': peers,\n"
        + "        'traversal': metrics,\n"
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
    if not isinstance(rows, list) or len(rows) > MAX_NODES:
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
        if len(result) > MAX_DEPTH:
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
    metrics = snapshot.get("traversal", {})
    if (not isinstance(metrics, dict)
        or any(k not in {"visited_nodes", "max_depth"} or type(v) is not int
               or not 0 <= v <= (MAX_NODES if k == "visited_nodes" else MAX_DEPTH)
               for k, v in metrics.items())):
        raise ValueError("invalid accessibility traversal metrics")
    result["traversal"] = metrics
    if len(json.dumps(result, ensure_ascii=True)) > MAX_EVIDENCE_BYTES:
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

    def authentication_ready(self, shell_pid):
        frame, size, words, snapshot = self.capture("authentication-wait")
        controls = polkit_prompt(snapshot, shell_pid, size, waiting=True)
        if controls is None:
            return False
        _, title, account, _ = controls
        self.label_point(frame, title, words, "Authentication Required", size)
        self.label_point(frame, account, words, "canary", size)
        return True

    def authenticate(self, password, shell_pid):
        frame, size, words, snapshot = self.capture("polkit-password")
        controls = polkit_prompt(snapshot, shell_pid, size)
        _, title, account, entry = controls
        self.label_point(frame, title, words, "Authentication Required", size)
        self.label_point(frame, account, words, "canary", size)
        fresh = polkit_prompt(self.snapshot(), shell_pid, size)
        # The process binding is rechecked by the snapshot provider. Require
        # this same dialog and focused field after the bounded OCR reads.
        if [(n["id"], n["bounds"]) for n in fresh] != [(n["id"], n["bounds"]) for n in controls]:
            raise ValueError("native polkit prompt changed before password input")
        self.qmp.type(password)
        self.qmp.key("ret")
        return {
            "dialog": "native GNOME polkit",
            "pid": shell_pid,
            "focused_password_role": True,
            "password_typed": True,
            "frame": frame.name,
        }


def polkit_prompt(snapshot, shell_pid, size, *, waiting=False):
    """Select only the exact Shell dialog, never a generic password field."""
    nodes = tree(snapshot)
    shell_nodes = [n for n in nodes.values() if n["pid"] == shell_pid and showing(n)]
    titles = [n for n in shell_nodes if n["role"] == "label" and n["name"] == "Authentication Required"]
    entries = [n for n in shell_nodes if n["role"] == "password text"]
    if waiting and len(titles) <= 1 and len(entries) <= 1 and (not titles or not entries):
        return None
    if len(titles) != 1 or len(entries) != 1:
        raise ValueError("native polkit title or password field is absent or ambiguous")
    entry, title = entries[0], titles[0]
    if not all(entry["states"].get(k) is True for k in ("enabled", "sensitive", "focused")):
        if waiting and entry["states"].get("focused") is False:
            return None
        raise ValueError("native polkit password field is not uniquely focused")
    focused = [n for n in shell_nodes if n["states"].get("focused") is True]
    if len(focused) != 1 or focused[0] != entry:
        raise ValueError("native polkit focus is ambiguous")
    dialogs = [n for n in ancestors(entry, nodes) if n["role"] == "dialog" and n["pid"] == shell_pid]
    if len(dialogs) != 1 or dialogs[0] not in ancestors(title, nodes):
        raise ValueError("native polkit title is not bound to the focused dialog")
    accounts = [n for n in shell_nodes if n["role"] == "label" and n["name"] == "canary"
                and dialogs[0] in ancestors(n, nodes)]
    if len(accounts) != 1:
        raise ValueError("native polkit administrator is not uniquely bound to the dialog")
    account = accounts[0]
    for n in (title, account):
        complete_labels(n)
    # StEntry describes its inner text with an off-tree hint actor. This
    # supplemental hint is not used to identify the administrator or field.
    # Keep unresolved identity labels closed; admit only the known single hint.
    unresolved = entry.get("unresolved_relations", {})
    if unresolved not in ({}, {"described_by": 1}) or "labelled_by" in entry.get("relations", {}):
        raise ValueError("native polkit password has unresolved identity labels")
    for n in (title, account, entry):
        rect(n, size)
    x, y, w, h = entry["bounds"]
    ax, ay, aw, ah = account["bounds"]
    tx, ty, tw, th = title["bounds"]
    if not (ty + th <= ay and ay + ah <= y + h and y - ay <= 400
            and ax < x + w and ax + aw > x and tx < x + w and tx + tw > x):
        raise ValueError("native polkit labels are not paired with the password field")
    return dialogs[0], title, account, entry


PAGE_HEADINGS = (
    "Welcome to Harbor Canary", "Disk Encryption", "Create User",
    "Choose an Image", "Confirm installation", "Install Location",
)


def keyboard_window(snapshot, pid, *, allow_unfocused=False):
    """GTK4 SENSITIVE represents !DISABLED; ENABLED is not emitted.

    GTK 4.22 gtkatspicontext.c and gtkatspiutils.c also deliberately return
    zero SCREEN coordinates. Keyboard input needs native focus, not invented
    geometry. Only the exact process-bound active window is admitted.
    """
    nodes = tree(snapshot)
    frames = [n for n in nodes.values() if n["pid"] == pid
              and n["role"] in ("frame", "window") and showing(n)
              and n["states"].get("active") is True]
    if len(frames) != 1:
        raise ValueError("keyboard navigation requires one active installer window")
    focused = [n for n in nodes.values() if n["pid"] == pid and showing(n)
               and n["states"].get("focused") is True and frames[0] in ancestors(n, nodes)]
    if not focused and allow_unfocused:
        return frames[0], None
    if len(focused) != 1:
        raise ValueError("keyboard navigation requires one focused installer descendant")
    return frames[0], focused[0]


def page_branch(snapshot, heading, pid):
    nodes = tree(snapshot)
    headings = [n for n in nodes.values() if n["pid"] == pid and n["role"] == "label"
                and n["name"] in PAGE_HEADINGS]
    matches = [n for n in headings if n["name"] == heading]
    if len(matches) != 1 or len(headings) < 2:
        raise ValueError("wizard page heading is absent or ambiguous")
    target = matches[0]
    complete_labels(target)
    other_paths = [{n["id"] for n in [h] + ancestors(h, nodes)}
                   for h in headings if h != target]
    exclusive = [n for n in [target] + ancestors(target, nodes)
                 if not any(n["id"] in path for path in other_paths)]
    if not exclusive:
        raise ValueError("wizard pages do not have distinct ancestry")
    return exclusive[-1]


def keyboard_target(snapshot, heading, name, roles, pid, *, header=False, allow_unfocused=False):
    nodes = tree(snapshot)
    window, focused = keyboard_window(snapshot, pid, allow_unfocused=allow_unfocused)
    branch = page_branch(snapshot, heading, pid)
    page_roots = [page_branch(snapshot, h, pid) for h in PAGE_HEADINGS
                  if any(n["name"] == h and n["role"] == "label" for n in nodes.values())]
    candidates = []
    for node in nodes.values():
        lineage = ancestors(node, nodes)
        role = "push button" if node["role"] == "button" and node.get("role_id") == 43 else node["role"]
        if (node["pid"] != pid or node["name"] != name or role not in roles
                or not showing(node) or node["states"].get("sensitive") is not True
                or window not in lineage):
            continue
        if header:
            if any(root == node or root in lineage for root in page_roots):
                continue
        elif branch != node and branch not in lineage:
            continue
        complete_labels(node)
        candidates.append(node)
    if len(candidates) != 1:
        raise ValueError("keyboard target is absent, disabled, or ambiguous on the verified page")
    return candidates[0], focused


def confirmation_disk(snapshot, pid, target_path):
    """Bind the displayed disk and erasure warning to the exact confirm page."""
    if not re.fullmatch(r"/dev/[a-zA-Z0-9]+", target_path):
        raise ValueError("invalid guarded target path")
    nodes = tree(snapshot)
    window, _ = keyboard_window(snapshot, pid, allow_unfocused=True)
    branch = page_branch(snapshot, "Confirm installation", pid)
    labels = [n for n in nodes.values() if n["pid"] == pid and n["role"] == "label"
              and showing(n) and window in ancestors(n, nodes)
              and branch in ancestors(n, nodes)]
    warning = f"Everything on {target_path} will be erased. This cannot be undone."
    selected = [n for n in labels if n["name"] == f"{target_path} (64 GiB)"]
    warnings = [n for n in labels if n["name"] == warning]
    if len(selected) != 1 or len(warnings) != 1:
        raise ValueError("confirmation disk subtitle or warning is absent or ambiguous")
    row = next((n for n in ancestors(selected[0], nodes) if n["role"] == "list item"), None)
    disk_titles = [n for n in labels if n["name"] == "Disk" and row in ancestors(n, nodes)]
    if row is None or len(disk_titles) != 1:
        raise ValueError("confirmation target subtitle is not bound to the Disk row")
    for node in selected + warnings + disk_titles:
        complete_labels(node)
    return warning


class KeyboardUI(UI):
    """Real bounded Tab traversal; never calls an accessibility action/setter."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.focus_transition = None
        self.current_page = None
        self.navigation_events = []

    def confirmation_target(self, target_path):
        """Read-only, exact path proof; no fuzzy OCR or guessed crop geometry."""
        from PIL import Image, ImageOps

        frame, size, rows, snapshot = self.capture("confirmation-target")
        if ([h for h in PAGE_HEADINGS if phrase_rows(rows, h)] != ["Confirm installation"]
                or phrase_rows(rows, "Type to search")):
            raise ValueError("confirmation page is not uniquely visible")
        warning = confirmation_disk(snapshot, self.app_pid, target_path)
        # GTK's red warning is lost by full-size sparse OCR. Scaling the whole
        # frame preserves placement and exact tokens, without inventing bounds.
        with Image.open(frame) as source:
            if source.size != size or size[0] * size[1] > 4096 * 2160:
                raise ValueError("confirmation framebuffer exceeds bounded size")
            scaled = ImageOps.grayscale(source).resize((size[0] * 2, size[1] * 2))
            with tempfile.TemporaryDirectory(prefix="confirmation-ocr-", dir=self.private) as temporary:
                path = Path(temporary) / "frame.png"
                scaled.save(path)
                rows = self.words(path, psm=11, confidence=80)
        matches = phrase_rows(rows, warning)
        if len(matches) != 1:
            raise ValueError("confirmation does not visibly identify the exact target warning")
        # phrase_rows normalizes punctuation for prose; the device token must
        # additionally match byte-for-byte, preserving slashes and suffixes.
        if [r["text"] for r in matches[0]][2] != target_path:
            raise ValueError("confirmation target OCR token differs from guarded path")
        confirmation_disk(self.snapshot(), self.app_pid, target_path)
        return {"target_path": target_path, "size_gib": 64, "frame": Path(frame).name,
                "warning_visible": True, "disk_row_bound": True,
                "ocr": "full-frame grayscale 2x; exact warning; confidence >=80"}

    def page(self, expected=None):
        frame, size, words, snapshot = self.capture("keyboard-page")
        if phrase_rows(words, "Type to search"):
            raise ValueError("GNOME overview obscures keyboard navigation")
        found = [heading for heading in PAGE_HEADINGS if phrase_rows(words, heading)]
        if len(found) != 1 or (expected is not None and found[0] != expected):
            raise ValueError("visible wizard page is absent, ambiguous, or changed")
        keyboard_window(snapshot, self.app_pid, allow_unfocused=True)
        page_branch(snapshot, found[0], self.app_pid)
        return found[0], snapshot

    def focus(self, name, roles, *, heading=None, header=False):
        heading, snapshot = self.page(heading)
        seen = set()
        deadline = time.monotonic() + 90
        pending = self.focus_transition
        bootstrap = (pending is not None and pending.get("action") in {"Welcome", "Next"}
                     and pending.get("from") in PAGE_HEADINGS and pending["from"] != heading)
        for _ in range(32):
            if time.monotonic() >= deadline:
                raise ValueError("native keyboard focus deadline expired")
            target, focused = keyboard_target(snapshot, heading, name, roles, self.app_pid,
                                             header=header, allow_unfocused=bootstrap)
            if focused is None:
                # A page advance can disable the focused header Next button.
                # This is the only case that admits one non-activating Tab
                # without widget focus. The exact app/window/page and target
                # remain bound; Enter and all text still need unique focus.
                _, snapshot = self.page(heading)
                target, focused = keyboard_target(snapshot, heading, name, roles, self.app_pid,
                                                 header=header, allow_unfocused=True)
                if focused is not None:
                    continue
                if time.monotonic() >= deadline:
                    raise ValueError("native keyboard focus deadline expired")
                self.qmp.key("tab")
                self.navigation_events.append({"action": "establish-focus-with-tab",
                                               "from": pending["from"], "page": heading})
                bootstrap = False
                self.focus_transition = None
                for _ in range(4):
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(.25)
                    snapshot = self.snapshot()
                    _, focused = keyboard_window(snapshot, self.app_pid, allow_unfocused=True)
                    if focused is not None:
                        break
                if focused is None:
                    raise ValueError("native focus did not appear after the single transition Tab")
                continue
            # A hidden matching control never qualifies: actual focus must land
            # on the unique control inside the screenshot-verified page branch.
            if focused == target:
                final_heading, fresh = self.page(heading)
                target, focused = keyboard_target(fresh, final_heading, name, roles, self.app_pid, header=header)
                if focused != target:
                    raise ValueError("keyboard focus changed before native input")
                self.current_page = heading
                self.focus_transition = None
                return target
            identity = (focused["id"], focused["parent"], focused["role"], focused["name"])
            if identity in seen or time.monotonic() >= deadline:
                raise ValueError("native keyboard focus cycled or did not advance to target")
            seen.add(identity)
            self.qmp.key("tab")
            time.sleep(.2)
            snapshot = self.snapshot()
        raise ValueError("native keyboard focus traversal exceeds bound")

    def start_welcome(self, name="Install Harbor Canary"):
        _, _, words, _ = self.capture("keyboard-welcome")
        escaped = bool(phrase_rows(words, "Type to search"))
        if escaped:
            self.qmp.key("esc")
            time.sleep(1)
        target = self.focus(name, ("list item",), heading="Welcome to Harbor Canary")
        self.qmp.key("ret")
        self.focus_transition = {"from": self.current_page, "action": "Welcome"}
        return {"name": name, "pid": target["pid"], "role": target["role"],
                "transport": "QMP keyboard", "focused": True, "overview_escape": escaped}

    def click(self, name, roles=("push button",), *, label=None):
        if label is not None:
            raise ValueError("keyboard action does not admit alternate labels")
        if name == "Install":
            _, snapshot = self.page("Confirm installation")
            target, focused = keyboard_target(snapshot, "Confirm installation", name, roles, self.app_pid)
            if target != focused:
                raise ValueError("Install focus changed after the final disk guard")
        else:
            target = self.focus(name, roles, header=name == "Next")
        self.qmp.key("ret")
        if name == "Next":
            self.focus_transition = {"from": self.current_page, "action": "Next"}
        return {"name": name, "pid": target["pid"], "role": target["role"],
                "transport": "QMP keyboard", "focused": True}

    def field(self, name, value, *, secret=False):
        target = self.focus(name, ("password text",) if secret else ("text", "entry"), heading="Create User")
        self.qmp.key("ctrl", "a")
        self.qmp.type(value)
        return {"name": name, "role": target["role"], "typed": True, "secret": secret,
                "transport": "QMP keyboard", "focused": True}

    def toggle_off(self, name):
        target = self.focus(name, ("switch", "check box", "toggle button"), heading="Disk Encryption")
        if target["states"].get("checked") is not True:
            raise ValueError("encryption switch was not checked before native input")
        self.qmp.key("spc")
        time.sleep(.3)
        _, fresh = self.page("Disk Encryption")
        changed, focused = keyboard_target(fresh, "Disk Encryption", name,
                                          ("switch", "check box", "toggle button"), self.app_pid)
        if changed != focused or changed["states"].get("checked") is not False:
            raise ValueError("native keyboard encryption switch did not turn off")
        return {"name": name, "pid": target["pid"], "checked_before": True,
                "checked_after": False, "transport": "QMP keyboard", "focused": True}
