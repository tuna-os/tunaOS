"""fishermand mock scenarios for the frontend unit-level test hook.

The mock daemon lives in tuna-os/fisherman (PR #513, mock mode only: it
touches no disk, TPM or power state). The e2e in run_e2e.py uses the REAL
stack; this module only names the scenarios a frontend unit test may start
the mock with, from shared/flow/screens.yaml `mock_scenarios`. One name,
one reach list, no behavior of its own.
"""

from __future__ import annotations

# Scenario names the mock daemon must offer (shared/flow/screens.yaml).
SCENARIOS = (
    "happy-tpm",
    "happy-no-tpm",
    "existing-data",
    "no-free-space",
    "conflicting-label",
    "disk-too-small",
    "no-disks",
    "hotplug",
    "rst-present",
    "requirements-ram",
    "requirements-cpu",
    "requirements-uefi",
)


def mock_command(scenario, socket_dir="/run/fisherman-e2e"):
    """Command starting fishermand in mock mode for one scenario."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown mock scenario {scenario!r}")
    return [
        "fishermand",
        "--mock",
        f"--mock-scenario={scenario}",
        f"--socket-dir={socket_dir}",
    ]
