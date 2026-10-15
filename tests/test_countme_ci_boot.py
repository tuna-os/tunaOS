"""The PR boot gate must exercise the installed image without adding CI reports."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/reusable-build-image.yml").read_text())
STEP = next(step for step in WORKFLOW["jobs"]["build_push"]["steps"] if step.get("name") == "Boot-verify image (PR gate)")


@pytest.mark.parametrize("variant,flavor", [("yellowfin", "gnome"), ("bonito-rawhide", "gnome-nvidia"), ("flounder-sid", "kde")])
def test_pr_gate_builds_and_boots_the_same_variant_disk(tmp_path, variant, flavor):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    just = bindir / "just"
    just.write_text('''#!/bin/bash
set -euo pipefail
[[ "$1" == qcow2 ]]
[[ "$2" == "localhost/${IMAGE_VARIANT}:${DEFAULT_TAG}" ]]
# Match the repository builder's image-ref basename -> output-name rule.
name="${2##*/}"
name="${name%%:*}"
touch "${name}.qcow2"
printf '%s\\n' "$2" > build-input
exit "${BUILD_RC:-0}"
''')
    sudo = bindir / "sudo"
    sudo.write_text('#!/bin/bash\nexec "$@"\n')
    boot = scripts / "iso-e2e.sh"
    boot.write_text('''#!/bin/bash
set -euo pipefail
[[ "$1" == "${IMAGE_VARIANT}.qcow2" && -f "$1" ]]
[[ "$2" == --disk && "$3" == --output && "$4" == verify-out ]]
printf '%s\\n' "$*" > boot-input
exit "${BOOT_RC:-0}"
''')
    for path in (just, sudo, boot):
        path.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "IMAGE_VARIANT": variant, "DEFAULT_TAG": flavor}
    proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", STEP["run"]], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "build-input").read_text().strip() == f"localhost/{variant}:{flavor}"
    assert (tmp_path / "boot-input").read_text().startswith(f"{variant}.qcow2 --disk --output verify-out")
    for name, code in (("BUILD_RC", "23"), ("BOOT_RC", "24")):
        proc = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", STEP["run"]], cwd=tmp_path, env={**env, name: code}, capture_output=True, text=True)
        assert proc.returncode == int(code), f"{name} failure was swallowed"


def test_ci_does_not_boot_guests_through_unprotected_corral_path():
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        parsed = yaml.safe_load(workflow.read_text())
        for job in parsed.get("jobs", {}).values():
            for step in job.get("steps", []):
                run = step.get("run", "")
                assert "corral create " not in run, f"{workflow.name}: unprotected Corral guest creation"
    assert "pull_request" in STEP["if"]
    assert not STEP.get("continue-on-error", False)
    disk_boot = (ROOT / "scripts/iso-e2e.sh").read_text()
    start = disk_boot.index("boot_disk_image()")
    end = disk_boot.index("\n}", start)
    assert "-smbios type=1,product=tunaos-countme-disabled" in disk_boot[start:end]


def test_pr_boot_gate_remains_declared_in_green_contract():
    criteria = yaml.safe_load((ROOT / ".github/green-criteria.yml").read_text())
    # The contract loader accepts the repository's top-level criteria list.
    boots = next(item for item in criteria["criteria"] if item["id"] == "boots")
    assert any(gate.get("jobs", {}).get("build_push") == STEP["name"] for gate in boots["gates"])
