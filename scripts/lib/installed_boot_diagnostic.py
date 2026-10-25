"""Read-only, bounded installed boot metadata. Never qualification evidence."""
from __future__ import annotations

import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zlib
import time
from importlib.metadata import version

MIB = 1024 * 1024
MAX_BINARY = 256 * MIB
MAX_EXPANDED = 512 * MIB
MAX_ENTRIES = 100000
MAX_REPORT = MIB
CONFIG_KEYS = ('CONFIG_DRM', 'CONFIG_DRM_VIRTIO_GPU', 'CONFIG_DRM_SIMPLEDRM',
               'CONFIG_DRM_KMS_HELPER', 'CONFIG_VIRTIO', 'CONFIG_VIRTIO_PCI')
COMPONENTS = {
    'plymouthd': r'(?:usr/)?sbin/plymouthd',
    'plymouth': r'(?:usr/)?bin/plymouth',
    'password_agent': r'(?:usr/)?lib/systemd/systemd-ask-password-plymouth',
    'cryptsetup': r'(?:usr/)?(?:sbin|bin)/cryptsetup',
    'virtio_gpu': r'(?:usr/)?lib/modules/[^/]+/kernel/drivers/gpu/drm/virtio/virtio_gpu\.ko(?:\.(?:xz|gz|zst))?',
    'simpledrm': r'(?:usr/)?lib/modules/[^/]+/kernel/drivers/gpu/drm/tiny/simpledrm\.ko(?:\.(?:xz|gz|zst))?',
    'plymouth_drm_plugin': r'(?:usr/)?lib(?:64)?/plymouth/renderers/drm\.so',
    'drm': r'(?:usr/)?lib/modules/[^/]+/kernel/drivers/gpu/drm/drm\.ko(?:\.(?:xz|gz|zst))?',
}


class Refused(ValueError):
    """Fixed machine-readable reason, never guest text."""


def require(test, reason):
    if not test:
        raise Refused(reason)


def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def regular(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    require(path.is_relative_to(root) and path != root, 'disk_outside_owned_directory')
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), 'symlink_path')
    st = path.stat()
    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.getuid(), 'not_owned_regular_file')
    return st.st_dev, st.st_ino, st.st_size


def qcow_header(path):
    # Refuse backing files and external data before any image library sees it.
    with Path(path).open('rb') as stream:
        header = stream.read(104)
    require(len(header) >= 72 and header[:4] == b'QFI\xfb', 'not_qcow2')
    version = struct.unpack_from('>I', header, 4)[0]
    require(version in (2, 3), 'unsupported_qcow_version')
    require(struct.unpack_from('>Q', header, 8)[0] == 0 and
            struct.unpack_from('>I', header, 16)[0] == 0, 'backing_file')
    require(0 < struct.unpack_from('>Q', header, 24)[0] <= 64 * 1024**3, 'virtual_size')
    require(struct.unpack_from('>I', header, 32)[0] == 0, 'encrypted_qcow')
    if version == 3:
        require(len(header) >= 104 and struct.unpack_from('>Q', header, 72)[0] == 0,
                'unsupported_qcow_features')


def safe_options(raw):
    require(len(raw) <= 16384, 'options_limit')
    safe = []
    redacted = 0
    for token in raw.split():
        if token in ('rhgb', 'quiet', 'console=tty0', 'console=ttyS0,115200n8') or re.fullmatch(r'drm.debug=0x[0-9a-fA-F]{1,2}', token):
            safe.append(token)
        else:
            redacted += 1
    return {'safe': safe, 'redacted_count': redacted, 'sha256': digest(raw.encode())}


def kernel_config(raw):
    require(len(raw) <= MIB, 'config_limit')
    text = raw.decode('ascii', errors='replace')
    result = {key: 'unknown' for key in CONFIG_KEYS}
    for key in CONFIG_KEYS:
        values = re.findall(r'^' + key + r'=([ymn])$', text, re.M)
        if re.search(r'^# ' + key + r' is not set$', text, re.M):
            values.append('n')
        require(len(values) <= 1, 'ambiguous_kernel_config')
        if values:
            result[key] = values[0]
    return result


