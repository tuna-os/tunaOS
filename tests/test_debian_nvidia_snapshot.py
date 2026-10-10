"""Execute snapshot selection with process-boundary APT fakes for CI."""

import os
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build_scripts/overlay/debian-nvidia-snapshot.sh"


def invoke(tmp_path, *, driver="550.163.01-5.1", kernel="7.2.7+deb14-amd64",
           arch="amd64", distro="debian", key=True, update_exit=0, bad_digest=False,
           bad_version=False):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    keyring = tmp_path / "debian-archive-keyring.gpg"
    if key:
        keyring.write_bytes(b"fixture keyring; external APT verifier is stubbed")
    release = tmp_path / "os-release"
    release.write_text(f"ID={distro}\n")
    text = SOURCE.read_text()
    # Relocate only filesystem inputs; run the actual control flow unchanged.
    text = text.replace('. /etc/os-release', f'. {release}')
    text = text.replace('KEYRING=/usr/share/keyrings/debian-archive-keyring.gpg',
                        f'KEYRING={keyring}')
    script = tmp_path / "snapshot.sh"
    script.write_text(text)
    log = tmp_path / "apt.log"
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    records = re.findall(r'^(linux-\S+) ([0-9a-f]{64})$', text, re.M)
    assert len(records) == 7
    for package, digest in records:
        (metadata / package).write_text(
            f"Package: {package}\nVersion: {'7.1.13-2' if bad_version else '7.1.13-1'}\n"
            f"SHA256: {'0' * 64 if bad_digest else digest}\n"
        )
    tools = {
        "dpkg": f"echo {arch}\n",
        "apt-get": f"printf '%s\\n' \"$*\" >> {log}\nexit {update_exit}\n",
        "apt-cache": f'cat {metadata}/"${{2%=*}}"\n',
    }
    for name, body in tools.items():
        executable = bindir / name
        executable.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
        executable.chmod(0o755)
    apt = tmp_path / "apt"
    result = subprocess.run(
        ["bash", str(script), driver, kernel], capture_output=True, text=True,
        env=dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", TUNAOS_APT_ROOT=str(apt)),
    )
    return result, apt, log


def test_exact_native_pair_keeps_apt_authentication(tmp_path):
    result, apt, log = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "7.1.13+deb14-amd64\n"
    source = (apt / "sources.list.d/tunaos-nvidia-kernel-snapshot.sources").read_text()
    assert "https://snapshot.debian.org/archive/debian/20260909T000000Z/" in source
    assert "Architectures: amd64" in source
    assert "Signed-By:" in source
    assert "Check-Valid-Until: no" in source
    assert "trusted" not in source.lower()
    preferences = (apt / "preferences.d/tunaos-nvidia-kernel-snapshot").read_text()
    assert 'Pin: origin "snapshot.debian.org"\nPin-Priority: -1' in preferences
    assert 'Pin: version 7.1.13-1\nPin-Priority: 1001' in preferences
    assert "Acquire::AllowInsecureRepositories=false" in log.read_text()
    assert "Acquire::AllowDowngradeToInsecureRepositories=false" in log.read_text()
    assert "Check-Valid-Until" not in log.read_text()


@pytest.mark.parametrize("options", [
    {"driver": "550.163.01-5.2"}, {"driver": "555.58.02-3"},
    {"kernel": "7.2.7+deb14-arm64"}, {"arch": "arm64"},
    {"distro": "ubuntu"}, {"key": False},
])
def test_unproven_identity_or_missing_trust_refuses_before_apt(tmp_path, options):
    result, apt, log = invoke(tmp_path, **options)
    assert result.returncode != 0
    assert not apt.exists()
    assert not log.exists()
    assert "7.1.13+deb14-amd64" not in result.stdout


@pytest.mark.parametrize("options", [
    {"update_exit": 100}, {"bad_digest": True}, {"bad_version": True},
])
def test_authentication_or_exact_metadata_failure_never_selects_kernel(tmp_path, options):
    result, _, _ = invoke(tmp_path, **options)
    assert result.returncode != 0
    assert result.stdout == ""
