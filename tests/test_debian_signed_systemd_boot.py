"""tunaOS#4955: the Debian images ship a systemd-boot that Debian's shim accepts.

flounder and flounder-sid shipped only the unsigned systemd-bootx64.efi. apt
satisfies `systemd-boot-efi-signed | systemd-boot-efi` with the unsigned
package when the install list names it, so the signed package must be named
too. `build_scripts/checks/verify-systemd-boot-signed.sh` then fails the build
when the signed file is absent or its signature does not verify.

Two parts:

- Structural: Containerfile.debian names the signed package, and a later RUN
  reaches the check (AGENTS.md, "Being invoked is not being reached").
- Behavioural: the real check script runs against a fixture tree with a stub
  `sbverify`. The stub prints what the real tool printed on trixie and sid on
  2026-11-25; an unsigned file gives "No signature table present" with exit
  status 0 from `--list`.

Falsification: remove the signed package from the install list, add `|| true`
after the check, put an `exit 0` before `sbverify` in the script, or make the
script trust the exit status of `sbverify --list`. Each change fails a test.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTAINERFILE = ROOT / "Containerfile.debian"
CHECK = ROOT / "build_scripts/checks/verify-systemd-boot-signed.sh"
CA_PEM = ROOT / "build_scripts/checks/certs/debian-secure-boot-ca.pem"
CHECK_CALL = "/run/context/build_scripts/checks/verify-systemd-boot-signed.sh"
SIGNED_PACKAGE = '"systemd-boot-efi-$(dpkg --print-architecture)-signed"'
# The `.vendor_cert` of Debian's shim. The same value is in
# installer-medium/secure-boot/bases.toml (shim_vendor_sha256) for Debian.
CA_DER_SHA256 = "079646974bce09b1f04da67bd722d1fb0947ae4c4010bccdbba52d5b23cbf1a2"

STUB_SBVERIFY = r"""#!/usr/bin/env bash
# Stub of sbverify. A file whose content starts with SIGNED has a signature;
# SIGNED-BY-OTHER has one that does not chain to the given certificate.
file="${!#}"
content="$(head -c 15 "$file")"
if [[ "$1" == "--list" ]]; then
	case "$content" in
	SIGNED*)
		echo "signature 1"
		echo "image signature issuers:"
		echo " - /CN=Debian Secure Boot CA"
		;;
	*) echo "No signature table present" ;;
	esac
	exit 0
fi
if [[ "$1" == "--cert" ]]; then
	echo "cert=$2" >>"${STUB_LOG:-/dev/null}"
	case "$content" in
	SIGNED-BY-OTHER*) echo "Signature verification failed"; exit 1 ;;
	SIGNED*) echo "Signature verification OK"; exit 0 ;;
	*) echo "No signature table present"; echo "Signature verification failed"; exit 1 ;;
	esac
