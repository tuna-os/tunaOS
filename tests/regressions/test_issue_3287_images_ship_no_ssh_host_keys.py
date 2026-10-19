"""tunaOS#3287: Debian and Ubuntu images shipped one set of SSH host keys.

openssh-server's postinst runs `ssh-keygen -A` when 40-services.sh installs
it, so every flounder, flounder-sid and grouper install carried the same host
private keys. build_scripts/99-cleanup.sh now removes baked keys wherever
openssh ships sshd-keygen.service (`ExecStart=ssh-keygen -A`), and adds a
drop-in so that unit regenerates any missing key on every boot, not only
under ConditionFirstBoot=yes: a bootc upgrade from a digest that still baked
keys drops them in the /etc merge on a boot that is not the first.

This test runs the real cleanup block against a scratch root and evaluates
the unit's resulting conditions with systemd's rules (an empty assignment
resets every condition; `|` conditions are triggering, so one true is
enough; the rest must all hold).

Falsification: behavioural. Delete the `rm -f /etc/ssh/ssh_host_*` line and
test_baked_keys_are_removed fails; delete the drop-in (or its
`ConditionFirstBoot=` reset) and
test_missing_keys_are_regenerated_on_a_boot_that_is_not_the_first fails.
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
DROPIN = f"{UNIT_DIR}/sshd-keygen.service.d/10-tunaos-missing-keys.conf"
KEY_TYPES = ("ed25519", "ecdsa", "rsa")

# openssh-server's unit as Debian ships it (salsa ssh-team/openssh,
# debian/systemd/sshd-keygen.service); Ubuntu resolute ships the same unit.
DEBIAN_UNIT = """[Unit]
Description=Generate sshd host keys on first boot
ConditionFirstBoot=yes
ConditionPathIsReadWrite=/etc/ssh
ConditionPathIsSymbolicLink=!/etc/ssh
Before=ssh.service sshd.service sshd@.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=ssh-keygen -A
"""


def _ssh_block() -> str:
    """The cleanup's SSH block, with absolute paths moved under $SCRATCH.

    Heredoc lines stay untouched: they are the drop-in's content, and the
    machine evaluates them against the real /etc/ssh.
    """
    text = CLEANUP.read_text()
    start = text.index("if compgen -G '/etc/ssh/ssh_host_*'")
    end = text.index("\nfi\n", start) + len("\nfi\n")
    out, in_heredoc = [], False
    for line in text[start:end].splitlines():
        if in_heredoc:
            out.append(line)
            in_heredoc = line != "EOF"
            continue
        # The compgen glob is single-quoted; $SCRATCH must expand in it.
        line = line.replace("'/etc/ssh/ssh_host_*'", '"/etc/ssh/ssh_host_*"')
        out.append(re.sub(r"(?<![\w$])/(etc/ssh|usr/lib/systemd)", r"$SCRATCH/\1", line))
        in_heredoc = "<<'EOF'" in line
    return "\n".join(out) + "\n"


def _run_cleanup(scratch: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", _ssh_block()],
        env={**os.environ, "SCRATCH": str(scratch)},
        capture_output=True, text=True,
    )


def _image(tmp_path: Path, unit: str | None) -> Path:
    scratch = tmp_path / "image"
    (scratch / "etc/ssh").mkdir(parents=True)
    for kind in KEY_TYPES:
        (scratch / f"etc/ssh/ssh_host_{kind}_key").write_text("baked private key\n")
        (scratch / f"etc/ssh/ssh_host_{kind}_key.pub").write_text("baked public key\n")
    (scratch / UNIT_DIR.lstrip("/")).mkdir(parents=True)
    if unit is not None:
        (scratch / UNIT_DIR.lstrip("/") / "sshd-keygen.service").write_text(unit)
    for name in ("ssh.service", "sshd@.service", "ssh.socket"):
        (scratch / UNIT_DIR.lstrip("/") / name).write_text("[Unit]\nDescription=Test SSH entrypoint\n")
    return scratch


def _conditions(*unit_texts: str) -> list[tuple[str, str]]:
    """[Unit] Condition* settings after systemd's drop-in merge."""
    conditions: list[tuple[str, str]] = []
    for text in unit_texts:
        section = None
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("["):
                section = line
                continue
            if section != "[Unit]" or not line.startswith("Condition"):
                continue
            key, value = line.split("=", 1)
            if value == "":
                conditions = []  # an empty assignment resets every condition
            else:
                conditions.append((key, value))
    return conditions


