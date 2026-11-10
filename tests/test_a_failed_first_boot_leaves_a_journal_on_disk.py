"""A first boot that never reaches a session must still leave evidence.

grouper:gnome run 42697802969 ignored every time-zone advance on both
legs, then Previous raised the shell ANR: dozens of captures of one
static page, then failure. The guest journal would have shown whether
Initial Setup ever started the session; with the default `auto`
storage and no /var/log/journal on the installed disk, the journal
lived only in /run and died with the VM. So the image ships a journald
drop-in with persistent storage and a size cap the smallest E2E disks
tolerate.
"""
from __future__ import annotations

import configparser
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
DROPIN = (ROOT / "system_files/usr/lib/systemd/journald.conf.d"
          / "90-tunaos-persistent.conf")
# The strict legs run on small disks; the cap must stay well under them.
MAX_BYTES = 100 * 1024 * 1024


def _journal_section() -> configparser.SectionProxy:
    assert DROPIN.is_file(), (
        f"{DROPIN.relative_to(ROOT)} is missing: without it the journal "
        "stays in /run and a failed first boot leaves no guest evidence."
    )
    parser = configparser.ConfigParser()
    parser.read(DROPIN, encoding="utf-8")
    assert "Journal" in parser, "drop-in sets nothing without a [Journal] section"
    return parser["Journal"]


def test_the_journal_survives_a_failed_first_boot():
    section = _journal_section()
    assert section.get("Storage", "").strip().lower() == "persistent", (
        "Storage must be persistent so /var/log/journal keeps the log "
        "after a boot that never reaches a session."
    )


def test_the_persistent_journal_is_size_capped():
    raw = _journal_section().get("SystemMaxUse", "").strip()
    match = re.fullmatch(r"(\d+)([KMG])?", raw, re.IGNORECASE)
    assert match, f"SystemMaxUse={raw!r} is not a plain size the cap can be checked against"
    size = int(match.group(1)) * {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}.get(
        (match.group(2) or "B").upper(), 1)
    assert 0 < size <= MAX_BYTES, (
        f"SystemMaxUse={raw!r} exceeds what the smallest E2E disks tolerate."
    )
