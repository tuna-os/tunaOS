"""Per-page screenshots of a real install, in the walkthrough layout.

tuna-os/installer `tools/walkthrough/render.py` turns a directory of
`<page-id>.png` and a `captures.json` into a numbered walkthrough with
captions. Its own pictures come from the mock daemon; this module writes the
same layout from a real install in the VM, so each green run can publish a
walkthrough of a real install as an artifact.

Rules (agreed with the owner of this harness):

- Only the page ids of the installer's flow spec (shared/flow/screens.yaml),
  plus its `--state` suffixes. A page the harness cannot name is skipped.
- Never the recovery-key page, in any state: a real key of a real disk must
  not reach an artifact, and a blurred key can still leak.
- An export never changes a stage result or the exit code: each failure is
  one line on stderr, and the run goes on.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

# The page ids of shared/flow/screens.yaml (order).
SPEC_IDS = (
    "requirements", "try-or-install", "language", "keyboard", "timezone", "network",
    "prerelease", "eula", "rst", "disk", "wipe-or-free", "encryption", "account",
    "confirm", "install", "recovery-key", "handoff", "done",
)

# Never exported, in any state.
SECRET_PAGES = ("recovery-key",)

# The Page enum of atspi_match (its values) to a spec id.
PAGE_IDS = {
    "disk": "disk",
    "disk-confirmation": "confirm",
    "install-confirmation": "confirm",
    "progress": "install",
    "recovery-key": "recovery-key",
    "complete": "done",
    "failure": "done--failed",
}

# The title of a native step ("Step N of M · <title>") to a spec id. The
# same headings as tools/walkthrough/flows.py in tuna-os/installer.
HEADINGS = (
    ("requirements", r"(System )?requirements"),
    ("try-or-install", r"Try or install|Welcome( to .*)?"),
    ("language", r"Language"),
    ("keyboard", r"Keyboard( layout)?"),
    ("timezone", r"Time ?zone"),
    ("network", r"Network"),
    ("prerelease", r"Disclaimer"),
    ("eula", r"Terms of use"),
    ("rst", r"Intel RST"),
    ("disk", r"Target disk|Disk( selection)?|Select a disk|Destination"),
    ("wipe-or-free", r"Existing data( found)?"),
    ("encryption", r"(Disk )?encryption|Disk passphrase"),
    ("account", r"(User )?account|Your account|Create your account"),
    ("confirm", r"Confirm( installation)?"),
    ("install", r"Installing.*|Installation"),
    ("recovery-key", r"(Back up )?recovery key"),
    ("handoff", r"Handoff"),
    ("done", r"Done|Finished|Installation complete!?"),
)

STEP_RE = re.compile(r"^\s*Step \d+ of \d+\s*\W+\s*(?P<title>.+?)\s*$", re.IGNORECASE)


def page_id(page=None, heading=None):
    """The spec id for a Page value or a native step heading; None if unknown."""
    if page is not None:
        value = getattr(page, "value", page)
        if value in PAGE_IDS:
            return PAGE_IDS[value]
    if heading:
        m = STEP_RE.match(heading)
        title = (m.group("title") if m else heading).strip()
        for pid, pattern in HEADINGS:
            if re.fullmatch(pattern, title, re.IGNORECASE):
                return pid
    return None


def exportable(pid):
    """Whether a page id may go into the exported set."""
    if not pid:
        return False
    base = pid.split("--", 1)[0]
    return base in SPEC_IDS and base not in SECRET_PAGES


class Exporter:
    """Copies the first screenshot of each page into `<root>/<frontend>/`."""

    def __init__(self, root, frontend, run="e2e"):
        self.dir = Path(root) / frontend
        self.frontend = frontend
        self.run = run
        self.pages = {}

    def shot(self, png, page=None, heading=None, headings=()):
        """Record `png` for the page, once. Never raises."""
        try:
            pid = page_id(page, heading)
            if not exportable(pid) or pid in self.pages:
                return None
            self.dir.mkdir(parents=True, exist_ok=True)
            name = f"{pid}.png"
            shutil.copyfile(png, self.dir / name)
            self.pages[pid] = {"page": pid.split("--", 1)[0], "file": name, "run": self.run,
                               "headings": [h for h in headings if h][:4]}
            self._write()
            return pid
        except Exception as exc:  # noqa: BLE001 - an export never stops a run
            print(f"walkthrough export: {exc}", file=sys.stderr)
            return None

    def _write(self):
        data = {"frontend": self.frontend, "variant": "", "pages": self.pages, "errors": []}
        tmp = self.dir / "captures.json.tmp"
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.dir / "captures.json")