def decode_zstd(blob, limit, deadline):
    """Find one complete frame, then decode with bounded streaming reads."""
    try:
        import zstandard as zstd
        require(version('zstandard') == '0.25.0', 'zstd_version')
        header = zstd.frame_header_size(blob)
        params = zstd.get_frame_parameters(blob)
        require(params.window_size <= 64*MIB, 'zstd_window_limit')
        require(params.dict_id == 0, 'zstd_dictionary')
        require(params.content_size in (zstd.CONTENTSIZE_UNKNOWN, zstd.CONTENTSIZE_ERROR)
                or params.content_size <= limit, 'expanded_or_truncated_archive')
        cursor = header
        for _ in range(100000):
            require(time.monotonic() < deadline, 'archive_timeout')
            require(cursor+3 <= len(blob), 'truncated_zstd')
            block = int.from_bytes(blob[cursor:cursor+3], 'little')
            cursor += 3
            kind, size = (block >> 1) & 3, block >> 3
            require(kind != 3 and size <= 128*1024, 'invalid_zstd_block')
            cursor += 1 if kind == 1 else size
            require(cursor <= len(blob), 'truncated_zstd')
            if block & 1:
                break
        else:
            raise Refused('zstd_block_limit')
        cursor += 4 if params.has_checksum else 0
        require(cursor <= len(blob), 'truncated_zstd')
        decoded = bytearray()
        with zstd.ZstdDecompressor(max_window_size=64*MIB).stream_reader(
                io.BytesIO(blob[:cursor]), read_across_frames=False) as stream:
            while True:
                require(time.monotonic() < deadline, 'archive_timeout')
                chunk = stream.read(min(65536, limit-len(decoded)+1))
                if not chunk:
                    break
                decoded.extend(chunk)
                require(len(decoded) <= limit, 'expanded_or_truncated_archive')
        return bytes(decoded), blob[cursor:]
    except ImportError:
        raise Refused('zstd_dependency_missing') from None
    except zstd.ZstdError:
        raise Refused('invalid_zstd') from None


def archive_metadata(blob, *, deadline=None):
    """Parse newc/gzip/XZ/ZSTD segments without extraction, links or guest execution.

    UKI is unsupported. Each compressed member and decoded byte is bounded.
    Raw names/content never appear in output. Key entries are never fingerprinted.
    """
    require(len(blob) <= MAX_BINARY, 'initramfs_limit')
    report = {'components': {}, 'theme_files': 0, 'password_units': 0,
              'module_initialization': 'not_observed', 'dracut_modules': [], 'theme_selection': 'unresolved'}
    deadline = time.monotonic()+30 if deadline is None else deadline
    members = 0
    expanded = len(blob)
    entries = 0
    pending = blob
    while pending:
        require(time.monotonic() < deadline, 'archive_timeout')
        pending = pending.lstrip(b'\0')
        if not pending:
            break
        if pending.startswith((b'\x1f\x8b', b'\xfd7zXZ\x00', b'\x28\xb5\x2f\xfd')):
            members += 1
            require(members <= 64, 'compression_member_limit')
        if pending.startswith(b'\x28\xb5\x2f\xfd'):
            decoded, remaining = decode_zstd(pending, MAX_EXPANDED-expanded, deadline)
            expanded += len(decoded)
            pending = decoded + remaining
            continue
        if pending.startswith(b'\x1f\x8b'):
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            decoded = decoder.decompress(pending, MAX_EXPANDED - expanded + 1)
            expanded += len(decoded)
            require(expanded <= MAX_EXPANDED and decoder.eof, 'expanded_or_truncated_archive')
            pending = decoded + decoder.unused_data
            continue
        if pending.startswith(b'\xfd7zXZ\x00'):
            decoder = lzma.LZMADecompressor(memlimit=64 * MIB)
            decoded = decoder.decompress(pending, max_length=MAX_EXPANDED - expanded + 1)
            expanded += len(decoded)
            require(expanded <= MAX_EXPANDED and decoder.eof, 'expanded_or_truncated_archive')
            pending = decoded + decoder.unused_data
            continue
        require(pending.startswith(b'070701'), 'unsupported_archive_format')
        require(len(pending) >= 110, 'truncated_cpio')
        try:
            fields = [int(pending[6+i*8:14+i*8], 16) for i in range(13)]
        except ValueError:
            raise Refused('invalid_cpio') from None
        mode, size, namesize = fields[1], fields[6], fields[11]
        require(0 < namesize <= 4096 and size <= MAX_BINARY, 'cpio_limits')
        end_name = 110 + namesize
        start = (end_name + 3) & ~3
        end = start + size
        require(end <= len(pending) and pending[end_name-1:end_name] == b'\0', 'truncated_cpio')
        name = pending[110:end_name-1].decode('utf-8', errors='strict')
        name = name.removeprefix('./')
        require(not name.startswith('/') and '..' not in PurePosixPath(name).parts, 'archive_traversal')
        entries += 1
        require(entries <= MAX_ENTRIES, 'entry_limit')
        content = memoryview(pending)[start:end]
        if stat.S_ISREG(mode):
            for label, pattern in COMPONENTS.items():
                if re.fullmatch(pattern, name):
                    require(label not in report['components'], 'ambiguous_component')
                    report['components'][label] = {'sha256': digest(content), 'bytes': size}
            if name == 'lib/dracut/modules.txt' and size <= 65536:
                report['dracut_modules'] = sorted(set(bytes(content).decode('ascii', errors='replace').split()) & {'plymouth', 'crypt', 'dm', 'kernel-modules', 'drm'})
            if re.fullmatch(r'usr/share/plymouth/themes/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\.(?:plymouth|script|png)', name):
                report['theme_files'] += 1
            if re.fullmatch(r'(?:usr/)?lib/systemd/system/(?:plymouth|systemd-ask-password)[A-Za-z0-9_.@-]*\.(?:service|path)', name):
                report['password_units'] += 1
        # Symlinks/devices are ignored, never followed or created.
        pending = pending[(end + 3) & ~3:]
    return report


