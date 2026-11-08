"""tunaOS#4446: an alias sshd unit must not apply the host-key gate.

grouper:gnome strict qualification failed "SSH host keys were generated"
(16 pass / 1 fail) on installed systems whose only TCP listeners were DNS.
The live serial from iso-builder run 42488951825 captured the gate applying
on `is-enabled=alias is-active=inactive`: on Debian/Ubuntu, sshd.service is
an alias of ssh.service, and `systemctl is-enabled` exits 0 for aliases. An
alias is a name, not an enabled unit, and the image correctly ships sshd off
with no host keys — so the gate must stay off.

Falsification: behavioural — the test extracts the real gate loop from
build_scripts/checks/e2e-runtime-checks.sh and runs it under a stub
systemctl replaying the measured grouper state. Revert the gate to bare
exit-status matching and the alias case applies the gate (test fails).
"""

from __future__ import annotations

import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ROOT / "build_scripts" / "checks" / "e2e-runtime-checks.sh"

UNITS = ("sshd.service", "ssh.service", "sshd.socket", "ssh.socket")


def _gate_snippet() -> str:
    """Extract the sshd gate loop verbatim (from `_sshd_on=0` to its `done`)."""
    lines = CHECKS.read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if l == "_sshd_on=0")
    end = next(i for i in range(start, len(lines)) if lines[i] == "done")
    body = "\n".join(lines[start : end + 1])
    assert "sshd.service" in body and "is-enabled" in body
    return body + '\nprintf "_sshd_on=%s\\n" "$_sshd_on"\n'


def _run_gate(states: dict[str, tuple[str, int]], active: str = "inactive") -> str:
    """Run the extracted gate with a stub systemctl replaying given states.

    states maps unit -> (is-enabled output, is-enabled exit code).
    """
    stub = textwrap.dedent("""\
        #!/bin/bash
        # Stub replays canned `systemctl` answers from the environment.
        if [[ "$1" == "is-enabled" ]]; then
            key="STATE_${2//[.-]/_}"
            echo "${!key%%:*}"
            exit "${!key##*:}"
        elif [[ "$1" == "is-active" ]]; then
            echo "%s"
            [[ "%s" == "active" ]]
            exit $?
        fi
        echo "unexpected systemctl call: $*" >&2
        exit 99
        """ % (active, active))
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        stub_path = Path(tmp) / "systemctl"
        stub_path.write_text(stub, encoding="utf-8")
        stub_path.chmod(stub_path.stat().st_mode | stat.S_IXUSR)
        env = dict(os.environ, PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}")
        for unit in UNITS:
            out, code = states.get(unit, ("disabled", 1))
            env[f"STATE_{unit.replace('.', '_').replace('-', '_')}"] = f"{out}:{code}"
        proc = subprocess.run(
            ["bash", "-c", _gate_snippet()],
            capture_output=True, text=True, env=env, timeout=60,
        )
    assert proc.returncode == 0, f"gate snippet failed: {proc.stderr}"
    return proc.stdout


def test_alias_sshd_does_not_apply_the_gate():
    """The measured grouper state: sshd.service is an alias, nothing active."""
    out = _run_gate({"sshd.service": ("alias", 0)})
    assert "_sshd_on=0" in out
    assert "gate applies" not in out


def test_enabled_sshd_still_applies_the_gate():
    """Positive control: a genuinely enabled unit (dev ISO) applies the gate."""
    out = _run_gate({"ssh.service": ("enabled", 0)})
    assert "_sshd_on=1" in out
    assert "gate applies via ssh.service" in out


def test_active_sshd_applies_the_gate_without_enablement():
    """Positive control: a running daemon applies the gate even if disabled."""
    out = _run_gate({}, active="active")
    assert "_sshd_on=1" in out
