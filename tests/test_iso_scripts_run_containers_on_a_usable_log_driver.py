"""ISO-build scripts must not start containers on the journald log driver.

The Kubic conmon these jobs install is built without journald support, so
any `podman run` left on podman's default log driver dies with

    [conmon:e]: Include journald in compilation path to log to systemd journal
    Error: conmon failed: exit status 1

and exit 126. `--log-driver=k8s-file` is the fix, and it is already spelled
out at the identical pair of calls in build-iso-tacklebox.sh and at
build-image-inner.sh's chunkah run (tacklebox#235).

build-iso-group.sh was a copy of that pair WITHOUT the flag, at the very
end of the script, after the ISO is already built — it exists only to read
VERSION_ID and arch for the output filename. So the pipeline built a
correct 13m39s grouped ISO and then threw it away on a metadata lookup
(job 97650065786: ">>> Tacklebox ISO complete" immediately followed by
"conmon failed").

Scoped to the scripts that build ISOs, because that is where the Kubic
conmon is installed. A script that inspects images on a stock runner is
not affected and is not the subject here.
"""

import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ISO_BUILD_SCRIPTS = ["build-iso-group.sh", "build-iso-tacklebox.sh", "build-image-inner.sh"]

# These invocations are written across several backslash-continued lines,
# with --log-driver frequently on a line of its own. Fold continuations
# before matching: a pattern that stops at the first newline reports every
# multi-line call as missing the flag, which is how the first version of
# this test "found" a bug in build-image-inner.sh that was not there.
CONTINUATION = re.compile(r"\\\n\s*")
PODMAN_RUN = re.compile(r"(?<!\w)podman run\b[^\n]*")


def _invocations(name):
    """Every `podman run` in the script, with its line number in the file.

    Continuations are folded before matching so a call spread over ten
    lines is judged as one command. The line number is recovered by
    counting how many `podman run` occurrences precede this one, then
    taking the correspondingly-numbered occurrence in the raw text --
    the two agree because folding cannot create or destroy occurrences.
    """
    raw = (SCRIPTS / name).read_text()
    folded = CONTINUATION.sub(" ", raw)

    raw_lines = []
    for i, line in enumerate(raw.splitlines(), start=1):
        if PODMAN_RUN.search(line) and not line.lstrip().startswith("#"):
            raw_lines.append(i)

    out = []
    for m in PODMAN_RUN.finditer(folded):
        line_start = folded.rfind("\n", 0, m.start()) + 1
        if folded[line_start : m.start()].lstrip().startswith("#"):
            continue
        line_no = raw_lines[len(out)] if len(out) < len(raw_lines) else -1
        out.append((line_no, m.group(0)))
    return out


CASES = [(s, n, t) for s in ISO_BUILD_SCRIPTS for n, t in _invocations(s)]


@pytest.mark.parametrize(
    "script,line,invocation",
    CASES,
    ids=[f"{s}:{n}" for s, n, _ in CASES],
)
def test_iso_scripts_run_containers_on_a_usable_log_driver(script, line, invocation):
    assert "--log-driver=" in invocation, (
        f"{script}:{line} starts a container without an explicit --log-driver. "
        f"The Kubic conmon cannot log to the journal, so this dies with "
        f"'conmon failed: exit status 1' and exit 126:\n"
        f"    {invocation.strip()[:160]}"
    )


def test_the_check_found_the_container_starts():
    """Parametrizing over an empty list is a green test that asserts nothing."""
    assert CASES, "no `podman run` found in the ISO-build scripts — detector broken"


def test_the_pattern_recognises_a_missing_flag():
    """The regex must actually distinguish the two forms it is judging."""
    bad = "podman run --rm --security-opt label=disable \"$REF\" uname -m"
    good = "podman run --rm --log-driver=k8s-file --security-opt label=disable \"$REF\" uname -m"
    assert "--log-driver=" not in PODMAN_RUN.search(bad).group(0)
    assert "--log-driver=" in PODMAN_RUN.search(good).group(0)
