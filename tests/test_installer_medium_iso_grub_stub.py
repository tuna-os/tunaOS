"""The GRUB stub in the ISO 9660 file system of the hybrid image (tunaOS#4970)."""

import importlib.util
import io
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "iso_grub_stub", ROOT / "installer-medium/repart/iso-grub-stub.py"
)
stub = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stub)

SECTOR = 2048
ROOT_DIR = 20


def hybrid(extra=b""):
    """An image as systemd-repart --el-torito writes it: an empty root directory of 68 bytes."""
    image = io.BytesIO(b"\0" * (2 << 20))
    image.seek(512)
    header = bytearray(92)
    header[:8] = b"EFI PART"
    struct.pack_into("<QII", header, 72, 2, 4, 128)
    image.write(header)
    image.seek(1024)
    image.write(b"\1" * 32 + struct.pack("<Q", 2048) + b"\0" * 88)
    size = 68 + len(extra)
    pvd = bytearray(SECTOR)
    pvd[:6] = b"\x01CD001"
    pvd[156 : 156 + 34] = stub.record(b"\0", ROOT_DIR, size, True)
    image.seek(stub.PVD * SECTOR)
    image.write(pvd)
    image.seek(ROOT_DIR * SECTOR)
    image.write(stub.record(b"\0", ROOT_DIR, size, True) + stub.record(b"\1", ROOT_DIR, size, True))
    image.write(extra)
    return image


def listing(image, extent, size):
    image.seek(extent * SECTOR)
    data, at, out = image.read(size), 0, {}
    while at < size and data[at]:
        entry = data[at : at + data[at]]
        out[entry[33 : 33 + entry[32]]] = struct.unpack_from("<I", entry, 2)[0], struct.unpack_from("<I", entry, 10)[0]
        at += data[at]
    return out


def test_grub_finds_its_configuration_on_the_disc():
    image = hybrid()
    before = image.getvalue()
    stub.add_stub(image, "almalinux", stub.first_partition(image))
    image.seek(stub.PVD * SECTOR + 156)
    record = image.read(34)
    root = listing(image, struct.unpack_from("<I", record, 2)[0], struct.unpack_from("<I", record, 10)[0])
    assert root[b"\0"][1] == root[b"\1"][1] == struct.unpack_from("<I", record, 10)[0] == 68 + 36
    vendor = listing(image, *root[b"EFI"])[b"ALMALINUX"]
    extent, size = listing(image, *vendor)[b"GRUB.CFG;1"]
    image.seek(extent * SECTOR)
    text = image.read(size).decode()
    assert "set config=($root,gpt1)/EFI/almalinux\n" in text
    assert text.endswith("configfile $config/grub.cfg\n")
    # The partitions and the GPT are as they were.
    after = image.getvalue()
    assert after[: 16 * SECTOR] == before[: 16 * SECTOR]
    assert after[1 << 20 :] == before[1 << 20 :]


def test_an_image_with_an_efi_directory_or_no_room_is_refused():
    with pytest.raises(ValueError, match="EFI directory"):
        image = hybrid(stub.record(b"EFI", 30, SECTOR, True))
        stub.add_stub(image, "fedora", stub.first_partition(image))
    with pytest.raises(ValueError, match="no room"):
        stub.add_stub(hybrid(), "fedora", 65 * SECTOR)
    image = hybrid()
    image.seek(stub.FIRST_FREE * SECTOR)
    image.write(b"x")
    with pytest.raises(ValueError, match="in use"):
        stub.add_stub(image, "fedora", 1 << 20)
    with pytest.raises(ValueError, match="directory name"):
        stub.add_stub(hybrid(), "../x", 1 << 20)
