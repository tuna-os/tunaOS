"""The Manifest job must ask for the container confinement podman needs.

`podman manifest create` inside a job container decides whether it is root
by asking for CAP_SYS_ADMIN, not by asking for uid 0. Without the capability
it re-execs into a user namespace first, and docker's default seccomp profile
denies clone(CLONE_NEWUSER) to a process that lacks it:

    cannot clone: Operation not permitted
    Error: cannot re-exec process

That never surfaced because the hosted runner used to launch every job
container with `--privileged --security-opt seccomp=unconfined` of its own
accord. Runner 2.337.0 stopped. Measured on 2026-09-02 with the runner image,
the apk package set and podman (6.0.2-r2) all identical: marlin's six Manifest
jobs passed on runner 2.336.0 (run 33659564363, 18:26Z); every Manifest job
on runner 2.337.0 from 23:12Z on died on the two lines above (sailfin
33687500544, flounder 33694724467, flounder-sid 33702354589). Not one image
was promoted matrix-wide.

The workflow now states the confinement it has always run under instead of
inheriting it. This test holds that in place: the failure mode is a
`container:` block on the manifest job with no `options:` granting it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"


def _manifest_job():
    doc = yaml.safe_load(WORKFLOW.read_text())
    jobs = doc["jobs"]
    assert "manifest" in jobs, "the Manifest job moved; update this test and the CI contract"
    return jobs["manifest"]


def test_the_manifest_job_runs_in_a_job_container():
    """If someone moves it onto the runner directly, the option below is moot
    and the test should be revisited rather than silently pass."""
    job = _manifest_job()
    assert isinstance(job.get("container"), dict), (
        "the Manifest job no longer runs in a job container; if that is "
        "deliberate, delete this test with the reason in the commit message"
    )


def test_the_manifest_container_is_privileged():
    """The one flag the runner silently supplied until 2.337.0."""
    container = _manifest_job()["container"]
    options = str(container.get("options") or "")
    assert "--privileged" in options.split(), (
        "manifest.container.options must carry --privileged: podman without "
        "CAP_SYS_ADMIN re-execs into a user namespace and docker's default "
        "seccomp denies the clone (runs 33687500544, 33694724467, 33702354589)"
    )


def test_no_other_job_container_is_left_to_inherit_its_confinement():
    """The same class applies to any future `container:` job that runs podman
    or buildah. Every job container in this workflow must state options
    explicitly, so a runner default change is a diff here and not a mystery
    red night."""
    doc = yaml.safe_load(WORKFLOW.read_text())
    for name, job in doc["jobs"].items():
        container = job.get("container")
        if isinstance(container, dict):
            assert container.get("options"), (
                f"job {name!r} runs in a container with no explicit options; "
                "state the confinement it needs (see the manifest job)"
            )
