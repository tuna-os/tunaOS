"""Fixture regressions; emulator execution is a separate CI result."""
import importlib.util
from pathlib import Path
import stat
import struct

import pytest

spec = importlib.util.spec_from_file_location("handoff", Path(__file__).parents[1] / "scripts/test-x13s-loader-handoff.py")
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


def archive(name="payload", mode=stat.S_IFREG | 0o644, data=b"bytes"):
    return handoff.newc([(name, mode, data)])


def test_selects_only_inline_regular_payload():
    assert handoff.member_from_newc(archive(), "payload") == b"bytes"


@pytest.mark.parametrize("mode,data", [(stat.S_IFLNK | 0o777, b"target"), (stat.S_IFREG, b""), (stat.S_IFDIR, b"x")])
def test_rejects_links_empty_hardlink_members_and_directories(mode, data):
    with pytest.raises(ValueError, match="inline regular"):
        handoff.member_from_newc(archive(mode=mode, data=data), "payload")


@pytest.mark.parametrize("name", ["../payload", "/payload", "a/../../payload"])
def test_rejects_unsafe_paths(name):
    with pytest.raises(ValueError, match="unsafe"):
        handoff.member_from_newc(archive(name=name), name)


def test_rejects_duplicate_member():
    data = handoff.newc([("payload", stat.S_IFREG, b"a"), ("./payload", stat.S_IFREG, b"b")])
    with pytest.raises(ValueError, match="duplicate"):
        handoff.member_from_newc(data, "payload")


@pytest.mark.parametrize("cut", [0, 6, 109, 115, 120])
def test_rejects_truncated_archive(cut):
    with pytest.raises(ValueError):
        handoff.member_from_newc(archive()[:cut], "payload")


def test_missing_member_fails():
    with pytest.raises(ValueError, match="missing"):
        handoff.member_from_newc(archive(), "absent")


def test_positive_requires_sentinel_release_and_clean_exit():
    log = "X13S_FIXTURE_PASS\nX13S_FIXTURE_UNAME=7.2.11-200.fc44.aarch64\n"
    handoff.assert_result("positive", log, 0)
    for badlog, code in [(log, 124), ("", 0), ("X13S_FIXTURE_PASS", 0)]:
        with pytest.raises(ValueError):
            handoff.assert_result("positive", badlog, code)


def test_negative_controls_must_reach_expected_payload():
    handoff.assert_result("missing-initrd", "Kernel panic - VFS: Unable to mount root fs", 0)
    handoff.assert_result("wrong-argument", "X13S_FIXTURE_FAIL", 0)
    for case in ("missing-initrd", "wrong-argument"):
        for log in ("", "X13S_FIXTURE_PASS", "firmware error"):
            with pytest.raises(ValueError):
                handoff.assert_result(case, log, 124)


def test_configs_use_actual_linux_initrd_path():
    positive = handoff.grub_config("positive")
    assert "linux /fixture/loader.efi" in positive
    assert "initrd /fixture/initrd" in positive
    assert "chainloader" not in positive
    assert "initrd /fixture/initrd" not in handoff.grub_config("missing-initrd")
    assert "x13s.fixture=wrong" in handoff.grub_config("wrong-argument")


@pytest.mark.parametrize("machine", [0x8664, 0xA641, 0])
def test_rejects_non_arm64_payload(machine):
    data = bytearray(100)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, machine)
    with pytest.raises(ValueError, match="architecture"):
        handoff.check_arm64(bytes(data))


def test_initrd_is_deterministic():
    assert archive() == archive()


FINGERPRINT = "36F612DCF27F7D1A48A835E4DBFCF71C6D9F90A6"


@pytest.mark.parametrize("keyid", ["6d9f90a6", "dbfcf71c6d9f90a6", FINGERPRINT])
def test_requires_explicit_approved_signature_receipt(keyid):
    result = handoff.signature_receipt(f"    Header V4 RSA/SHA256 Signature, key ID {keyid}: OK\n    Payload SHA256 digest: OK", 0, FINGERPRINT)
    assert result["verified_header_signature"] is True


@pytest.mark.parametrize("output,code", [
    ("Header SHA256 digest: OK\nPayload SHA256 digest: OK", 0),
    ("digests signatures OK", 0),
    ("Header V4 RSA/SHA256 Signature, key ID 31645531: OK", 0),
    ("Header V4 RSA/SHA256 Signature, key ID 6d9f90a6: NOKEY", 0),
    ("Header V4 RSA/SHA256 Signature, key ID 6d9f90a6: BAD", 1),
    ("Header V4 RSA/SHA256 Signature, key ID 6d9f90a6: OK", 1),
    ("Header V6 RSA/SHA256 Signature, key ID 6d9f90a6: OK", 0),
])
def test_unsigned_wrong_signer_or_unverified_rpm_is_rejected(output, code):
    with pytest.raises(ValueError, match="explicitly verified"):
        handoff.signature_receipt(output, code, FINGERPRINT)
