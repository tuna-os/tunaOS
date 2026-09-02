"""A mirror that accepts the connection and stops sending must not hang a build.

dnf's transfer defaults assume an interactive user who will notice and hit
^C. In CI nobody is watching, so a connection trickling below librepo's
default `minrate` of 1000 B/s is indistinguishable from a healthy one and dnf
waits on it indefinitely.

    Build Hummingbird #66, run 32907940350, `hummingbird / gnome / linux-amd64`
      23:12:27  [13/30] pcre2-utf32-0:10.47-1.2.hum1 100% | 247.5 KiB | 00m00s
      03:00:31  ##[error]The operation was canceled.

Seventeen packages still in flight, then 3h48m without a single further line,
then the job ceiling. The cell published nothing, so Manifest failed and
Sign, Gate, Promote, Attest SBOM and the gnome ISO were all skipped.

`minrate` + `timeout` are what actually abort a stalled transfer: a
connection delivering less than minrate bytes/s for timeout seconds gets
dropped, which turns a silent wedge into an error dnf_retry can retry.

The bound belongs in /etc/dnf/dnf.conf rather than on individual call sites
because the wedge was NOT in a call this repo wraps -- it was a plain `dnf
install` of build dependencies. Only a config drop-in covers every dnf in
every downstream RUN layer.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts/10-base-packages.sh"


def body() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_the_transfer_bounds_are_written_to_dnf_conf() -> None:
    text = body()
    for setting in ("minrate=", "timeout=", "retries="):
        assert setting in text, f"{setting} is not written to /etc/dnf/dnf.conf"


def test_the_bounds_are_generous_enough_for_a_small_single_host_mirror() -> None:
    """repo.tunaos.org is one box, not a CDN.

    The point is to catch a wedge, not to fail a slow but working mirror --
    a bound tight enough to do the latter trades one broken cell for a
    flaky one, which is worse because it looks like the packages are missing.
    """
    text = body()
    minrate = int(re.search(r"minrate=(\d+)", text).group(1))
    timeout = int(re.search(r"^\s*echo 'timeout=(\d+)'", text, re.M).group(1))
    assert minrate <= 64 * 1024, (
        f"minrate={minrate} B/s would drop a mirror serving at a real but "
        "modest rate"
    )
    assert timeout >= 60, (
        f"timeout={timeout}s is short enough that a slow metadata fetch reads "
        "as a wedge"
    )


def test_the_bounds_are_set_before_the_first_package_is_installed() -> None:
    """A bound written after the install it was meant to protect is decoration.

    max_parallel_downloads already sits in this window; the guard is that a
    later refactor moving the dnf.conf block down past the base install
    silently stops covering the transaction that actually wedged.
    """
    text = body()
    bounds = text.index("minrate=")
    installs = [m.start() for m in re.finditer(r"^\s*dnf(_retry)? .*install", text, re.M)]
    assert installs, "no dnf install found — this test is no longer measuring anything"
    assert bounds < min(installs), (
        "the transfer bounds are written after the first dnf install in this "
        "script, so that install runs unbounded"
    )


def test_writing_the_bounds_is_idempotent() -> None:
    """This script reruns across chained stages; appending each time grows the
    file without bound and leaves dnf reading whichever copy it picks."""
    text = body()
    block = text[text.index("# Bound how long a single download may stall") :]
    guard = block[: block.index("fi\n")]
    assert "grep -q '^minrate'" in guard, (
        "the append is not guarded by a grep for an existing setting"
    )


def test_the_incident_that_set_these_numbers_is_recorded_next_to_them() -> None:
    text = body()
    block = text[text.index("# Bound how long a single download may stall") :][:2000]
    assert "32907940350" in block, "the run that motivated the bound is not cited"
