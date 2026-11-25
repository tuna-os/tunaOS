"""Guest AT-SPI tree dump transport (tunaOS#4910, #4901).

The dump runs inside the guest session over SSH (Utah atspi_drive.py); the
clicks run on the host over QMP. This module builds the SSH command and
validates the JSON the guest returns. No network or guest needed to test it.
"""

from __future__ import annotations

import json

GUEST_DUMP_PATH = "/usr/libexec/tunaos/atspi_dump_guest.py"

REQUIRED_KEYS = ("name", "role", "states", "path")


def ssh_dump_command(host_port, key_path, app_substr, user="liveuser", extra_opts=()):
    """SSH command dumping the guest AT-SPI tree for one app substring."""
    return [
        "ssh",
        "-p",
        str(host_port),
        "-i",
        key_path,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=10",
        *[a for opt in extra_opts for a in ("-o", opt)],
        f"{user}@127.0.0.1",
        f"python3 {GUEST_DUMP_PATH} dump {app_substr}",
    ]


def parse_tree(raw):
    """Validate guest JSON into a node list. Raises ValueError on bad input."""
    try:
        nodes = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"guest dump is not JSON: {exc}") from exc
    if not isinstance(nodes, list):
        raise TypeError(f"guest dump must be a list, got {type(nodes).__name__}")
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise TypeError(f"node {i} is not an object")
        missing = [k for k in REQUIRED_KEYS if k not in node]
        if missing:
            raise ValueError(f"node {i} misses keys: {missing}")
    return nodes


def summarize(nodes):
    """One CI log line per button, check box and label (Utah summarize_nodes)."""
    lines = []
    for node in nodes:
        if node.get("role") not in ("button", "push button", "check box", "label"):
            continue
        states = node.get("states", [])
        lines.append(
            f"{node['role']} name={node.get('name', '')!r} "
            f"showing={'showing' in states} sensitive={'sensitive' in states}"
        )
    return lines or ["no buttons, check boxes or labels"]
