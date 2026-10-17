"""tunaOS#3298: gurnard images shipped shared SSH host keys.

Ubuntu noble's openssh-server postinst creates host keys in the image but the
package ships ssh.service without sshd-keygen.service. The cleanup therefore
warned and retained one private identity for every gurnard installation.

These tests run the real cleanup block against a noble-shaped scratch image,
model the generated unit's missing-key conditions and SSH dependency, and run
its ssh-keygen command against a machine root. They also exercise the fatal
branch when neither a distro nor TunaOS generator can be installed.

Falsification: behavioural. Restore the old no-generator warning branch and
test_noble_keys_are_removed_and_regenerated retains the baked keys; remove the
fatal fallback and test_keys_without_any_generator_fail_the_build returns zero.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLEANUP = ROOT / "build_scripts/99-cleanup.sh"
UNIT_DIR = "/usr/lib/systemd/system"
GENERATOR = f"{UNIT_DIR}/tunaos-ssh-host-keygen.service"
SSH_DROPIN = f"{UNIT_DIR}/ssh.service.d/10-tunaos-host-keygen.conf"
KEY_TYPES = ("ed25519", "ecdsa", "rsa")


def _ssh_block() -> str:
    """Move the cleanup's absolute image paths under $SCRATCH."""
    text = CLEANUP.read_text()
    start = text.index("if compgen -G '/etc/ssh/ssh_host_*'")
    end = text.index("\nfi\n", start) + len("\nfi\n")
    out, in_heredoc = [], False
    for line in text[start:end].splitlines():
        if in_heredoc:
            out.append(line)
            in_heredoc = line != "EOF"
            continue
        line = line.replace("'/etc/ssh/ssh_host_*'", '"/etc/ssh/ssh_host_*"')
        line = re.sub(
            r"(?<![\w$])/(etc/ssh|usr/lib/systemd|usr/bin/ssh-keygen)",
            r"$SCRATCH/\1",
            line,
        )
        out.append(line)
        in_heredoc = "<<'EOF'" in line
    return "\n".join(out) + "\n"


def _run_cleanup(scratch: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _ssh_block()],
        env={**os.environ, "SCRATCH": str(scratch)},
        capture_output=True,
        text=True,
    )


def _noble_image(tmp_path: Path, with_generator_inputs: bool = True) -> Path:
    scratch = tmp_path / "image"
    (scratch / "etc/ssh").mkdir(parents=True)
    for kind in KEY_TYPES:
        (scratch / f"etc/ssh/ssh_host_{kind}_key").write_text("baked private key\n")
        (scratch / f"etc/ssh/ssh_host_{kind}_key.pub").write_text("baked public key\n")
    (scratch / UNIT_DIR.lstrip("/")).mkdir(parents=True)
    if with_generator_inputs:
        (scratch / UNIT_DIR.lstrip("/") / "ssh.service").write_text(
            "[Service]\nExecStart=/usr/sbin/sshd -D\n"
        )
        keygen = scratch / "usr/bin/ssh-keygen"
        keygen.parent.mkdir(parents=True)
        keygen.write_text("#!/bin/sh\nexit 0\n")
        keygen.chmod(0o755)
    return scratch


def _values(unit: str, directive: str) -> list[str]:
    prefix = f"{directive}="
    return [
        value
        for line in unit.splitlines()
        if line.startswith(prefix)
        for value in line.removeprefix(prefix).split()
    ]


def _generator_runs(unit: str, machine: Path) -> bool:
    missing_paths = [
        value.removeprefix("|!")
        for value in _values(unit, "ConditionPathExists")
        if value.startswith("|!")
    ]
    return any(not (machine / path.lstrip("/")).exists() for path in missing_paths)


def test_noble_keys_are_removed_and_regenerated(tmp_path):
    scratch = _noble_image(tmp_path)
    result = _run_cleanup(scratch)
    assert result.returncode == 0, result.stderr
    assert not list((scratch / "etc/ssh").glob("ssh_host_*")), (
        "gurnard still carries host keys every installation would share"
    )

    generator = (scratch / GENERATOR.lstrip("/")).read_text()
    ssh_dropin = (scratch / SSH_DROPIN.lstrip("/")).read_text()
    generator_name = Path(GENERATOR).name
    assert generator_name in _values(ssh_dropin, "Requires")
    assert generator_name in _values(ssh_dropin, "After")
    assert "ssh.service" in _values(generator, "Before")

    machine = tmp_path / "machine"
    (machine / "etc/ssh").mkdir(parents=True)
    existing_key = machine / "etc/ssh/ssh_host_ed25519_key"
    existing_key.write_text("machine-generated key\n")
    assert _generator_runs(generator, machine)

    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen not installed")
    subprocess.run(
        ["ssh-keygen", "-A", "-f", str(machine)], check=True, capture_output=True
    )
    assert existing_key.read_text() == "machine-generated key\n"
    assert all(
        (machine / f"etc/ssh/ssh_host_{kind}_key").exists() for kind in KEY_TYPES
    )
    assert not _generator_runs(generator, machine)


def test_keys_without_any_generator_fail_the_build(tmp_path):
    scratch = _noble_image(tmp_path, with_generator_inputs=False)
    result = _run_cleanup(scratch)
    assert result.returncode != 0
    assert "no verified per-machine generator" in result.stderr
    assert list((scratch / "etc/ssh").glob("ssh_host_*_key")), (
        "a failed safety check must not silently delete keys without a replacement"
    )
