"""The Ubuntu bases must not ship a packaged account on UID 1000.

Measured, not assumed: extracting /etc/passwd from the single layer of the
pinned gurnard base
(docker.io/library/ubuntu:noble@sha256:561618e2…) yields

    ubuntu:x:1000:1000:Ubuntu:/home/ubuntu:/bin/bash

Two consequences, and the second is what surfaced it.

  THE IMAGE   the first real user an installed gurnard/grouper creates lands
              at 1001 while a passwordless phantom holds the UID every
              desktop session, flatpak permission and $XDG_RUNTIME_DIR path
              assumes.

  THE ISO     tacklebox's CustomizeLive prepends its embedded
              src/live/baseline.sh, which creates the live user with an
              unconditional `--uid 1000`. gurnard run 32484024591 died there
              on BOTH arches:

                  >>> [customize] (1/2) baseline.sh
                  useradd: UID 1000 is not unique
                  ... exit status 4

              tunaOS hit the identical bug in its own
              live-iso/common/src/customize-live.sh and fixed it by asking
              for 1000 only when free — but that script is (2/2) and never
              runs. So the two guards are not redundant: they sit on
              opposite sides of a failure that aborts the build between
              them, and a test that only knew about one would go green
              while every Ubuntu ISO stayed red.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKAROUNDS = ROOT / "build_scripts" / "01-workarounds.sh"
CUSTOMIZE_LIVE = ROOT / "live-iso" / "common" / "src" / "customize-live.sh"
BUILD_CONFIG = ROOT / ".github" / "build-config.yml"


def test_the_stock_ubuntu_account_is_removed_on_ubuntu_bases():
    text = WORKAROUNDS.read_text()
    assert "userdel" in text, "nothing removes the stock cloud account"
    block = text[text.index("IS_UBUNTU"):]
    assert "ubuntu" in block


def test_the_removal_is_gated_on_the_ubuntu_base():
    """A userdel that ran everywhere would delete whatever an unrelated base
    happens to call `ubuntu`."""
    text = WORKAROUNDS.read_text()
    guard = text.index('if [[ "${IS_UBUNTU:-false}" = true ]]; then')
    assert guard < text.index("userdel")


def test_the_removal_is_narrow_enough_to_be_safe():
    """Only the STOCK account goes. A base that renumbers it, drops it, or an
    operator who repurposed the name must be left alone rather than silently
    altered — so the UID is checked, not just the name."""
    text = WORKAROUNDS.read_text()
    guard = text[text.index('if [[ "${IS_UBUNTU:-false}" = true ]]; then'):
                 text.index("userdel")]
    assert re.search(r"id -u ubuntu\b", guard), "the account is not identified by name"
    assert re.search(r'==\s*"?1000"?', guard), "the removal does not pin UID 1000"


def test_the_account_removal_itself_must_succeed():
    """`userdel --remove` can legitimately fail on its home-directory half:
    bootc images symlink /home to a var/home that is empty in the container
    layer. Falling back to a plain userdel keeps the failure that matters
    fatal, where a blanket `|| true` would let the UID stay taken and the
    ISO keep failing with the build reported green."""
    text = WORKAROUNDS.read_text()
    assert "userdel --remove ubuntu 2>/dev/null || userdel ubuntu" in text
    fallback = text.index("|| userdel ubuntu")
    line_end = text.index("\n", fallback)
    assert "|| true" not in text[fallback:line_end]


def test_customize_live_still_asks_for_1000_only_when_free():
    """The other side of the same failure. This guard predates the fix above
    and must survive it: the two are not redundant (see the module
    docstring)."""
    text = CUSTOMIZE_LIVE.read_text()
    assert "getent passwd 1000 >/dev/null || _uid_args=(--uid 1000)" in text


def test_the_ubuntu_bases_this_applies_to_are_still_ubuntu():
    """If gurnard or grouper is ever rebased off Ubuntu the workaround stops
    applying, and this test says so instead of leaving dead code guarded by
    a flag nothing sets."""
    config = BUILD_CONFIG.read_text()
    for variant in ("gurnard", "grouper"):
        start = config.index(f"- id: {variant}\n")
        window = config[start:start + 600]
        assert "docker.io/library/ubuntu" in window, variant
