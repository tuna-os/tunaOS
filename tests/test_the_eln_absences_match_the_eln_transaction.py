"""The ELN lane's prose and its dnf transaction must name the same absences.

wahoo is an early-warning lane: its base package set is installed strictly, so
a package ELN stops shipping fails the build instead of vanishing from the
image. `10-base-packages.sh` says so in as many words -- "a miss is a real ELN
regression worth failing the build on" -- and keeps a block naming each package
the EL/Fedora lists carry that ELN does not, with the measurement that
established it.

Two lists, one meaning, and nothing kept them in step. The failure mode is
quiet in both directions:

  listed absent, still installed  → the build dies on a package the file
                                    already documents as unavailable, and the
                                    next reader trusts the prose over the code.
  removed, not documented         → a package leaves the lane with no record
                                    of why, which is the "silently skipped"
                                    outcome the whole strict transaction
                                    exists to prevent.

Measured instance, 2026-09-12: ELN retired fastfetch between two wahoo runs ten
hours apart (34657968072 installed fastfetch-0:2.68.1-1.eln159; 34684438275, on
the same build tags, got "No match for argument: fastfetch"). That killed base
on both arches and took all four wahoo cells with it. Dropping the name without
recording the measurement would have left the next person to rediscover it.

So when ELN ships one of these again, moving the name back into the
transaction and deleting its entry here are the same edit -- this test fails
on either half alone.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts" / "10-base-packages.sh"

MARKER = "NOT ship are deliberately absent rather than silently skipped:"


def _eln_branch() -> str:
    """The IS_ELN branch only. The Fedora and EL10 lists are separate
    transactions against separate bases, and they legitimately carry names ELN
    does not -- reading the whole file would compare across bases."""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("elif [[ ${IS_ELN:-false} == true ]]; then")
    end = text.index("\nelif ", start + 1)
    return text[start:end]


def _documented_absences() -> list[str]:
    """Package names from the `... does NOT ship ...` block.

    Each entry looks like `#   name  — reason`, and the block ends at the first
    comment line that is not one (the glow/gum paragraph that follows).
    """
    branch = _eln_branch()
    block = branch[branch.index(MARKER):]
    names = []
    for line in block.splitlines()[1:]:
        stripped = line.strip()
        if not stripped.startswith("#"):
            break
        m = re.match(r"#\s{2,}([a-z0-9][a-z0-9._+-]*)\s+[-—]\s+\S", stripped)
        if m:
            names.append(m.group(1))
        elif stripped == "#" or re.match(r"#\s{18,}\S", stripped):
            continue          # blank spacer, or a wrapped continuation line
        else:
            break
    return names


def _strictly_installed() -> set[str]:
    """Package names in the ELN branch's strict `dnf -y install` transactions.

    Tolerant paths are excluded by construction: they carry
    --skip-unavailable, or go through install_available.
    """
    pkgs: set[str] = set()
    branch = _eln_branch()
    for m in re.finditer(r"^\tdnf -y install \\\n((?:\t\t\S.*\n)+)", branch, re.M):
        body = m.group(1)
        if "--skip-unavailable" in body:
            continue
        for line in body.splitlines():
            name = line.strip().rstrip("\\").strip()
            if name and not name.startswith("-"):
                pkgs.add(name)
    return pkgs


def test_the_absence_block_still_parses():
    """Guard both selectors: either matching nothing would make the real
    assertion vacuously true (tunaOS#1730)."""
    documented = _documented_absences()
    assert documented, (
        f"no names parsed out of the '{MARKER}' block -- its shape changed, "
        "so the assertion below is measuring nothing")
    for known in ("systemd-oomd", "just", "tailscale"):
        assert known in documented, (
            f"{known} should be a documented ELN absence; parsed {documented}")
    installed = _strictly_installed()
    assert {"podman", "flatpak"} <= installed, (
        f"the strict ELN transaction did not parse; got {sorted(installed)}")


@pytest.mark.parametrize("pkg", _documented_absences())
def test_a_documented_absence_is_not_strictly_installed(pkg: str):
    assert pkg not in _strictly_installed(), (
        f"10-base-packages.sh documents {pkg!r} as a package ELN does not "
        f"ship, but still installs it in the strict ELN transaction. The "
        f"build will fail on it every time.\n"
        f"If ELN now ships {pkg}, delete its entry from the absence block in "
        f"the same change that adds it back to the transaction -- the two "
        f"lists are one statement, and this test is what keeps them saying "
        f"the same thing."
    )
