"""The ISO job's sudo calls name the variables they pass.

ubuntu-latest is Ubuntu 26.04, and its sudo is sudo-rs 0.2.13. sudo-rs ignores
`-E` and a bare `--preserve-env`:

    sudo: preserving the entire environment is not supported, '-E' is ignored

`--preserve-env=LIST` and `sudo env VAR=...` still pass variables (measured on
both runner images, hanthor/tunaos-999 run 44951232425). The amd64 ISO job ran
`sudo -E bash ./scripts/build-iso-tacklebox.sh`, so TACKLEBOX_FROM_SOURCE=1 was
dropped. tacklebox then ran from its container image instead of the host
binary, and podman nested in that image has no network (NESTED_DNS_FAIL on both
runners in the same diagnostic run). Live customize died on "Could not resolve
host: github.com": yellowfin:gnome run 44926145318 and grouper:gnome run
44926166422. Every amd64 ISO job since ubuntu-latest moved to 26.04 failed the
same way; arm64 (ubuntu-24.04-arm, classic sudo) passed.

Falsification: put `sudo -E` back on the Build Live ISO step, or drop
TACKLEBOX_FROM_SOURCE from its list, and these tests fail.
"""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/reusable-build-artifacts.yml"


def _steps():
    doc = yaml.safe_load(WORKFLOW.read_text())
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            yield step


def _step(name):
    return next(step for step in _steps() if step.get("name") == name)


def test_no_sudo_call_relies_on_preserving_the_whole_environment():
    for step in _steps():
        run = step.get("run", "")
        assert not re.search(r"\bsudo\s+-E\b", run), step["name"]
        assert not re.search(r"\bsudo\s+--preserve-env(\s|$)", run), step["name"]


def test_build_live_iso_passes_tacklebox_from_source_through_sudo():
    run = _step("Build Live ISO")["run"]
    assert "export TACKLEBOX_FROM_SOURCE=1" in run
    preserved = re.search(r"sudo --preserve-env=(\S+)", run).group(1).split(",")
    assert {"TACKLEBOX_FROM_SOURCE", "IMAGE_REGISTRY", "GITHUB_REPOSITORY_OWNER"} <= set(preserved)


def test_boot_gate_passes_the_live_marker_through_sudo():
    run = _step("Boot gate: verify ISO readiness")["run"]
    preserved = re.search(r"sudo --preserve-env=(\S+)", run).group(1).split(",")
    assert "LIVE_MARKER" in preserved
