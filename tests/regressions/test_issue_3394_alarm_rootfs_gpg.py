"""tunaOS#3394 (dup #3400): the ALARM rootfs is trusted by GPG signature, not MD5.

build-archlinuxarm-base.yml used to check the tarball against an .md5 sidecar
from the same mirror, so replacing both objects passed. The rootfs is now
verified against its detached .sig with .github/scripts/verify-alarm-rootfs.sh,
pinned to the Arch Linux ARM Build System key fingerprint, and fails closed.

Falsification: the behavioural tests sign real data with throwaway keys; making
the script accept a bad, foreign or unsigned rootfs fails them. The structural
tests fail if the workflow regains an MD5 check or loses the pinned key.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "verify-alarm-rootfs.sh"
KEY = ROOT / ".github" / "keys" / "archlinuxarm-build.asc"
WORKFLOW = (ROOT / ".github" / "workflows" / "build-archlinuxarm-base.yml").read_text(
    encoding="utf-8"
)
ALARM_FPR = "68B3537F39A313B3E574D06777193F152BDBE6A6"

needs_gpg = pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg not installed")


def _gpg(home: Path, *args: str) -> str:
    env = {**os.environ, "GNUPGHOME": str(home)}
    done = subprocess.run(
        ["gpg", "--batch", "--yes", *args], env=env, check=True, capture_output=True, text=True
    )
    return done.stdout


def _make_key(tmp_path: Path, name: str) -> tuple[Path, str]:
    """A throwaway signing key; returns (GNUPGHOME, primary fingerprint)."""
    home = tmp_path / f"gpg-{name}"
    home.mkdir(mode=0o700)
    _gpg(home, "--passphrase", "", "--quick-generate-key", f"{name} <{name}@example.test>",
         "ed25519", "sign", "never")
    colons = _gpg(home, "--list-keys", "--with-colons")
    fpr = re.search(r"^fpr:::::::::([0-9A-F]{40}):", colons, re.M).group(1)
    return home, fpr


def _export(home: Path, fpr: str, dest: Path) -> Path:
    dest.write_text(_gpg(home, "--armor", "--export", fpr), encoding="utf-8")
    return dest


def _sign(home: Path, fpr: str, data: Path, sig: Path) -> None:
    _gpg(home, "--passphrase", "", "--local-user", fpr, "--detach-sign", "--output", str(sig),
         str(data))


def _run(rootfs: Path, sig: Path, key: Path, fpr: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(SCRIPT), str(rootfs), str(sig), str(key), fpr], capture_output=True, text=True
    )


@pytest.fixture()
def signed(tmp_path):
    home, fpr = _make_key(tmp_path, "builder")
    rootfs = tmp_path / "rootfs.tar.gz"
    rootfs.write_bytes(b"pretend rootfs\n" * 100)
    sig = tmp_path / "rootfs.tar.gz.sig"
    _sign(home, fpr, rootfs, sig)
    return tmp_path, home, fpr, rootfs, sig, _export(home, fpr, tmp_path / "builder.asc")


@needs_gpg
def test_a_good_signature_from_the_pinned_key_passes(signed):
    _, _, fpr, rootfs, sig, key = signed
    done = _run(rootfs, sig, key, fpr)
    assert done.returncode == 0, done.stderr


@needs_gpg
def test_a_tampered_rootfs_fails(signed):
    _, _, fpr, rootfs, sig, key = signed
    rootfs.write_bytes(rootfs.read_bytes() + b"backdoor")
    assert _run(rootfs, sig, key, fpr).returncode != 0


@needs_gpg
def test_a_missing_or_empty_signature_fails(signed):
    tmp, _, fpr, rootfs, sig, key = signed
    sig.write_bytes(b"")
    assert _run(rootfs, sig, key, fpr).returncode != 0
    assert _run(rootfs, tmp / "absent.sig", key, fpr).returncode != 0


@needs_gpg
def test_a_valid_signature_from_a_different_key_fails(signed):
    tmp, _, fpr, rootfs, _, key = signed
    ahome, afpr = _make_key(tmp, "attacker")
    forged = tmp / "forged.sig"
    _sign(ahome, afpr, rootfs, forged)
    # Attacker's key shipped as the key file, pinned fingerprint unchanged.
    assert _run(rootfs, forged, _export(ahome, afpr, tmp / "attacker.asc"), fpr).returncode != 0
    # Pinned key file, attacker's signature: the signer is unknown.
    assert _run(rootfs, forged, key, fpr).returncode != 0


@needs_gpg
def test_a_key_file_with_extra_keys_fails(signed):
    tmp, home, fpr, rootfs, _, key = signed
    ahome, afpr = _make_key(tmp, "attacker")
    forged = tmp / "forged.sig"
    _sign(ahome, afpr, rootfs, forged)
    both = tmp / "both.asc"
    both.write_text(key.read_text() + _gpg(ahome, "--armor", "--export", afpr), encoding="utf-8")
    assert _run(rootfs, forged, both, fpr).returncode != 0


def test_a_malformed_pinned_fingerprint_fails(signed):
    _, _, fpr, rootfs, sig, key = signed
    assert _run(rootfs, sig, key, fpr.lower()).returncode != 0
    assert _run(rootfs, sig, key, fpr[:16]).returncode != 0


@needs_gpg
def test_the_committed_key_is_the_pinned_alarm_build_key():
    out = subprocess.run(
        ["gpg", "--batch", "--show-keys", "--with-colons", str(KEY)],
        capture_output=True, text=True, check=True,
    ).stdout
    primaries = []
    want = False
    for line in out.splitlines():
        kind = line.split(":")[0]
        if kind == "pub":
            want = True
        elif kind == "sub":
            want = False
        elif kind == "fpr" and want:
            primaries.append(line.split(":")[9])
            want = False
    assert primaries == [ALARM_FPR]
    assert "builder@archlinuxarm.org" in out


def test_workflow_verifies_the_signature_and_drops_md5():
    assert "md5sum" not in WORKFLOW
    assert "tar.gz.md5" not in WORKFLOW
    assert ".sig" in WORKFLOW
    assert f"ALARM_BUILD_KEY_FPR: {ALARM_FPR}" in WORKFLOW
    assert ".github/scripts/verify-alarm-rootfs.sh" in WORKFLOW
    # Verified before the rootfs is extracted as root.
    assert WORKFLOW.index("verify-alarm-rootfs.sh") < WORKFLOW.index("tar -xpf rootfs.tar.gz")


def test_the_verifier_is_fail_closed_and_isolated():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "GNUPGHOME" in text and "mktemp -d" in text
    assert "--status-fd" in text and "VALIDSIG" in text
    assert "md5sum" not in text
