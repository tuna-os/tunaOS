"""tunaOS#1556 (lifecycle surface): the arm64 cells died before any test ran.

Run 31999953433 lost all six arm64 cells to

    Error: failed to open 2048 locks in /libpod_lock: numerical result out of range

bootc-lifecycle.yml apt-installed podman unconditionally — the exact
mixed-stack mistake reusable-build-image.yml's Gate documents ("crun: unknown
version") — and two podman builds sharing /dev/shm/libpod_lock with different
lock counts is what ERANGE looks like. Both lifecycle jobs now use the Gate's
guarded install and clear any stale lock segment.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BODY = (ROOT / ".github" / "workflows" /
        "bootc-lifecycle.yml").read_text(encoding="utf-8")


def test_podman_is_never_apt_installed_over_a_preinstalled_one() -> None:
    assert "sudo apt-get install -y --no-install-recommends podman" not in BODY
    assert BODY.count("podman already present") == 2, (
        "both lifecycle jobs must carry the guarded install"
    )


def test_stale_lock_segments_are_cleared() -> None:
    assert BODY.count("rm -f /dev/shm/libpod_lock") == 2
