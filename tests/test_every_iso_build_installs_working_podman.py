"""A job that builds an ISO must first install a podman that can commit one.

The runner images ship podman 5.8.4, whose commit of a live-customized
rootfs wedges (#1893). Every ISO-building job in this repository works
around it the same way -- add the Kubic libcontainers apt source and
reinstall podman from it -- and a job that skips that step does not fail
quickly or loudly. It hangs in `podman commit` until something outside it
gives up: tacklebox's 600s bound if the pin has one, the job timeout if
not.

`publish-iso-groups.yml` skipped it. Combined with a tacklebox pin from
before the bound existed, its build job had no upper bound short of the
360-minute Actions default, and no grouped ISO has ever reached the
bucket -- `albacore-latest.iso` is 404 while the legacy pipeline's
`albacore-gnome-latest.iso` is 200.

This is a necessary condition, not a sufficient one, and the test claims
only the former: `iso-e2e.yml` does install the Kubic podman and its
commit still ran past tacklebox's 600s bound on a GitHub-hosted runner
(job 97638514487). Passing this test does not mean a job can build an
ISO; failing it means it certainly cannot.

Detection is by what a job RUNS, not by what it is called, so a new
ISO-building workflow is covered the day it is added.
"""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))

# The commands that drive tacklebox into a live-customize + commit.
BUILDS_AN_ISO = re.compile(r"\bjust\s+(iso|iso-group)\b|\bbuild-iso(-group)?\.sh\b")
INSTALLS_KUBIC_PODMAN = re.compile(r"devel:/kubic:/libcontainers")


def _job_shell(job):
    return "\n".join(
        str(s.get("run", "")) for s in (job.get("steps") or []) if isinstance(s, dict)
    )


def _cases():
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text()) or {}
        for job_id, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict) or not job.get("steps"):
                continue
            shell = _job_shell(job)
            if BUILDS_AN_ISO.search(shell):
                yield wf.name, job_id, shell


CASES = list(_cases())


@pytest.mark.parametrize(
    "workflow,job_id,shell",
    CASES,
    ids=[f"{w}:{j}" for w, j, _ in CASES],
)
def test_every_iso_build_installs_working_podman(workflow, job_id, shell):
    assert INSTALLS_KUBIC_PODMAN.search(shell), (
        f"{workflow} job '{job_id}' runs an ISO build but never installs the "
        f"Kubic podman. The runner image's podman 5.8.4 wedges in the "
        f"post-customize commit (#1893), and the job will hang rather than "
        f"fail."
    )


def test_the_check_found_the_iso_builds():
    """Parametrizing over an empty list is a green test that asserts nothing."""
    names = {w for w, _, _ in CASES}
    assert names, "no workflow appears to build an ISO — the detector is broken"