def _unit_runs(conditions, machine_root: Path, first_boot: bool) -> bool:
    def holds(key, value):
        negate = value.startswith("!")
        value = value.lstrip("!")
        path = machine_root / value.lstrip("/")
        if key == "ConditionFirstBoot":
            result = first_boot == (value == "yes")
        elif key == "ConditionPathExists":
            result = path.exists()
        elif key == "ConditionPathIsSymbolicLink":
            result = path.is_symlink()
        elif key == "ConditionPathIsReadWrite":
            result = os.access(path, os.W_OK)
        else:
            raise AssertionError(f"condition this test does not model: {key}")
        return result != negate

    plain = [(k, v) for k, v in conditions if not v.startswith("|")]
    triggering = [(k, v[1:]) for k, v in conditions if v.startswith("|")]
    return all(holds(k, v) for k, v in plain) and (
        not triggering or any(holds(k, v) for k, v in triggering)
    )


def test_baked_keys_are_removed(tmp_path):
    scratch = _image(tmp_path, DEBIAN_UNIT)
    result = _run_cleanup(scratch)
    assert result.returncode == 0, result.stderr
    assert not list((scratch / "etc/ssh").glob("ssh_host_*")), (
        "the image still carries host keys every install would share"
    )


def test_missing_keys_are_regenerated_on_a_boot_that_is_not_the_first(tmp_path):
    scratch = _image(tmp_path, DEBIAN_UNIT)
    assert _run_cleanup(scratch).returncode == 0
    dropin = (scratch / DROPIN.lstrip("/")).read_text()
    conditions = _conditions(DEBIAN_UNIT, dropin)

    machine = tmp_path / "machine"
    (machine / "etc/ssh").mkdir(parents=True)
    # An upgraded machine whose baked keys the /etc merge just dropped.
    assert _unit_runs(conditions, machine, first_boot=False)
    # Upstream alone would not have run: this is the gap the drop-in closes.
    assert not _unit_runs(_conditions(DEBIAN_UNIT), machine, first_boot=False)

    # One key type missing is enough.
    for kind in KEY_TYPES[:2]:
        (machine / f"etc/ssh/ssh_host_{kind}_key").write_text("machine key\n")
    assert _unit_runs(conditions, machine, first_boot=False)


def test_existing_machine_keys_are_kept(tmp_path):
    scratch = _image(tmp_path, DEBIAN_UNIT)
    assert _run_cleanup(scratch).returncode == 0
    conditions = _conditions(DEBIAN_UNIT, (scratch / DROPIN.lstrip("/")).read_text())

    machine = tmp_path / "machine"
    (machine / "etc/ssh").mkdir(parents=True)
    for kind in KEY_TYPES:
        (machine / f"etc/ssh/ssh_host_{kind}_key").write_text("machine key\n")
    assert not _unit_runs(conditions, machine, first_boot=False)

    if shutil.which("ssh-keygen") is None:
        pytest.skip("ssh-keygen not installed")
    # `ssh-keygen -A` (the unit's ExecStart) creates only missing types.
    (machine / "etc/ssh/ssh_host_rsa_key").unlink()
    subprocess.run(["ssh-keygen", "-A", "-f", str(machine)], check=True,
                   capture_output=True)
    assert (machine / "etc/ssh/ssh_host_ed25519_key").read_text() == "machine key\n"
    assert (machine / "etc/ssh/ssh_host_rsa_key").read_text() != "machine key\n"


def test_an_image_without_the_generator_keeps_its_keys(tmp_path):
    # Ubuntu noble (gurnard) ships no sshd-keygen.service; removing the keys
    # there would leave sshd with none (tunaOS#3298 tracks the generator).
    scratch = _image(tmp_path, None)
    result = _run_cleanup(scratch)
    assert result.returncode == 0, result.stderr
    assert len(list((scratch / "etc/ssh").glob("ssh_host_*"))) == 2 * len(KEY_TYPES)
    assert "no sshd-keygen.service" in result.stderr


@pytest.mark.parametrize("name", ["ssh.service", "sshd@.service"])
def test_keygen_dependency_survives_missing_package_enablement_links(tmp_path, name):
    scratch = _image(tmp_path, DEBIAN_UNIT)
    # No /etc/systemd/system links exist in this fixture. The vendor drop-in
    # must pull AND order keygen whenever an administrator starts SSH.
    assert _run_cleanup(scratch).returncode == 0
    dependency = scratch / UNIT_DIR.lstrip("/") / f"{name}.d/10-tunaos-host-keys.conf"
    assert dependency.read_text() == "[Unit]\nRequires=sshd-keygen.service\nAfter=sshd-keygen.service\n"
    assert not (scratch / "etc/systemd/system").exists(), "cleanup must not enable SSH"


def test_non_debian_generator_gets_no_new_dependencies(tmp_path):
    scratch = _image(tmp_path, None)
    assert _run_cleanup(scratch).returncode == 0
    assert not list((scratch / UNIT_DIR.lstrip("/")).glob("*.d/10-tunaos-host-keys.conf"))


def test_socket_does_not_wait_for_normal_service_default_dependencies(tmp_path):
    scratch = _image(tmp_path, DEBIAN_UNIT)
    assert _run_cleanup(scratch).returncode == 0
    assert not (scratch / UNIT_DIR.lstrip("/") / "ssh.socket.d/10-tunaos-host-keys.conf").exists()