def guest_regular(g, path, limit, budget=None):
    require(path.startswith('/') and '..' not in PurePosixPath(path).parts, 'guest_path')
    for item in reversed((PurePosixPath(path), *PurePosixPath(path).parents)):
        require(not g.is_symlink(str(item)), 'guest_symlink')
    require(g.is_file(path, followsymlinks=False), 'guest_not_regular')
    size = g.filesize(path)
    require(0 <= size <= limit, 'guest_file_limit')
    if budget is not None:
        budget[0] -= size
        require(budget[0] >= 0, 'guest_total_limit')
    data = bytearray()
    while len(data) < size:
        chunk = g.pread(path, min(128 * 1024, size - len(data)), len(data))
        require(chunk and len(chunk) <= size-len(data), 'guest_file_changed')
        data.extend(chunk)
    require(g.filesize(path) == size, 'guest_file_changed')
    return bytes(data)


def inspect_boot(g):
    """No inspect_os, LVM, unlock, guest command, root mount or extraction."""
    budget = [512*MIB]
    def read(path, limit):
        return guest_regular(g, path, limit, budget)
    filesystems = g.list_filesystems()
    require(0 < len(filesystems) <= 32, 'partition_count')
    require(any(fs == 'crypto_LUKS' for fs in filesystems.values()), 'luks_not_observed')
    candidates = []
    boot_metadata = []
    # Only EFI System Partition or XBOOTLDR GPT GUIDs. Generic Linux FS is
    # ambiguous (possibly root), so do not mount it to guess its role.
    roles = {'c12a7328-f81f-11d2-ba4b-00a0c93ec93b', 'bc13c2ff-59e6-4262-a352-b275fd6f7172'}
    for device, fs in filesystems.items():
        require(re.fullmatch(r'/dev/sda[0-9]+', device) is not None, 'unknown_partition_layout')
        number = int(device.removeprefix('/dev/sda'))
        guid = g.part_get_gpt_type('/dev/sda', number).lower()
        labelled_boot = guid == '0fc63daf-8483-4772-8e79-3d69d8477de4' and g.vfs_label(device) == 'boot'
        if guid in roles or labelled_boot:
            require(fs in ('vfat', 'ext4'), 'encrypted_or_unsupported_boot')
            candidates.append((device, fs))
    require(candidates, 'boot_role_unproven')
    reports = []
    selected = []
    for device, fs in candidates:
        g.mount_options('ro,noload' if fs == 'ext4' else 'ro', device, '/')
        try:
            default_entry = None
            require(not any(g.is_dir(path, followsymlinks=False) for path in ('/etc', '/root', '/home')), 'root_layout_refused')
            for name in ('/loader/loader.conf', '/grub2/grubenv', '/EFI/BOOT/BOOTX64.EFI'):
                if g.is_file(name, followsymlinks=False):
                    data = read(name, 8*MIB if name.endswith('.EFI') else 65536)
                    if name in ('/loader/loader.conf','/grub2/grubenv'):
                        pattern = r'^default[ \t]+([A-Za-z0-9_.-]+)$' if name.endswith('loader.conf') else r'^saved_entry=([A-Za-z0-9_.-]+)$'
                        matches = re.findall(pattern, data.decode('ascii', errors='replace'), re.M)
                        if len(matches) == 1:
                            default_entry = matches[0]
                    boot_metadata.append({'kind': {'/loader/loader.conf':'loader_config',
                        '/grub2/grubenv':'grub_environment', '/EFI/BOOT/BOOTX64.EFI':'efi_fallback'}[name],
                        'sha256':digest(data), 'bytes':len(data)})
            entries = []
            if g.is_dir('/loader/entries', followsymlinks=False):
                require(not g.is_symlink('/loader'), 'guest_symlink')
                names = g.ls('/loader/entries')
                require(len(names) <= 16, 'boot_entry_limit')
                for name in sorted(names):
                    require(re.fullmatch(r'[A-Za-z0-9_.-]+\.conf', name) is not None, 'unknown_entry_name')
                    raw = read('/loader/entries/' + name, 65536)
                    fields = {}
                    for line in raw.decode('utf-8').splitlines():
                        key, _, value = line.partition(' ')
                        if key in ('linux', 'initrd', 'options'):
                            require(key not in fields, 'multiple_boot_fields')
                            fields[key] = value.strip()
                    require('linux' in fields and 'initrd' in fields, 'unsupported_boot_entry')
                    kernel = read(fields['linux'], MAX_BINARY)
                    initrd = read(fields['initrd'], MAX_BINARY)
                    config = {key: 'unknown' for key in CONFIG_KEYS}
                    # Exact kernel basename mapping only; never search encrypted root.
                    base = PurePosixPath(fields['linux']).name
                    if base.startswith('vmlinuz-'):
                        config_path = str(PurePosixPath(fields['linux']).parent / ('config-' + base[8:]))
                        if g.is_file(config_path, followsymlinks=False):
                            config = kernel_config(read(config_path, MIB))
                    if default_entry in (name, name.removesuffix('.conf')):
                        selected.append(digest(raw))
                    entries.append({'entry_sha256': digest(raw), 'kernel_sha256': digest(kernel),
                                    'initramfs_sha256': digest(initrd),
                                    'options': safe_options(fields.get('options', '')),
                                    'kernel_config': config, 'archive': archive_metadata(initrd)})
            reports.extend(entries)
            require(len(reports) <= 8, 'kernel_candidate_limit')
        finally:
            g.umount_all()
    require(reports, 'uki_or_selection_unsupported')
    return {'selection': 'configured_default_not_runtime_observed' if len(selected) == 1 else 'unresolved',
            'selected_entry_sha256': selected[0] if len(selected) == 1 else None, 'candidates': reports,
            'runtime_initialization': 'not_observed', 'qualified': False,
            'encrypted_container_present': True, 'boot_metadata': boot_metadata}


