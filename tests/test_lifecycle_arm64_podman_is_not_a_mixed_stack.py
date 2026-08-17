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


# The ISO surface — where #1556 was originally filed. Lifecycle run
# 32040213366 validated the guard on all 53 arm64 legs (zero mixed-stack or
# lock-init failures), so the same treatment applies to the workflow whose
# arm64 tacklebox pre-pull first showed the signature.
ARTIFACTS = (ROOT / ".github" / "workflows" /
             "reusable-build-artifacts.yml").read_text(encoding="utf-8")


def test_iso_surface_carries_the_same_guard() -> None:
    assert "podman already present" in ARTIFACTS
    assert "rm -f /dev/shm/libpod_lock" in ARTIFACTS
    # The one unconditional install line this workflow used to carry.
    assert "apt-get install -y just podman" not in ARTIFACTS
