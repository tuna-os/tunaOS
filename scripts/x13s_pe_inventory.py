#!/usr/bin/env python3
"""Observe an ARM64 DTB-loader PE without executing it or granting admission.

Formats: Microsoft PE/COFF specification and Devicetree Specification v0.4.
This checks bounded structural fields, not signatures, CHID selection, or boot.
"""

import hashlib
import struct

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_SECTIONS = 96


class InventoryError(ValueError):
    """Input cannot be represented by this bounded observation format."""


def _span(data, offset, size):
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise InventoryError("truncated or out-of-range span")
    return data[offset : offset + size]


def _unpack(fmt, data, offset):
    return struct.unpack(fmt, _span(data, offset, struct.calcsize(fmt)))


def _cstring(data, offset):
    if offset >= len(data):
        raise InventoryError("string offset out of range")
    end = data.find(b"\0", offset)
    if end < 0:
        raise InventoryError("unterminated string")
    try:
        return data[offset:end].decode("ascii"), end + 1
    except UnicodeDecodeError as error:
        raise InventoryError("non-ASCII metadata") from error


def _dtb_root_compatible(data):
    """Read the root compatible property, never substring-match nested nodes."""
    magic, total, off_struct, off_strings, _, version, compatible_version, _, strings_size, struct_size = _unpack(
        ">10I", data, 0
    )
    if magic != 0xD00DFEED or version != 17 or compatible_version > 17:
        raise InventoryError("unsupported DTB header")
    blob = _span(data, 0, total)
    if total < 40 or off_struct < 40 or off_strings < 40:
        raise InventoryError("DTB block overlaps header")
    if max(off_struct, off_strings) < min(off_struct + struct_size, off_strings + strings_size):
        raise InventoryError("overlapping DTB blocks")
    structure = _span(blob, off_struct, struct_size)
    strings = _span(blob, off_strings, strings_size)
    pos, depth, roots = 0, 0, 0
    found = None
    while pos < len(structure):
        token = _unpack(">I", structure, pos)[0]
        pos += 4
        if token == 1:
            name, pos = _cstring(structure, pos)
            pos = (pos + 3) & ~3
            if depth == 0:
                roots += 1
                if roots != 1 or name:
                    raise InventoryError("invalid DTB root")
            depth += 1
        elif token == 2:
            depth -= 1
            if depth < 0:
                raise InventoryError("unbalanced DTB nodes")
        elif token == 3:
            length, name_offset = _unpack(">II", structure, pos)
            pos += 8
            value = _span(structure, pos, length)
            pos = (pos + length + 3) & ~3
            name, _ = _cstring(strings, name_offset)
            if depth == 0:
                raise InventoryError("DTB property outside a node")
            if depth == 1 and name == "compatible":
                if found is not None or not value or value[-1:] != b"\0":
                    raise InventoryError("invalid root compatible property")
                try:
                    found = [part.decode("ascii") for part in value[:-1].split(b"\0")]
                except UnicodeDecodeError as error:
                    raise InventoryError("non-ASCII compatible property") from error
                if any(not item for item in found):
                    raise InventoryError("empty compatible value")
        elif token == 4:
            continue
        elif token == 9:
            if depth != 0 or roots != 1:
                raise InventoryError("unbalanced DTB end")
            return found or []
        else:
            raise InventoryError("unknown DTB token")
    raise InventoryError("missing DTB end")


def inspect_pe(data):
    """Return byte observations only; no support or trusted/qualified boolean."""
    if not isinstance(data, bytes) or len(data) > MAX_IMAGE_BYTES:
        raise InventoryError("expected bounded immutable bytes")
    if _span(data, 0, 2) != b"MZ":
        raise InventoryError("missing DOS signature")
    pe = _unpack("<I", data, 0x3C)[0]
    if pe < 64 or _span(data, pe, 4) != b"PE\0\0":
        raise InventoryError("invalid PE signature")
    machine, count = _unpack("<HH", data, pe + 4)
    if machine != 0xAA64 or not 0 < count <= MAX_SECTIONS:
        raise InventoryError("expected ARM64 PE with bounded sections")
    optional_size = _unpack("<H", data, pe + 20)[0]
    optional = _span(data, pe + 24, optional_size)
    if len(optional) < 112 or _unpack("<H", optional, 0)[0] != 0x20B:
        raise InventoryError("expected PE32+ optional header")
    table = pe + 24 + optional_size
    table_end = table + count * 40
    _span(data, table, count * 40)
    spans, sections = [], []
    for index in range(count):
        header = _span(data, table + index * 40, 40)
        raw_name = header[:8].split(b"\0", 1)[0]
        try:
            name = raw_name.decode("ascii")
        except UnicodeDecodeError as error:
            raise InventoryError("non-ASCII section name") from error
        virtual_size = _unpack("<I", header, 8)[0]
        size, offset = _unpack("<II", header, 16)
        payload = _span(data, offset, size)
        if size:
            if offset < table_end or any(offset < end and start < offset + size for start, end in spans):
                raise InventoryError("overlapping PE sections or headers")
            spans.append((offset, offset + size))
        initialized_size = min(virtual_size, size)
        item = {
            "name": name,
            "size": size,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "virtual_size": virtual_size,
            "initialized_size": initialized_size,
            "initialized_sha256": hashlib.sha256(payload[:initialized_size]).hexdigest(),
        }
        if name == ".dtbauto":
            item["root_compatible"] = _dtb_root_compatible(payload)
        elif name == ".uname":
            item["kernel_release"], _ = _cstring(payload, 0)
        sections.append(item)
    return {
        "format": "x13s-pe-observation-v1",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "machine": "arm64",
        "sections": sections,
        "signature_verification": "not_performed",
        "chid_selection": "not_verified",
        "hardware_boot": "not_tested",
    }
