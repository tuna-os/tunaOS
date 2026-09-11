"""Every variant flag the desktop contract reads must reach it in CI.

verify-desktop-experience.sh runs in two places with different plumbing:

  build time   install-desktop.sh sources build_scripts/lib.sh, which derives
               IS_ELN / IS_HUMMINGBIRD from BASE_IMAGE. Both are set.
  Desktop      reusable-build-image.yml runs the same script standalone in a
  contract     container, so nothing sources lib.sh and every flag has to be
               passed with an explicit `-e`.

The script uses those flags to tell a packaging mistake apart from a measured
property of an upstream compose. A flag that does not arrive silently reads as
false, so an exemption the script is written to apply cannot fire, and a
correctly-built image fails a check that was never meant to fail it.

Measured, 2026-09-11: the job passed IS_HUMMINGBIRD and not IS_ELN, so wahoo's
ELN codec gap -- documented in the README ("no codecs"), implemented in the
script, and pinned by tests/bats/test_eln_codec_gap.bats as ELN-only and loud --
could not fire in that job. wahoo:gnome, :cosmic and :kde all failed Desktop
contract on

    ffmpeg cannot decode h264 - a free/crippled libavcodec is installed

which skipped their Promote and read as three not-green `builds` cells for
images that had built and pushed (run 34609709028).

So the invariant is the join, not either side: whatever flags the script reads,
the job that runs it must pass. Adding a third flag to the script without
plumbing it fails here rather than on a variant's nightly.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "build_scripts" / "checks" / "verify-desktop-experience.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "reusable-build-image.yml"

# Flags the script reads that the job is NOT expected to pass, each with the
# reason. Anything else the script starts branching on has to be plumbed, which
# is the point of this file.
#
# IS_FEDORA is deliberately here rather than fixed alongside IS_ELN, because
# passing it would change nothing today. Its one use is
#
#   if [[ "${PKG_MGR:-}" == "dnf" && "${IS_FEDORA:-false}" != true && ... ]]
#
# and PKG_MGR is unset in this job for a deeper reason: the script's
# `source /run/context/build_scripts/lib.sh` is a no-op here, because the
# container mounts only the script itself, so `detected_os` never runs and the
# whole OS-detection layer is absent. The first clause is therefore already
# false and IS_FEDORA cannot affect the branch either way.
#
# That deeper gap has its own consequence -- with PKG_MGR unset the el10 family
# takes the `else` and REQUIRES cosmic-files, which tunaOS#916 says is
# best-effort there -- but fixing it means mounting lib.sh and letting
# detection run, which is a change to how this job works rather than a missing
# `-e`. Kept as a named exclusion so it stays visible instead of passing
# silently.
INERT_IN_THIS_JOB = {"IS_FEDORA"}

# Not per-variant switches at all: a test-harness path override and an
# allowlist path used by a different script.
NOT_VARIANT_FLAGS = {"TUNAOS_VERIFY_ROOT", "TUNAOS_WISHLIST_ALLOWLIST"}


def _flags_the_script_reads() -> set[str]:
    """IS_* variables the contract branches on, read from the script itself."""
    text = CONTRACT.read_text(encoding="utf-8")
    # Matches ${IS_ELN:-false} and "${IS_HUMMINGBIRD:-false}" alike.
    return {
        name
        for name in re.findall(r"\$\{(IS_[A-Z0-9_]+)(?::-[^}]*)?\}", text)
        if name not in NOT_VARIANT_FLAGS and name not in INERT_IN_THIS_JOB
    }


def _desktop_contract_step() -> str:
    """The run: body of the step that executes verify-desktop-experience.sh."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in doc["jobs"].values():
        for step in job.get("steps") or []:
            body = step.get("run") or ""
            if "verify-desktop-experience.sh" in body:
                return body
    raise AssertionError(
        "no step in reusable-build-image.yml runs "
        "verify-desktop-experience.sh - this test's premise moved"
    )


def test_the_script_actually_branches_on_variant_flags():
    """Guard the selector: a regex that matches nothing would make the real
    assertion below vacuously true (#1730)."""
    flags = _flags_the_script_reads()
    assert flags, "no IS_* flags found in the contract - the regex stopped matching"
    assert "IS_ELN" in flags and "IS_HUMMINGBIRD" in flags, (
        f"expected the two known variant flags among {sorted(flags)}"
    )


@pytest.mark.parametrize("flag", sorted(_flags_the_script_reads()))
def test_the_desktop_contract_step_passes_every_flag_the_script_reads(flag: str):
    body = _desktop_contract_step()
    assert re.search(rf"-e\s+{flag}=", body), (
        f"verify-desktop-experience.sh branches on {flag}, but the Desktop "
        f"contract step in reusable-build-image.yml does not pass it. Nothing "
        f"sources build_scripts/lib.sh in that container, so {flag} reads as "
        f"false and any exemption guarded by it cannot fire - the image fails a "
        f"check it was never meant to fail, and its Promote is skipped."
    )
