"""Frontend-neutral AT-SPI poll loop (tunaOS#4910, #4901).

The dump runs inside the guest, the clicks run on the host. This module
holds the loop between the two: poll the tree, classify the page from its
text on every poll, fail on FAILURE before DONE, and click qualified nodes
from the host. All I/O enters through injected callables, so unit tests
drive the loop with recorded fixtures and no VM.
"""

from __future__ import annotations

import time

from atspi_match import PRESS_ROLES, Page, classify_page, find_recovery_key, qualify
from qmp_input import click_node


class DriverError(RuntimeError):
    """The installer stalled or failed in a way the loop can name."""


class Driver:
    """Poll-classify-click over injected dump/click/screenshot functions."""

    def __init__(
        self, dump, click, screenshot=None, poll_interval=2.0, width=1280, height=800, press=None,
        classify=classify_page,
    ):
        """`dump(app)` returns a node list; `click(cmds)` sends QMP commands.

        `press(app, node)` runs the AT-SPI action of a node in the guest. When
        given, it replaces the pointer click: a Wayland session reports no
        screen coordinates for a node."""
        self.press = press
        self.classify = classify
        self.dump = dump
        self.click = click
        self.screenshot = screenshot or (lambda name: None)
        self.poll_interval = poll_interval
        self.width = width
        self.height = height
        self.last_nodes = []

    def poll(self, app):
        """Dump once and classify. Records the snapshot for failure dumps."""
        self.last_nodes = self.dump(app)
        return self.classify(self.last_nodes)

    def wait_for(self, app, want, timeout=600):
        """Poll until `want` (a Page or set of Pages); FAILURE raises first."""
        if isinstance(want, Page):
            want = {want}
        deadline = time.monotonic() + timeout
        page = Page.WAIT
        while time.monotonic() < deadline:
            page = self.poll(app)
            if page is Page.FAILURE:
                self.screenshot("failed")
                raise DriverError(f"installer failed on {page.value}: {self.last_nodes!r}")
            if page in want:
                return page
            time.sleep(self.poll_interval)
        self.screenshot("stuck")
        raise DriverError(
            f"timed out waiting for {[p.value for p in want]}, "
            f"stuck on {page.value}: {self.last_nodes!r}"
        )

    def click_named(self, app, name, role=None, sensitive=True):
        """Click the qualified node by role AND sensitivity. Raises if none."""
        nodes = self.dump(app)
        self.last_nodes = nodes
        node = qualify(nodes, name, role=role, sensitive=sensitive)
        if node is None:
            raise DriverError(
                f"no {'sensitive ' if sensitive else ''}{role or 'node'} "
                f"named {name!r} on {[n.get('name') for n in nodes]!r}"
            )
        if self.press is not None:
            self.press(app, node)
        else:
            self.click(click_node(node, self.width, self.height))
        return node

    def click_primary(self, app, names=("Next", "Continue", "Install", "Done")):
        """Click the first sensitive button in `names`, topmost dialog first."""
        for name in names:
            for role in (*PRESS_ROLES, None):
                try:
                    return self.click_named(app, name, role=role)
                except DriverError:
                    continue
        raise DriverError(f"no primary action {list(names)!r} on screen")

    def recovery_key_value(self, app):
        """The recovery-key shape match, or None when the page shows none."""
        nodes = self.dump(app)
        self.last_nodes = nodes
        node = find_recovery_key(nodes)
        return (node.get("name") or node.get("text")) if node else None
