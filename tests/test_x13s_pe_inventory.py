"""Behavioral observations of synthetic PE/DTB bytes; no hardware evidence."""

import hashlib
import importlib.util
from pathlib import Path
import struct

import pytest

spec = importlib.util.spec_from_file_location("x13s_pe_inventory", Path(__file__).parents[1] / "scripts/x13s_pe_inventory.py")
if spec is None or spec.loader is None:
    raise RuntimeError("unable to load x13s_pe_inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def dtb(value=b"lenovo,thinkpad-x13s\0qcom,sc8280xp\0", nested=False):
    words = lambda *items: struct.pack(">" + "I" * len(items), *items)
    body = words(1) + b"\0" * 4
    if nested:
        body += words(1) + b"child\0\0\0"
    body += words(3, len(value), 0) + value + b"\0" * (-len(value) % 4)
    if nested:
        body += words(2)
    body += words(2, 9)
    strings = b"compatible\0"
    return words(0xD00DFEED, 56 + len(body) + len(strings), 56, 56 + len(body), 40, 17, 16, 0, len(strings), len(body)) + bytes(16) + body + strings


def pe(parts=None, machine=0xAA64):
    parts = parts or [(b".uname", b"7.2.11-200.fc44.aarch64\0"), (b".dtbauto", dtb()), (b".hwids", b"unverified"), (b".linux", b"synthetic")]
    table = 64 + 24 + 112
    data = bytearray(table + len(parts) * 40)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<HH", data, 68, machine, len(parts))
    struct.pack_into("<H", data, 84, 112)
    struct.pack_into("<H", data, 88, 0x20B)
    for i, (name, payload) in enumerate(parts):
        off = table + i * 40
        data[off:off + 8] = name.ljust(8, b"\0")
        struct.pack_into("<I", data, off + 8, len(payload))
        struct.pack_into("<II", data, off + 16, len(payload), len(data))
        data.extend(payload)
    return bytes(data)


def test_observes_exact_root_without_claiming_boot_or_trust():
    result = inventory.inspect_pe(pe())
    assert result["sections"][1]["root_compatible"] == ["lenovo,thinkpad-x13s", "qcom,sc8280xp"]
    assert result["sections"][0]["kernel_release"] == "7.2.11-200.fc44.aarch64"
    assert result["signature_verification"] == "not_performed"
    assert result["chid_selection"] == "not_verified"
    assert result["hardware_boot"] == "not_tested"
    assert "qualified" not in result


def test_multiple_dtb_sections_are_preserved_in_order():
    result = inventory.inspect_pe(pe([(b".dtbauto", dtb(b"other,board\0")), (b".dtbauto", dtb())]))
    assert [s["root_compatible"][0] for s in result["sections"]] == ["other,board", "lenovo,thinkpad-x13s"]


def test_nested_compatible_is_not_root_evidence():
    assert inventory.inspect_pe(pe([(b".dtbauto", dtb(nested=True))]))["sections"][0]["root_compatible"] == []


@pytest.mark.parametrize("machine", [0x8664, 0xA641, 0])
def test_rejects_wrong_machine(machine):
    with pytest.raises(inventory.InventoryError):
        inventory.inspect_pe(pe(machine=machine))


@pytest.mark.parametrize("length", [0, 2, 63, 70, 100, 250])
def test_rejects_truncated_headers(length):
    with pytest.raises(inventory.InventoryError):
        inventory.inspect_pe(pe()[:length])


def test_rejects_truncated_payload():
    with pytest.raises(inventory.InventoryError):
        inventory.inspect_pe(pe()[:-1])


def test_rejects_overlapping_sections():
    data = bytearray(pe())
    table = 200
    first = struct.unpack_from("<I", data, table + 20)[0]
    struct.pack_into("<I", data, table + 40 + 20, first)
    with pytest.raises(inventory.InventoryError, match="overlapping"):
        inventory.inspect_pe(bytes(data))


@pytest.mark.parametrize("value", [b"not-terminated", b"\0", b"\xff\0"])
def test_rejects_invalid_root_property(value):
    with pytest.raises(inventory.InventoryError):
        inventory.inspect_pe(pe([(b".dtbauto", dtb(value))]))


def test_rejects_oversized_input_without_parsing(monkeypatch):
    monkeypatch.setattr(inventory, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(inventory.InventoryError, match="bounded"):
        inventory.inspect_pe(pe())


@pytest.mark.parametrize("offset,value", [(0, 0), (4, 0xFFFFFFFF), (8, 0), (12, 56), (20, 16), (24, 18), (32, 0xFFFFFFFF), (36, 0xFFFFFFFF)])
def test_rejects_bad_dtb_header(offset, value):
    data = bytearray(dtb())
    struct.pack_into(">I", data, offset, value)
    with pytest.raises(inventory.InventoryError):
        inventory.inspect_pe(pe([(b".dtbauto", bytes(data))]))


def test_rejects_unknown_dtb_token():
    data = bytearray(dtb())
    struct.pack_into(">I", data, 56, 0xFFFFFFFF)
    with pytest.raises(inventory.InventoryError, match="token"):
        inventory.inspect_pe(pe([(b".dtbauto", bytes(data))]))


def test_rejects_missing_end_token():
    data = bytearray(dtb())
    structure_size = struct.unpack_from(">I", data, 36)[0]
    struct.pack_into(">I", data, 56 + structure_size - 4, 4)
    with pytest.raises(inventory.InventoryError, match="missing DTB end"):
        inventory.inspect_pe(pe([(b".dtbauto", bytes(data))]))


def test_rejects_unterminated_kernel_release():
    with pytest.raises(inventory.InventoryError, match="unterminated"):
        inventory.inspect_pe(pe([(b".uname", b"release")]))


@pytest.mark.parametrize("count", [0, 97, 65535])
def test_rejects_unbounded_section_count(count):
    data = bytearray(pe())
    struct.pack_into("<H", data, 70, count)
    with pytest.raises(inventory.InventoryError, match="bounded sections"):
        inventory.inspect_pe(bytes(data))


def test_preserves_input_bytes():
    data = pe()
    before = bytes(data)
    inventory.inspect_pe(data)
    assert data == before


def test_distinguishes_padding_from_initialized_kernel_bytes():
    data = bytearray(pe([(b".linux", b"kernel" + bytes(10))]))
    struct.pack_into("<I", data, 208, 6)
    section = inventory.inspect_pe(bytes(data))["sections"][0]
    assert section["size"] == 16
    assert section["virtual_size"] == section["initialized_size"] == 6
    assert section["initialized_sha256"] == hashlib.sha256(b"kernel").hexdigest()
    assert section["sha256"] != section["initialized_sha256"]


def test_uninitialized_memory_is_not_fabricated_as_file_bytes():
    data = bytearray(pe([(b".bss", b"abc")]))
    struct.pack_into("<I", data, 208, 100)
    section = inventory.inspect_pe(bytes(data))["sections"][0]
    assert section["virtual_size"] == 100
    assert section["initialized_size"] == 3
    assert section["initialized_sha256"] == hashlib.sha256(b"abc").hexdigest()
