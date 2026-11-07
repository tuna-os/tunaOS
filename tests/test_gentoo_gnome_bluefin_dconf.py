"""guppy:gnome must compile the dconf database the bluefin payload ships.

Containerfile.gentoo's `gnome` target copies /system_files/bluefin from the
common image AFTER install-desktop.sh ran `dconf update` in the desktop stage.
That payload carries /etc/dconf/db/distro.d keyfiles and a gschema override,
so without a recompile after the COPY the Desktop contract failed with

    missing compiled dconf database: keyfiles in /etc/dconf/db/distro.d but
    /etc/dconf/db/distro is missing or empty (run dconf update)

and guppy:gnome was never promoted (run 42330408569).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY = "COPY --from=common /system_files/bluefin /"


def _gnome_stage() -> list[str]:
    text = (ROOT / "Containerfile.gentoo").read_text()
    body = text[text.index("FROM desktop AS gnome") : text.index("FROM desktop AS kde")]
    return [line for line in body.splitlines() if not line.lstrip().startswith("#")]


def test_dconf_and_schemas_compile_after_the_bluefin_copy() -> None:
    code = "\n".join(_gnome_stage())
    copy = code.index(COPY)
    after = code[copy:]
    for command in ("dconf update", "glib-compile-schemas /usr/share/glib-2.0/schemas"):
        assert command in after, f"{command!r} must run after {COPY!r}"


def test_the_compile_is_fail_closed() -> None:
    code = "\n".join(_gnome_stage())
    after = code[code.index(COPY) :]
    # A guard on `command -v dconf` would skip silently and reproduce the
    # contract failure; the compiled database is asserted instead.
    assert not re.search(r"command -v dconf", after)
    assert "test -s /etc/dconf/db/distro" in after
