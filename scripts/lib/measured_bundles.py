"""The installer bundles each desktop's strict driver has measured.

A strict receipt binds the InstallerKde (etc.) Flatpak digest the live overlay
carries (`org.tunaos.live-overlay.installer`). A driver passes a run only when
that digest was measured: a strict run walked every page of the bundle and
installed. Every bootc-installer release changes the digest, so the list lives
in `measured-bundles.json`, keyed by desktop, and `scripts/measure-installer-bundle.py`
appends a digest from a run's own evidence. The driver's page-text contract
still runs on every page of every run; the digest pin never replaces it.
"""

import json
from pathlib import Path
import re

PATH = Path(__file__).with_name('measured-bundles.json')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


def load(path=PATH):
    """Return {desktop: [digest, ...]}, oldest first; refuse a malformed file."""
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected an object keyed by desktop')
    out = {}
    for desktop, entries in data.items():
        digests = []
        for entry in entries:
            digest = entry.get('digest') if isinstance(entry, dict) else None
            if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
                raise ValueError(f'{path}: {desktop}: bad digest {digest!r}')
            if not entry.get('evidence'):
                raise ValueError(f'{path}: {desktop}: {digest} names no measurement evidence')
            if digest in digests:
                raise ValueError(f'{path}: {desktop}: duplicate {digest}')
            digests.append(digest)
        out[desktop] = digests
    return out


def digests(desktop, path=PATH):
    """The measured digests of one desktop, oldest first; at least one is required."""
    found = load(path).get(desktop)
    if not found:
        raise ValueError(f'{path}: no measured bundle for {desktop}')
    return tuple(found)
