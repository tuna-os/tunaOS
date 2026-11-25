"""The Secure Boot key is readable only in the `secure-boot-signing` environment.

GitHub gives an environment secret only to a job that names the environment,
and the environment admits only the branches in its branch policy. A workflow
on any other branch gets no key. That holds only while each job that reads
the key names the environment, so this test fails when a workflow reads
`TUNAOS_SB_KEY` or `TUNAOS_SB_CERT` in any other place.

Accepted forms:

- a job with steps whose `environment` is the fixed name, or the expression
  below (the name on main, empty on every other ref, so that a pull request
  or a branch dispatch still runs, with no environment and no key). This
  repository signs from main only;
- a `uses:` job that passes the secret by name to a local reusable workflow
  in which each job that reads the secret names the environment. A `uses:`
  job cannot name an environment itself.

tuna-os/tromso and tuna-os/brussels hold the same test.
"""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
ENVIRONMENT = "secure-boot-signing"
SECRETS = ("TUNAOS_SB_KEY", "TUNAOS_SB_CERT")
CONDITIONAL = "${{ github.ref == 'refs/heads/main' && 'secure-boot-signing' || '' }}"
# GitHub ignores the case of a secret name.
READ = re.compile(r"secrets\.(?:%s)\b" % "|".join(SECRETS), re.IGNORECASE)
# A reusable workflow of this repository, at the commit of the caller.
LOCAL = re.compile(r"[.$]/\.github/workflows/([\w.-]+)")


def _workflows():
    """Each workflow file: its name, its text with no comment lines, its YAML."""
    paths = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    return {path.name: _parse(path.read_text()) for path in paths}


def _parse(text):
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return code, yaml.safe_load(text)


def _in_environment(job):
    environment = job.get("environment")
    if isinstance(environment, dict):
        environment = environment.get("name")
    return environment in (ENVIRONMENT, CONDITIONAL)


def _reads(node):
    return len(READ.findall(yaml.safe_dump(node)))


def _offences(workflows):
    offences = []
    for filename, (code, workflow) in workflows.items():
        # A wildcard read gives every secret, the key included.
        if re.search(r"toJSON\(\s*secrets\s*\)|secrets\s*\[", code, re.IGNORECASE):
            offences.append(f"{filename}: reads the secrets context as a whole")
        jobs = workflow.get("jobs") or {}
        for name, job in jobs.items():
            if job.get("secrets") == "inherit":
                offences.append(f"{filename}: job {name} passes every secret (inherit)")
                continue
            if not _reads(job):
                continue
            if "uses" not in job:
                if not _in_environment(job):
                    offences.append(f"{filename}: job {name} reads the key outside {ENVIRONMENT}")
                continue
            # A caller: only a by-name pass to a local reusable workflow.
            passed = job.get("secrets") or {}
            exact = {key: "${{ secrets.%s }}" % key for key in SECRETS if key in passed}
            if _reads(job) != len(exact) or any(passed[key] != exact[key] for key in exact):
                offences.append(f"{filename}: job {name} does more than pass the key by name")
                continue
            local = LOCAL.fullmatch(job["uses"])
            if not local:
                offences.append(f"{filename}: job {name} passes the key to {job['uses']}")
                continue
            _, callee = workflows.get(local[1], ("", {}))
            readers = [called for called in (callee.get("jobs") or {}).values() if _reads(called)]
            if not readers or not all(
                "uses" not in called and _in_environment(called) for called in readers
            ):
                offences.append(
                    f"{filename}: job {name} passes the key to a job outside {ENVIRONMENT}"
                )
        # A read outside `jobs:` (a workflow-level `env:`) reaches every job.
        if len(READ.findall(code)) != sum(_reads(job) for job in jobs.values()):
            offences.append(f"{filename}: reads the key outside a job")
    return offences


def test_the_key_is_read_only_in_the_signing_environment():
    assert not _offences(_workflows())


STEP = "    steps:\n      - run: 'true'\n        env:\n          K: ${{ secrets.TUNAOS_SB_KEY }}\n"
PASS = "    secrets:\n      TUNAOS_SB_KEY: ${{ secrets.TUNAOS_SB_KEY }}\n"
LEAKS = {
    "no environment": "jobs:\n  a:\n    runs-on: x\n" + STEP,
    "other case": "jobs:\n  a:\n    runs-on: x\n" + STEP.replace("TUNAOS_SB_KEY", "tunaos_sb_key"),
    "other environment": "jobs:\n  a:\n    runs-on: x\n    environment: publish\n" + STEP,
    "wider expression": "jobs:\n  a:\n    runs-on: x\n"
    "    environment: ${{ github.ref != '' && 'secure-boot-signing' || '' }}\n" + STEP,
    "workflow env": "env:\n  K: ${{ secrets.TUNAOS_SB_CERT }}\njobs:\n  a:\n    runs-on: x\n"
    "    steps:\n      - run: 'true'\n",
    "inherit": "jobs:\n  a:\n    uses: ./.github/workflows/bad.yml\n    secrets: inherit\n",
    "whole context": "jobs:\n  a:\n    runs-on: x\n    steps:\n      - run: 'true'\n"
    "        env:\n          K: ${{ toJSON(secrets) }}\n",
    "outside repository": "jobs:\n  a:\n    uses: o/r/.github/workflows/b.yml@main\n" + PASS,
    "callee outside": "jobs:\n  a:\n    uses: $/.github/workflows/bad.yml\n" + PASS,
    "more than a pass": "jobs:\n  a:\n    uses: ./.github/workflows/good.yml\n    secrets:\n"
    "      OTHER: ${{ secrets.TUNAOS_SB_KEY }}\n",
}
GOOD = "jobs:\n  a:\n    runs-on: x\n    environment: secure-boot-signing\n" + STEP
ACCEPTED = {
    "fixed name": GOOD,
    "conditional name": "jobs:\n  a:\n    runs-on: x\n    environment: %s\n" % CONDITIONAL + STEP,
    "pass to a job in the environment": "jobs:\n  a:\n    uses: $/.github/workflows/good.yml\n" + PASS,
    "a comment": "# secrets.TUNAOS_SB_KEY\njobs:\n  a:\n    runs-on: x\n"
    "    steps:\n      - run: 'true'\n",
}


def _check(text):
    callees = {"bad.yml": _parse(LEAKS["no environment"]), "good.yml": _parse(GOOD)}
    found = _offences({"case.yml": _parse(text), **callees})
    return [offence for offence in found if offence.startswith("case.yml")]


def test_the_check_finds_each_read_outside_the_environment():
    for label, text in LEAKS.items():
        assert _check(text), label
    for label, text in ACCEPTED.items():
        assert not _check(text), label


def test_the_document_says_where_the_key_is():
    text = (REPO / "installer-medium" / "docs" / "SECURE-BOOT.md").read_text()
    assert ENVIRONMENT in text
    assert "tunaos-secure-boot-lockdown.sh" in text
