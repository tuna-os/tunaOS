"""hummingbird's base transaction must ask for plymouth and its script plugin.

26-packages-post.sh builds the initramfs in the base stage, before any desktop
adds packages, so the splash that draws the LUKS passphrase prompt comes only
from 10-base-packages.sh. Without plymouth the encrypted install asks on the
text console, and the strict ISO check rejects it: "strict luks cold boot asked
for the passphrase on the text console, not the branded Plymouth prompt"
(iso-builder run 45799958429, hummingbird:gnome; the installed branding check
read "plymouth is not installed; ... want theme bird").

The package requests are not caught elsewhere: the #4104 fixture supplies
plymouthd and script.so itself, and the base-package suites never name
plymouth.

Falsification: structural. Drop plymouth, plymouth-scripts or
plymouth-plugin-script from the hummingbird `dnf -y install` in
build_scripts/10-base-packages.sh, or move them to a transaction without
--skip-broken, and this test fails.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts/10-base-packages.sh"


def _hummingbird_branch() -> str:
    body = SCRIPT.read_text()
    start = body.index("if [[ $IS_HUMMINGBIRD == true ]]; then")
    end = body.index("elif [[ ${IS_ELN:-false} == true ]]; then", start)
    return body[start:end]


def _install_words() -> list[str]:
    joined = re.sub(r"\\\n\s*", " ", _hummingbird_branch())
    cmds = [line.split() for line in joined.splitlines()
            if re.match(r"\s*dnf\s+-y\s+install\b", line)]
    assert len(cmds) == 1, cmds
    return cmds[0]


def test_the_base_transaction_asks_for_the_splash():
    words = _install_words()
    for package in ("plymouth", "plymouth-scripts", "plymouth-plugin-script"):
        assert package in words, f"{package} missing from the hummingbird base transaction"
    # A broken optional request must not sink xfsprogs (see
    # test_a_broken_optional_package_cannot_sink_the_hummingbird_base.py).
    assert "--skip-broken" in words and "--skip-unavailable" in words


def test_a_missing_splash_is_warned_about_not_fatal():
    branch = _hummingbird_branch()
    guard = re.search(r"if ! rpm -q plymouth plymouth-plugin-script[^\n]*\n(.*?)\n\tfi\n", branch, re.DOTALL)
    assert guard, "no rpm -q guard for plymouth and its script plugin"
    assert "WARNING:" in guard.group(1) and "exit" not in guard.group(1)
