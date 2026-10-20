"""Fixture regressions; emulator execution is a separate CI result."""
import importlib.util
from pathlib import Path
import stat
import struct
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("handoff", Path(__file__).parents[1] / "scripts/test-x13s-loader-handoff.py")
if spec is None or spec.loader is None:
    raise RuntimeError("unable to load X13s handoff module")
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


def archive(name="payload", mode=stat.S_IFREG | 0o644, data=b"bytes"):
    return handoff.newc([(name, mode, data)])

def test_download_handles_short_reads(monkeypatch, tmp_path):
    payload = b"payload"

    class Response:
        def __init__(self):
            self.remaining = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, count):
            chunk, self.remaining = self.remaining[: min(2, count)], self.remaining[min(2, count):]
            return chunk

    monkeypatch.setattr(handoff.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    target = tmp_path / "payload"
    handoff.download("https://fixture.invalid/payload", target, handoff.digest(payload), size=len(payload))
    assert target.read_bytes() == payload

def test_serial_evidence_keeps_raw_bytes(tmp_path):
    path = tmp_path / "serial.log"
    raw = b"boot\xff\n"
    path.write_bytes(raw)

    output, log = handoff.read_serial(path)

    assert output == raw
    assert path.read_bytes() == raw
    assert log == "boot\ufffd\n"


def test_selects_only_inline_regular_payload(tmp_path):
    assert handoff.member_from_newc(archive(), "payload") == b"bytes"
    path = tmp_path / "payload.cpio"
    path.write_bytes(archive())
    assert handoff.member_from_newc(path, "payload") == b"bytes"


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

def test_rejects_normalized_duplicate_member():
    data = handoff.newc([("a/b", stat.S_IFREG, b"a"), ("a//b", stat.S_IFREG, b"b")])
    with pytest.raises(ValueError, match="duplicate"):
        handoff.member_from_newc(data, "a/b")

def test_rejects_invalid_archive_name_encoding():
    data = handoff.newc([("payload", stat.S_IFREG | 0o644, b"bytes")])
    assert b"payload\0" in data
    data = data.replace(b"payload\0", b"\xffayload\0", 1)
    with pytest.raises(ValueError, match="encoding"):
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
    for case, log in (
        ("missing-initrd", "Kernel panic - VFS: Unable to mount root fs"),
        ("wrong-argument", "X13S_FIXTURE_FAIL"),
    ):
        for code in (124, -9):
            with pytest.raises(ValueError, match="exited nonzero"):
                handoff.assert_result(case, log, code)


def test_configs_use_actual_linux_initrd_path():
    positive = handoff.grub_config("positive")
    assert "linux /fixture/loader.efi" in positive
    assert "initrd /fixture/initrd" in positive
    assert "chainloader" not in positive
    assert "initrd /fixture/initrd" not in handoff.grub_config("missing-initrd")
    assert "panic=1" in handoff.grub_config("missing-initrd")
    assert "x13s.fixture=wrong" in handoff.grub_config("wrong-argument")
    assert "panic=-1" in positive


def _check_loader_with_sections(monkeypatch, sections):
    class Loader:
        def exec_module(self, module):
            module.inspect_pe = lambda _data: {"sections": sections}

    monkeypatch.setattr(
        handoff.importlib.util,
        "spec_from_file_location",
        lambda *_args: SimpleNamespace(loader=Loader()),
    )
    monkeypatch.setattr(
        handoff.importlib.util,
        "module_from_spec",
        lambda _spec: SimpleNamespace(),
    )
    return handoff.check_loader(b"synthetic")


def test_check_loader_rejects_missing_inventory_loader(monkeypatch):
    monkeypatch.setattr(
        handoff.importlib.util,
        "spec_from_file_location",
        lambda *_args: SimpleNamespace(loader=None),
    )
    with pytest.raises(ValueError, match="unable to load"):
        handoff.check_loader(b"synthetic")


@pytest.mark.parametrize(
    "sections,message",
    [
        (
            [
                {"name": ".linux", "initialized_sha256": "f838299696f91f0400de9e6b796d3d862f8e9eb2899101a913314150ce9550d6"},
                {"name": ".uname", "kernel_release": "7.2.11-200.fc44.aarch64"},
                {"name": ".initrd"},
            ],
            "compete",
        ),
        (
            [
                {"name": ".linux", "initialized_sha256": "wrong"},
                {"name": ".uname", "kernel_release": "7.2.11-200.fc44.aarch64"},
            ],
            "kernel",
        ),
        (
            [
                {"name": ".linux", "initialized_sha256": "f838299696f91f0400de9e6b796d3d862f8e9eb2899101a913314150ce9550d6"},
                {"name": ".uname", "kernel_release": "wrong"},
            ],
            "release",
        ),
    ],
)
def test_check_loader_rejects_unsafe_or_mismatched_payload(monkeypatch, sections, message):
    with pytest.raises(ValueError, match=message):
        _check_loader_with_sections(monkeypatch, sections)

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


@pytest.mark.parametrize("armored", [True, False])
def test_approved_key_export_requires_armor_and_exact_fingerprint(monkeypatch, tmp_path, armored):
    from types import SimpleNamespace
    data = b"-----BEGIN PGP PUBLIC KEY BLOCK-----\nfixture\n-----END PGP PUBLIC KEY BLOCK-----\n" if armored else b"binary"
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=data)
    monkeypatch.setattr(handoff, "run", fake_run)
    if armored:
        assert handoff.export_approved_key(tmp_path, FINGERPRINT) == data
    else:
        with pytest.raises(ValueError, match="armored"):
            handoff.export_approved_key(tmp_path, FINGERPRINT)
    assert calls == [["gpg", "--homedir", tmp_path, "--batch", "--armor", "--export", FINGERPRINT]]
