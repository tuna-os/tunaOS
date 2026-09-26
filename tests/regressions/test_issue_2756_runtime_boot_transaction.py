"""A boot-transaction check must not wait for, or reject, its own running job."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build_scripts/checks/e2e-runtime-checks.sh"


@pytest.mark.parametrize(
    ("state", "accepted"),
    [
        ("running", True),
        ("degraded", True),
        ("starting", True),
        ("initializing", True),
        ("maintenance", False),
        ("stopping", False),
        ("offline", False),
        ("unknown", False),
        ("", False),
        ("starting\nrunning", False),
    ],
)
def test_actual_boot_state_assertion(state, accepted):
    source = SCRIPT.read_text()
    # Run the production probe and check call together, not a copied predicate.
    block = source.split("valid_boot_state() {", 1)[1].split(
        "# bootc deployments", 1
    )[0]
    shell = r'''
set -eu
systemctl() {
    [[ "$#" = 1 && "$1" = is-system-running ]] || exit 97
    printf '%s\n' "$OBSERVED_STATE"
    [[ "$OBSERVED_STATE" = running ]]
}
emit() { printf '%s\n' "$1"; }
check() {
    description=$1
    shift
    if "$@"; then
        printf 'PASS: %s\n' "$description"
    else
        printf 'FAIL: %s\n' "$description"
        return 1
    fi
}
'''
    result = subprocess.run(
        ["bash", "-c", shell + "valid_boot_state() {" + block],
        env={**os.environ, "OBSERVED_STATE": state},
        text=True,
        capture_output=True,
        timeout=3,
    )
    assert result.returncode == (0 if accepted else 1), result.stdout + result.stderr
    assert ("PASS:" if accepted else "FAIL:") in result.stdout
    assert "system manager is in a valid boot state" in result.stdout
