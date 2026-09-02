"""A boot gate on a runner that cannot boot.

live-iso-bootc.yml built the ISO and then tried to boot it:

    ==> Booting ./skipjack-gnome-10-x86_64.iso in QEMU (headless, KVM)...
    Could not access KVM kernel module: No such file or directory
    qemu-system-x86_64: failed to initialize kvm: No such file or directory

(runs 32690010127 and 32696543980, both AFTER the ISO built successfully.)

That was never going to work. The job runs on `runs-on=.../runner=build-amd64`,
whose families in .github/runs-on.yml are ["c6a", "c6i", "c5a", "c5"] --
ordinary EC2 instances. EC2 exposes /dev/kvm only on `.metal` instance types.
So the step could not have passed on any run, on any commit, ever. It is not
capacity flakiness to retry around, and nothing in this repository can change
it.

The five boot/screenshot steps were therefore removed rather than repaired:
installer-smoke.yml already boots the ISO on `ubuntu-latest` -- which does
provide KVM -- SSHes into the guest, asserts the compositor and installer
frontend, drives the installer through its screens and captures the session
journal, across all five flavors instead of one hardcoded flavor.

What is worth keeping is the RULE, because the next person to add a QEMU step
will pick a runner the same way. Every job in this repository that touches KVM
must run on a GitHub-hosted `ubuntu-*` runner. Today four do and all four are
correct; the one that was not is gone.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RUNS_ON = ROOT / ".github" / "runs-on.yml"


def kvm_jobs():
    """(workflow, job, runs-on) for every job whose body reaches for KVM."""
    found = []
    for f in sorted(WORKFLOWS.glob("*.y*ml")):
        text = f.read_text(encoding="utf-8")
        if "accel=kvm" not in text and "/dev/kvm" not in text:
            continue
        doc = yaml.safe_load(text)
        for name, job in (doc.get("jobs") or {}).items():
            body = yaml.dump(job)
            if "accel=kvm" in body or "/dev/kvm" in body:
                found.append((f.name, name, job.get("runs-on")))
    return found


def test_the_sweep_examines_something():
    """A rule that matches no job passes for the wrong reason."""
    jobs = kvm_jobs()
    assert jobs, "no KVM-using job found at all; this file would assert nothing"


def test_every_kvm_job_runs_on_a_github_hosted_runner():
    offenders = [
        (wf, job, runner)
        for wf, job, runner in kvm_jobs()
        if not (isinstance(runner, str) and runner.startswith("ubuntu-"))
    ]
    assert not offenders, (
        "these jobs use KVM on a runner that cannot provide /dev/kvm "
        f"(EC2 exposes it only on .metal instance types): {offenders}"
    )


def test_the_ec2_pool_really_cannot_supply_kvm():
    """Pin the premise. If a .metal family is ever added, this test should be
    revisited deliberately rather than the rule above silently over-applying."""
    cfg = yaml.safe_load(RUNS_ON.read_text(encoding="utf-8"))
    # The families live under a top-level `runners:` key. Reading cfg.values()
    # directly finds nothing and makes every assertion below vacuous, which is
    # how this test first "passed" -- hence the emptiness guard.
    families = []
    for runner in (cfg.get("runners") or {}).values():
        if isinstance(runner, dict) and "family" in runner:
            families.extend(runner["family"])
    assert families, "no runner families parsed from runs-on.yml"
    metal = [f for f in families if str(f).endswith(".metal") or "metal" in str(f)]
    assert not metal, (
        f"runs-on.yml now offers a metal family {metal}; a KVM job could "
        "legitimately run there, so revisit test_every_kvm_job_runs_on_a_"
        "github_hosted_runner rather than leaving it as a blanket ban"
    )


def test_live_iso_bootc_no_longer_boots_anything():
    """The specific removal, so it cannot quietly come back on this runner."""
    doc = yaml.safe_load((WORKFLOWS / "live-iso-bootc.yml").read_text(encoding="utf-8"))
    body = yaml.dump(doc["jobs"]["build"])
    assert "accel=kvm" not in body
    assert "qemu-system" not in body
    names = [s.get("name", "") for s in doc["jobs"]["build"]["steps"]]
    assert not any("Boot ISO" in n for n in names), names
    # It must still do the thing it CAN do, or removing the gate just
    # removed the job's reason to exist.
    assert any("Build Live ISO" in n for n in names), names
    assert any("Upload Artifact" in n for n in names), names
