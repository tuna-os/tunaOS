"""One broken optional package must not take the hummingbird base down with it.

10-base-packages.sh installs the hummingbird base set in one dnf transaction
and then asserts, by `rpm -q`, that xfsprogs (mandatory: bootc install execs
mkfs.xfs from inside the image) arrived, while flatpak (not yet publishable,
tunaOS#1397) is only warned about.

`--skip-unavailable` covers a package no repo carries. It does not cover a
package a repo carries but cannot resolve, and dnf's answer to one such
request is to refuse the WHOLE transaction. Measured 2026-09-03, run
33699113444, both arches: tunaos-hummingbird began serving
flatpak-1.17.3-1.bfin1 built against fuse3 3.18 (libfuse3.so.4), the pinned
base ships fuse3-libs 3.16.2 (libfuse3.so.3) and a grub2-tools-minimal that
still requires the old soname (measured against both repodata on 2026-09-03:
public-hummingbird carries fuse3-libs 3.18.2 and no grub2-tools-minimal;
tunaos-hummingbird carries flatpak and xfsprogs and no fuse3). dnf reported
flatpak as the problem, installed nothing, and the build died at the xfsprogs
guard with a message about xfsprogs.

The transaction must carry `--skip-broken` alongside `--skip-unavailable`,
so the optional request is dropped and the mandatory one lands; the rpm -q
guards remain the arbiter of what was mandatory.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts/10-base-packages.sh"


def _hummingbird_install_command() -> str:
    """The single `dnf ... install` inside the IS_HUMMINGBIRD branch, with its
    line continuations joined."""
    body = SCRIPT.read_text()
    start = body.index("if [[ $IS_HUMMINGBIRD == true ]]; then")
    end = body.index("elif [[ ${IS_ELN:-false} == true ]]; then", start)
    branch = body[start:end]
    joined = re.sub(r"\\\n\s*", " ", branch)
    cmds = [line.strip() for line in joined.splitlines()
            if re.match(r"\s*dnf\s+-y\s+install\b", line)]
    assert len(cmds) == 1, f"expected exactly one dnf install in the hummingbird branch, found {cmds}"
    return cmds[0]


def test_the_hummingbird_transaction_skips_broken_as_well_as_unavailable():
    cmd = _hummingbird_install_command()
    assert "--skip-unavailable" in cmd.split()
    assert "--skip-broken" in cmd.split(), (
        "without --skip-broken one unresolvable optional package (flatpak, "
        "run 33699113444) refuses the whole transaction, xfsprogs included"
    )


def test_flatpak_and_xfsprogs_share_that_transaction():
    """The failure mode needs both in one request: the optional one breaks,
    the mandatory one is collateral. If they are ever split into separate
    transactions this test should be rewritten, not deleted."""
    cmd = _hummingbird_install_command()
    words = cmd.split()
    assert "flatpak" in words and "xfsprogs" in words


def test_the_mandatory_guard_still_decides():
    """--skip-broken must not turn a skipped xfsprogs into a silent pass; the
    rpm -q guard is what makes the miss fatal, and it has to stay."""
    body = SCRIPT.read_text()
    assert re.search(r"if ! rpm -q xfsprogs >/dev/null 2>&1; then\s*\n\s*echo \"ERROR: xfsprogs did not install", body)
    assert re.search(r"if ! rpm -q flatpak >/dev/null 2>&1; then\s*\n\s*echo \"WARNING: flatpak did not install", body)