fi
exit 2
"""


def _run_instructions():
    """Each RUN of Containerfile.debian as one string, comments removed."""
    runs, current = [], None
    for line in CONTAINERFILE.read_text().splitlines():
        if current is None:
            if not line.startswith("RUN "):
                continue
            current = []
        elif line.lstrip().startswith("#"):
            continue
        current.append(line.rstrip("\\").strip())
        if not line.rstrip().endswith("\\"):
            runs.append(" ".join(current))
            current = None
    return runs


def test_the_install_list_names_the_signed_package_and_keeps_the_unsigned_one():
    installs = [r for r in _run_instructions() if " systemd-boot " in r]
    assert len(installs) == 1, "expected one RUN that installs systemd-boot"
    words = installs[0].split()
    assert SIGNED_PACKAGE in installs[0]
    # Corral's bootc backend probe needs the plain file from this package.
    assert "systemd-boot-efi" in words
    assert "--no-install-recommends" in words


def test_a_run_after_the_install_reaches_the_check():
    runs = _run_instructions()
    install = next(i for i, r in enumerate(runs) if SIGNED_PACKAGE in r)
    callers = [i for i, r in enumerate(runs) if CHECK_CALL in r]
    assert callers, "no RUN calls verify-systemd-boot-signed.sh"
    assert callers[0] > install, "the check runs before the package is installed"

    run = runs[callers[0]]
    assert "from=context" in run, "the RUN does not mount the build context"
    steps = [s.strip() for s in run.split("&&")]
    at = next(i for i, s in enumerate(steps) if s.startswith(CHECK_CALL))
    # Each step before the check must fail the RUN when it fails, and no step
    # may end the RUN early.
    for step in steps[: at + 1]:
        assert "||" not in step and ";" not in step, f"step can hide a failure: {step}"
        assert not re.search(r"\bexit\b", step), f"step can end the RUN early: {step}"
    assert steps[at] == CHECK_CALL, f"the check has a suffix: {steps[at]}"
    assert any("install" in s and "sbsigntool" in s.split() for s in steps[:at]), (
        "sbverify is not installed before the check")


def test_the_script_has_no_exit_before_sbverify_runs():
    lines = CHECK.read_text().splitlines()
    code = [(n, line) for n, line in enumerate(lines, 1) if not line.lstrip().startswith("#")]
    verify = next(n for n, line in code if re.match(r"\s*sbverify --cert ", line))
    assert any(re.search(r"\bsbverify --list\b", line) for n, line in code if n < verify)
    for n, line in code:
        if n < verify:
            assert not re.search(r"\bexit\s+0\b|\breturn\s+0\b", line), f"line {n}: {line}"
    assert "set -euo pipefail" in lines
    assert os.access(CHECK, os.X_OK)


def test_the_pinned_certificate_is_the_debian_secure_boot_ca():
    import base64

    body = "".join(
        line for line in CA_PEM.read_text().splitlines() if not line.startswith("-----"))
    assert hashlib.sha256(base64.b64decode(body)).hexdigest() == CA_DER_SHA256
    assert f'CA_DER_SHA256="{CA_DER_SHA256}"' in CHECK.read_text()


@pytest.fixture
def image(tmp_path):
    """A fixture tree, a copy of the check and its certificate, and a stub sbverify."""
    checks = tmp_path / "checks"
    (checks / "certs").mkdir(parents=True)
    shutil.copy2(CHECK, checks / CHECK.name)
    shutil.copy2(CA_PEM, checks / "certs" / CA_PEM.name)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "sbverify").write_text(STUB_SBVERIFY)
    (stubs / "sbverify").chmod(0o755)
    efi = tmp_path / "root/usr/lib/systemd/boot/efi"
    efi.mkdir(parents=True)
    (efi / "systemd-bootx64.efi").write_text("PLAIN")
    (efi / "systemd-bootx64.efi.signed").write_text("SIGNED")
    (efi / "systemd-bootaa64.efi.signed").write_text("SIGNED")

    def run(*args, arch="amd64", path=None):
        env = {
            "PATH": path if path is not None else f"{stubs}:{os.environ['PATH']}",
            "TUNAOS_SYSROOT": str(tmp_path / "root"),
            "TUNAOS_DEB_ARCH": arch,
            "STUB_LOG": str(tmp_path / "stub.log"),
        }
        return subprocess.run(
            ["bash", str(checks / CHECK.name), *args],
            env=env, capture_output=True, text=True, check=False)

    run.efi, run.checks, run.log = efi, checks, tmp_path / "stub.log"
    return run


@pytest.mark.parametrize("arch", ["amd64", "arm64"])
def test_a_signed_binary_passes(image, arch):
    result = image(arch=arch)
    assert result.returncode == 0, result.stderr
    assert "signed systemd-boot: OK" in result.stdout
    # The certificate that sbverify got is the pinned one.
    assert image.log.read_text().strip() == f"cert={image.checks}/certs/{CA_PEM.name}"


def test_a_missing_signed_binary_fails(image):
    (image.efi / "systemd-bootx64.efi.signed").unlink()
    result = image()
    assert result.returncode == 1
    assert "is missing" in result.stderr


def test_an_unsigned_binary_fails_although_list_exits_zero(image):
    (image.efi / "systemd-bootx64.efi.signed").write_text("PLAIN")
    result = image()
    assert result.returncode == 1
    assert "has no signature" in result.stderr


def test_the_unsigned_binary_given_as_argument_fails(image):
    result = image(str(image.efi / "systemd-bootx64.efi"))
    assert result.returncode == 1
    assert "has no signature" in result.stderr


def test_a_signature_from_another_signer_fails(image):
    (image.efi / "systemd-bootx64.efi.signed").write_text("SIGNED-BY-OTHER")
    result = image()
    assert result.returncode == 1
    assert "does not chain to the Debian Secure Boot CA" in result.stderr


def test_a_changed_certificate_fails_before_sbverify_uses_it(image):
    pem = image.checks / "certs" / CA_PEM.name
    lines = pem.read_text().splitlines()
    lines[1] = lines[1][:-4] + "AAAA"
    pem.write_text("\n".join(lines) + "\n")
    result = image()
    assert result.returncode == 1
    assert "not the pinned" in result.stderr
    assert not image.log.exists()


def test_an_unknown_architecture_fails(image):
    result = image(arch="riscv64")
    assert result.returncode == 1
    assert "riscv64" in result.stderr


def test_a_missing_sbverify_fails(image, tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    for tool in ("bash", "dirname", "sed", "base64", "sha256sum", "cut", "grep"):
        (tools / tool).symlink_to(shutil.which(tool))
    result = image(path=str(tools))
    assert result.returncode == 1
    assert "sbverify is missing" in result.stderr
