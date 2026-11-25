"""Host-side QMP absolute-pointer clicks (tunaOS#4910, #4901).

Wayland allows no synthetic input from inside the guest, so the host clicks
through QMP `input-send-event` on a USB tablet (Utah raw_e2e.py `click_at`).
This module only builds the event payloads; driver.py sends them over the
QMP socket. Pure functions, no QEMU needed, unit-tested.
"""

from __future__ import annotations

ABS_MAX = 32767


def clamp(value, low, high):
    """Clamp `value` into [`low`, `high`]."""
    return max(low, min(high, value))


def abs_move(x, y, width=1280, height=800):
    """QMP `input-send-event` payload moving the tablet pointer to (x, y)."""
    cx = clamp(int(x), 0, width - 1)
    cy = clamp(int(y), 0, height - 1)
    return {
        "execute": "input-send-event",
        "arguments": {
            "events": [
                {"type": "abs", "data": {"axis": "x", "value": round(cx * ABS_MAX / (width - 1))}},
                {"type": "abs", "data": {"axis": "y", "value": round(cy * ABS_MAX / (height - 1))}},
            ]
        },
    }


def btn(down):
    """QMP left-button press (`down=True`) or release (`down=False`)."""
    return {
        "execute": "input-send-event",
        "arguments": {"events": [{"type": "btn", "data": {"down": bool(down), "button": "left"}}]},
    }


def click_at(x, y, width=1280, height=800):
    """The three QMP commands of one host-side click: move, press, release."""
    return [abs_move(x, y, width, height), btn(True), btn(False)]


def node_center(node, width=1280, height=800):
    """Pixel center of an AT-SPI node `ext` box, clamped to the screen."""
    x, y, w, h = node.get("ext") or (0, 0, 0, 0)
    return (clamp(x + w // 2, 0, width - 1), clamp(y + h // 2, 0, height - 1))


def click_node(node, width=1280, height=800):
    """Click payloads for an AT-SPI node's center. Raises on missing extents."""
    if not node.get("ext"):
        raise ValueError(f"node {node.get('name', '')!r} has no extents")
    x, y = node_center(node, width, height)
    return click_at(x, y, width, height)
