"""The boot gates must exercise the installed image without adding CI reports."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/reusable-build-image.yml").read_text())
STEP = next(step for step in WORKFLOW["jobs"]["build_push"]["steps"] if step.get("name") == "Boot-verify image (PR gate)")
GATE = (ROOT / "scripts/corral-boot-gate.sh").read_text()


@pytest.mark.parametrize("variant,flavor", [("yellowfin", "gnome"), ("bonito-rawhide", "gnome-nvidia"), ("flounder-sid", "kde")])
def test_pr_gate_boots_the_variant_it_built(tmp_path, variant, flavor):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    sudo = bindir / "sudo"
    sudo.write_text('#!/bin/bash\nexec "$@"\n')
    boot = scripts / "corral-boot-gate.sh"
    boot.write_text('''#!/bin/bash
set -euo pipefail
[[ "$1" == "localhost/${IMAGE_VARIANT}:${DEFAULT_TAG}" ]]
[[ "$2" == verify-out && -d verify-out ]]
printf '%s\\n' "$*" > boot-input
exit "${BOOT_RC:-0}"
''')
    for path in (sudo, boot):
        path.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "IMAGE_VARIANT": variant, "DEFAULT_TAG": flavor}
    proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", STEP["run"]], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "boot-input").read_text().startswith(f"localhost/{variant}:{flavor} verify-out")
    proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", STEP["run"]], cwd=tmp_path, env={**env, "BOOT_RC": "24"}, capture_output=True, text=True)
    assert proc.returncode == 24, "a failed boot was swallowed"


def test_ci_does_not_boot_guests_through_unprotected_corral_path():
    """Every CI guest is booted with the opt-out on its kernel command line.

    `corral create` has no install-time kernel argument, so a guest it boots
    can send a report before anything over SSH can stop it. The gates go
    through scripts/corral-boot-gate.sh, which installs tunaos.countme=0 into
    the boot entry, or through iso-e2e.sh, which sets the SMBIOS marker.
    """
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        parsed = yaml.safe_load(workflow.read_text())
        for job in parsed.get("jobs", {}).values():
            for step in job.get("steps", []):
                run = step.get("run", "")
                assert "corral create " not in run, f"{workflow.name}: unprotected Corral guest creation"
                assert "corral vmtest" not in run, f"{workflow.name}: Corral guest booted outside scripts/corral-boot-gate.sh"
    assert "pull_request" in STEP["if"]
    assert not STEP.get("continue-on-error", False)
    assert "--karg tunaos.countme=0" in GATE
    boots = re.findall(r'"\$CORRAL" vmtest (?!--help)', GATE)
    assert len(boots) == 1, "every guest the gate boots must take the same kernel arguments"
    disk_boot = (ROOT / "scripts/iso-e2e.sh").read_text()
    start = disk_boot.index("boot_disk_image()")
    end = disk_boot.index("\n}", start)
    assert "-smbios type=1,product=tunaos-countme-disabled" in disk_boot[start:end]


def test_both_gates_run_the_same_harness():
    gate_steps = WORKFLOW["jobs"]["verify_boot"]["steps"]
    runs = [step.get("run", "") for step in gate_steps]
    assert any("scripts/corral-boot-gate.sh" in run for run in runs)
    assert "scripts/corral-boot-gate.sh" in STEP["run"]


def test_pr_boot_gate_remains_declared_in_green_contract():
    criteria = yaml.safe_load((ROOT / ".github/green-criteria.yml").read_text())
    # The contract loader accepts the repository's top-level criteria list.
    boots = next(item for item in criteria["criteria"] if item["id"] == "boots")
    assert any(gate.get("jobs", {}).get("build_push") == STEP["name"] for gate in boots["gates"])