def provenance(value):
    require(isinstance(value, dict), 'provenance_type')
    output = {'repository': 'tuna-os/tunaOS'}
    require(value.get('repository') == output['repository'], 'repository')
    for key in ('collector_sha', 'producer_sha'):
        require(re.fullmatch(r'[0-9a-f]{40}', str(value.get(key, ''))) is not None, 'source_sha')
        output[key] = value[key]
    for key in ('source', 'overlay', 'installer', 'engine', 'media', 'archive'):
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', str(value.get(key, ''))) is not None, 'digest')
        output[key] = value[key]
    for key in ('producer_run', 'producer_attempt', 'artifact_id', 'run', 'attempt'):
        require(type(value.get(key)) is int and value[key] > 0, 'run_identity')
        output[key] = value[key]
    return output


def write_report(directory, report):
    directory = Path(directory)
    directory.mkdir(mode=0o700, exist_ok=False)
    raw = (json.dumps(report, sort_keys=True) + '\n').encode()
    require(len(raw) <= MAX_REPORT, 'report_limit')
    (directory / 'report.json').write_bytes(raw)
    manifest = {'schema': 'InstalledBootDiagnosticManifest/v1',
                'files': [{'name': 'report.json', 'bytes': len(raw), 'sha256': digest(raw)}]}
    (directory / 'manifest.json').write_text(json.dumps(manifest) + '\n')
