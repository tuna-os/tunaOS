"""Typed, confined initramfs inspection for the APT static artifact consumer.

The caller must run this operation in its bounded inspection process group.
libarchive decodes CPIO/compression; this module never executes archive contents
or delegates extraction to cpio. All temporary paths belong to the caller.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import mmap
import os
from pathlib import Path
import posixpath
import shutil
import stat
import tempfile

MAX_EXPANDED_BYTES = 1024**3
MAX_MEMBERS = 100000
MAX_NAME_BYTES = 4096


class InvalidArchive(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise InvalidArchive(code)


class Reader:
    """Minimal binding to the system libarchive typed reader API."""

    def __init__(self, data, offset, *, compressed=False, length=None):
        self.lib = ctypes.CDLL(ctypes.util.find_library("archive") or "libarchive.so.13")
        declarations = {
            "archive_read_new": (ctypes.c_void_p, []),
            "archive_read_support_filter_all": (ctypes.c_int, [ctypes.c_void_p]),
            "archive_read_support_format_raw": (ctypes.c_int, [ctypes.c_void_p]),
            "archive_read_support_format_cpio": (ctypes.c_int, [ctypes.c_void_p]),
            "archive_read_open_memory": (ctypes.c_int, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]),
            "archive_read_next_header": (ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]),
            "archive_read_header_position": (ctypes.c_int64, [ctypes.c_void_p]),
            "archive_read_data": (ctypes.c_ssize_t, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]),
            "archive_filter_bytes": (ctypes.c_int64, [ctypes.c_void_p, ctypes.c_int]),
            "archive_filter_count": (ctypes.c_int, [ctypes.c_void_p]),
            "archive_read_free": (ctypes.c_int, [ctypes.c_void_p]),
            "archive_entry_pathname": (ctypes.c_char_p, [ctypes.c_void_p]),
            "archive_entry_filetype": (ctypes.c_uint, [ctypes.c_void_p]),
            "archive_entry_symlink": (ctypes.c_char_p, [ctypes.c_void_p]),
            "archive_entry_hardlink": (ctypes.c_char_p, [ctypes.c_void_p]),
        }
        for name, (result, args) in declarations.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, args
        self.reader = self.lib.archive_read_new()
        need(self.reader, "archive-reader-allocation-failed")
        self.data, self.offset, self.compressed = data, offset, compressed
        self.memory = (ctypes.c_char * (length if length is not None else len(data) - offset)).from_buffer(data, offset)
        try:
            if compressed:
                need(self.lib.archive_read_support_filter_all(self.reader) == 0, "archive-filter-unavailable")
                status = self.lib.archive_read_support_format_raw(self.reader)
            else:
                status = self.lib.archive_read_support_format_cpio(self.reader)
            need(status == 0, "archive-format-unavailable")
            need(self.lib.archive_read_open_memory(self.reader, self.memory, len(self.memory)) == 0,
                 "invalid-initramfs-archive")
        except BaseException:
            self.close()
            raise

    def close(self):
        self.lib.archive_read_free(self.reader)
        del self.memory

    def entries(self):
        entry = ctypes.c_void_p()
        while True:
            status = self.lib.archive_read_next_header(self.reader, ctypes.byref(entry))
            if not self.compressed and status in {0, 1}:
                position = self.offset + self.lib.archive_read_header_position(self.reader)
                need(self.data[position:position + 6] == b"070701",
                     "unsupported-initramfs-cpio-record")
            if status == 1:
                return
            need(status == 0, "invalid-initramfs-record")
            yield entry

    def chunks(self):
        buffer = ctypes.create_string_buffer(65536)
        while True:
            size = self.lib.archive_read_data(self.reader, buffer, len(buffer))
            need(size >= 0, "invalid-initramfs-data")
            if not size:
                return
            yield buffer.raw[:size]


def zstd_frame_size(data, offset):
    library = ctypes.CDLL(ctypes.util.find_library("zstd") or "libzstd.so.1")
    library.ZSTD_findFrameCompressedSize.restype = ctypes.c_size_t
    library.ZSTD_findFrameCompressedSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    library.ZSTD_isError.argtypes = [ctypes.c_size_t]
    memory = (ctypes.c_char * (len(data) - offset)).from_buffer(data, offset)
    try:
        size = library.ZSTD_findFrameCompressedSize(memory, len(memory))
        need(not library.ZSTD_isError(size) and 0 < size <= len(memory), "invalid-initramfs-zstd-frame")
        return size
    finally:
        del memory


def name(raw):
    need(raw is not None and len(raw) <= MAX_NAME_BYTES, "invalid-initramfs-path")
    decoded = raw.decode("utf-8")
    need(not decoded.startswith("/") and ".." not in decoded.split("/"), "escaping-initramfs-path")
    normalized = posixpath.normpath(decoded)
    need(normalized not in {"", ".."} and not normalized.startswith("../"), "escaping-initramfs-path")
    return normalized


def within(root, relative):
    path = root / relative
    try:
        need(path.resolve().is_relative_to(root), "escaping-initramfs-link")
    except (RuntimeError, OSError) as exc:
        raise InvalidArchive("invalid-initramfs-link-chain") from exc
    return path


def unpack(path, destination):
    """Decode every raw/compressed CPIO segment into an owned confined tree.

    The kernel permits early microcode CPIO followed by a compressed main
    archive, multiple CPIO trailers, and zero padding. No first-trailer shortcut
    is taken. Absolute symlink targets are rooted in this archive's tree, not
    the inspecting host; devices and FIFOs are recorded but never created.
    """
    destination = destination.resolve(strict=True)
    need(not any(destination.iterdir()), "initramfs-tree-must-be-empty")
    records, links = {}, []
    expanded = 0
    members = 0
    spool_index = 0
    with tempfile.TemporaryDirectory(prefix="apt-initrd-data-", dir=destination.parent) as temporary:
        def account(size):
            nonlocal expanded
            expanded += size
            need(expanded <= MAX_EXPANDED_BYTES, "expanded-initramfs-limit")

        def consume(file, depth=0):
            nonlocal members, spool_index
            need(depth <= 8, "nested-initramfs-limit")
            need(file.stat().st_size > 0, "empty-initramfs-stream")
            with file.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_COPY) as data:
                offset = 0
                while offset < len(data):
                    while offset < len(data) and data[offset] == 0:
                        offset += 1
                    if offset == len(data):
                        break
                    magic = data[offset:offset + 6]
                    need(magic not in {b"070702", b"070707"}, "unsupported-initramfs-cpio-method")
                    cpio = magic == b"070701"
                    frame_size = None
                    if not cpio:
                        need(data[offset:offset + 4] == b"\x28\xb5\x2f\xfd",
                             "unsupported-initramfs-compression")
                        frame_size = zstd_frame_size(data, offset)
                    reader = Reader(data, offset, compressed=not cpio, length=frame_size)
                    try:
                        if not cpio:
                            need(reader.lib.archive_filter_count(reader.reader) > 1,
                                 "unrecognized-initramfs-compression")
                            spool_index += 1
                            decompressed = Path(temporary) / str(spool_index)
                            with decompressed.open("xb") as output:
                                for _entry in reader.entries():
                                    for chunk in reader.chunks():
                                        account(len(chunk))
                                        output.write(chunk)
                            consume(decompressed, depth + 1)
                            need(reader.lib.archive_filter_bytes(reader.reader, -1) == frame_size,
                                 "unconsumed-initramfs-data")
                            offset += frame_size
                            continue
                        for entry in reader.entries():
                            member = name(reader.lib.archive_entry_pathname(entry))
                            kind = reader.lib.archive_entry_filetype(entry)
                            members += 1
                            need(members <= MAX_MEMBERS, "initramfs-entry-limit")
                            need(member not in records or kind == records[member] == stat.S_IFDIR,
                                 "duplicate-initramfs-path")
                            records[member] = kind
                            if member == ".":
                                need(kind == stat.S_IFDIR, "invalid-initramfs-root")
                                continue
                            target = within(destination, member)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            link = reader.lib.archive_entry_symlink(entry)
                            hardlink = reader.lib.archive_entry_hardlink(entry)
                            if link is not None or hardlink is not None:
                                raw = link if link is not None else hardlink
                                need(len(raw) <= MAX_NAME_BYTES, "invalid-initramfs-link")
                                raw = raw.decode("utf-8")
                                normalized = posixpath.normpath(
                                    raw.lstrip("/") if raw.startswith("/") else
                                    posixpath.join(posixpath.dirname(member) if link is not None else "", raw))
                                need(normalized != ".." and not normalized.startswith("../"),
                                     "escaping-initramfs-link")
                                links.append((member, normalized, link is not None))
                            if kind == stat.S_IFREG:
                                with target.open("xb") as output:
                                    for chunk in reader.chunks():
                                        account(len(chunk))
                                        output.write(chunk)
                            elif kind == stat.S_IFDIR:
                                target.mkdir(exist_ok=True)
                            else:
                                for chunk in reader.chunks():
                                    account(len(chunk))
                            # Special records cannot satisfy regular-file proof.
                        consumed = reader.lib.archive_filter_bytes(reader.reader, 0)
                        need(0 < consumed <= len(data) - offset, "invalid-initramfs-consumption")
                        offset += consumed
                    finally:
                        reader.close()

        consume(path)
        for member, target_name, symbolic in links:
            target, source = within(destination, member), within(destination, target_name)
            if symbolic:
                need(not target.exists() and not target.is_symlink(), "conflicting-initramfs-link")
                target.symlink_to(os.path.relpath(source, target.parent))
            else:
                # CPIO may place the group's payload in its final alias.
                need(source.is_file() and target.is_file() and not source.is_symlink()
                     and not target.is_symlink(), "missing-initramfs-hardlink")
                if target.stat().st_size:
                    # Writing the inode (rather than replacing it) also updates
                    # aliases already joined by earlier records in this group.
                    with target.open("rb") as payload, source.open("wb") as shared:
                        shutil.copyfileobj(payload, shared, length=65536)
                target.unlink()
                os.link(source, target, follow_symlinks=False)
        for member, _target_name, _symbolic in links:
            within(destination, member)
    return records
