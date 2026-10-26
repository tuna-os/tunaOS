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
    'password_agent': r'usr/bin/systemd-tty-ask-password-agent',
    'ask_password_plymouth_path': r'usr/lib/systemd/system/systemd-ask-password-plymouth\.path',
    'ask_password_plymouth_service': r'usr/lib/systemd/system/systemd-ask-password-plymouth\.service',
    'cryptsetup': r'(?:usr/)?(?:sbin|bin)/cryptsetup',
    'plymouth_drm_plugin': r'(?:usr/)?lib(?:64)?/plymouth/renderers/drm\.so',
}
DRIVER_MODULES = {'virtio_gpu': 'virtio_gpu', 'simpledrm': 'simpledrm', 'drm': 'drm'}
MODULE_FILES = re.compile(r'(?:usr/)?lib/modules/[^/]+/modules\.(?:builtin|dep)$')
THEME_CONF = ('etc/plymouth/plymouthd.conf', 'usr/share/plymouth/plymouthd.defaults')
THEME_PATH = re.compile(r'usr/share/plymouth/themes/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)\.(plymouth|script|png)$')
PLUGIN_PATH = re.compile(r'(?:usr/)?lib(?:64)?/plymouth/([A-Za-z0-9_-]+)\.so$')
FONT_PATH = re.compile(r'usr/share/fonts/[A-Za-z0-9_./-]+\.(?:ttf|otf|pfb|pfm|pf2)$')


class Refused(ValueError):
    """Fixed machine-readable reason plus explicitly safe diagnostic facts."""
    def __init__(self, reason, details=None):
        self.details = details or {}
        super().__init__(reason)


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

LUKS_ID = r'(?:luks-)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
LUKS_NAME = r'[A-Za-z0-9_.+-]{1,64}'
LUKS_OPTION = r'(?:discard|no-read-workqueue|no-write-workqueue|same-cpu-crypt|submit-from-crypt-cpus)'


def safe_options(raw):
    require(len(raw) <= 16384, 'options_limit')
    safe = []
    redacted = 0
    for token in raw.split():
        if token in ('rhgb', 'quiet', 'splash', 'nomodeset'):
            safe.append(token)
        elif re.fullmatch(r'drm\.debug=0x[0-9a-fA-F]{1,2}', token):
            safe.append(token)
        elif token.startswith('root='):
            name, separator, _ = token.partition('=')
            safe.append(name + '=<redacted>' if separator else name)
        elif token == 'rd.luks.allow-discards' or re.fullmatch(r'rd\.luks(?:=|\.crypttab=)[01]', token):
            safe.append(token)
        elif re.fullmatch(rf'rd\.luks\.uuid={LUKS_ID}', token):
            safe.append('rd.luks.uuid=<redacted>')
        elif re.fullmatch(rf'rd\.luks\.name={LUKS_ID}={LUKS_NAME}', token):
            safe.append('rd.luks.name=<redacted>')
        elif re.fullmatch(rf'rd\.luks\.options={LUKS_ID}={LUKS_OPTION}(?:,{LUKS_OPTION})*', token):
            safe.append('rd.luks.options=<redacted>')
        elif token.startswith('rd.luks.'):
            redacted += 1
        elif re.fullmatch(r'console=(?:tty\d{1,2}|ttyS\d{1,2}|ttyAMA\d{1,2}|ttyUSB\d{1,2}|hvc\d{1,2}|xvc\d{1,2})(?:,\d{4,7}[neo][0-9]?)?', token):
            safe.append(token)
        elif re.fullmatch(r'plymouth\.(?:enable|debug)=[01]|plymouth\.ignore-serial-consoles', token):
            safe.append(token)
        elif re.fullmatch(r'rd\.plymouth=[01]', token):
            safe.append(token)
        elif re.fullmatch(r'rd\.driver\.(?:blacklist|whitelist)=(?:nouveau|nvidia(?:_drm|_modeset|_uvm)?|virtio_gpu|bochs|simpledrm|drm)(?:,(?:nouveau|nvidia(?:_drm|_modeset|_uvm)?|virtio_gpu|bochs|simpledrm|drm))*', token):
            safe.append(token)
        elif re.fullmatch(r'video=(?:HDMI-(?:[A-C]-\d{1,2}|\d{1,2})|DP-\d{1,2}|DVI-[A-I]-\d{1,2}|VGA-\d{1,2}|eDP-\d{1,2}|LVDS-\d{1,2}|DSI-\d{1,2}):\d{3,5}x\d{3,5}(?:@\d{2,3})?', token):
            safe.append(token)
        elif re.fullmatch(r'vt\.(?:global_cursor_default|default_redraw)=[01]', token):
            safe.append(token)
        elif re.fullmatch(r'fbcon=(?:nodefer|map:\d{1,2}|rotate:[0-3])', token):
            safe.append(token)
        elif re.fullmatch(r'systemd\.show_status=(?:0|1|auto|true|false)', token):
            safe.append(token)
        else:
            redacted += 1
    return {'safe': safe, 'redacted_count': redacted, 'sha256': digest(raw.encode())}


def safe_partition_label(value):
    if not isinstance(value, str):
        return None
    known = {'boot': 'boot', 'efi': 'EFI', 'esp': 'ESP', 'xbootldr': 'XBOOTLDR'}
    return known.get(value.casefold(), '<redacted>') if len(value) <= 64 else '<redacted>'


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
    """Parse newc/gzip/XZ/ZSTD segments linearly without extracting them."""
    require(len(blob) <= MAX_BINARY, 'initramfs_limit')
    report = {'components': {}, 'theme_files': 0, 'password_units': 0,
              'module_initialization': 'not_observed', 'dracut_modules': [],
              'dracut_build_parameters_sha256': None, 'theme_selection': 'unresolved',
              'theme_evidence': {'theme_file': False, 'script_file': False,
                                 'script_plugin': False, 'label_plugin': False, 'font': False},
              'drivers': {name: 'unknown' for name in DRIVER_MODULES}}
    deadline = time.monotonic()+30 if deadline is None else deadline
    members = entries = 0
    expanded = len(blob)
    pending = memoryview(blob)
    pos = 0
    builtin, dependencies, module_files = set(), set(), set()
    module_metadata_seen = False
    theme_member_paths = set()
    theme_definitions = {}
    theme_settings = {path: set() for path in THEME_CONF}
    plugins, fonts = set(), False
    while pos < len(pending):
        require(time.monotonic() < deadline, 'archive_timeout')
        while pos < len(pending) and pending[pos] == 0:
            pos += 1
        if pos == len(pending):
            break
        rest = pending[pos:]
        if rest[:4] == b'\x28\xb5\x2f\xfd':
            members += 1
            require(members <= 64, 'compression_member_limit')
            decoded, remaining = decode_zstd(rest.tobytes(), MAX_EXPANDED-expanded, deadline)
            expanded += len(decoded)
            pending = memoryview(decoded + remaining)
            pos = 0
            continue
        if rest[:2] == b'\x1f\x8b':
            members += 1
            require(members <= 64, 'compression_member_limit')
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            decoded = decoder.decompress(rest, MAX_EXPANDED-expanded+1)
            expanded += len(decoded)
            require(expanded <= MAX_EXPANDED and decoder.eof, 'expanded_or_truncated_archive')
            pending = memoryview(decoded + decoder.unused_data)
            pos = 0
            continue
        if rest[:6] == b'\xfd7zXZ\x00':
            members += 1
            require(members <= 64, 'compression_member_limit')
            decoder = lzma.LZMADecompressor(memlimit=64*MIB)
            decoded = decoder.decompress(rest, max_length=MAX_EXPANDED-expanded+1)
            expanded += len(decoded)
            require(expanded <= MAX_EXPANDED and decoder.eof, 'expanded_or_truncated_archive')
            pending = memoryview(decoded + decoder.unused_data)
            pos = 0
            continue
        require(rest[:6] == b'070701', 'unsupported_archive_format')
        require(len(rest) >= 110, 'truncated_cpio')
        try:
            fields = [int(rest[6+i*8:14+i*8].tobytes(), 16) for i in range(13)]
        except ValueError:
            raise Refused('invalid_cpio') from None
        mode, size, namesize = fields[1], fields[6], fields[11]
        require(0 < namesize <= 4096 and size <= MAX_BINARY, 'cpio_limits')
        end_name = 110 + namesize
        start = (end_name + 3) & ~3
        end = start + size
        require(end <= len(rest) and rest[end_name-1:end_name] == b'\0', 'truncated_cpio')
        name = rest[110:end_name-1].tobytes().decode('utf-8', errors='strict').removeprefix('./')
        require(not name.startswith('/') and '..' not in PurePosixPath(name).parts, 'archive_traversal')
        entries += 1
        require(entries <= MAX_ENTRIES, 'entry_limit')
        content = rest[start:end]
        if stat.S_ISREG(mode):
            for label, pattern in COMPONENTS.items():
                if re.fullmatch(pattern, name):
                    require(label not in report['components'], 'ambiguous_component')
                    report['components'][label] = {'sha256': digest(content), 'bytes': size}
            if name == 'usr/lib/dracut/modules.txt' and size <= 65536:
                report['dracut_modules'] = sorted(set(bytes(content).decode('ascii', errors='replace').split()) & {'plymouth', 'crypt', 'dm', 'kernel-modules', 'drm', 'simpledrm', 'ostree', 'virtio_gpu', 'virtio-gpu'})
            if name == 'usr/lib/dracut/build-parameter.txt':
                report['dracut_build_parameters_sha256'] = digest(content)
            if MODULE_FILES.fullmatch(name) and size <= 16*MIB:
                module_metadata_seen = True
                lines = bytes(content).decode('ascii', errors='replace').splitlines()
                if name.endswith('modules.builtin'):
                    builtin.update(_module_name(line.strip().split(' ', 1)[0]) for line in lines if line.strip())
                else:
                    for line in lines:
                        module = line.partition(':')[0].strip()
                        if module:
                            dependencies.add(_module_name(module))
            if '/lib/modules/' in name and re.search(r'\.ko(?:\.(?:xz|gz|zst))?$', name):
                module_files.add(_module_name(name))
            match = THEME_PATH.fullmatch(name)
            if match:
                report['theme_files'] += 1
                theme_member_paths.add(name)
                if match.group(3) == 'plymouth' and size <= 65536:
                    theme_definitions[name] = bytes(content).decode('utf-8', errors='replace')
            if name in THEME_CONF and size <= 65536:
                theme_settings[name].update(re.findall(
                    r'^Theme\s*=\s*([A-Za-z0-9_-]+)\s*$', bytes(content).decode('utf-8', errors='replace'), re.M))
            plugin = PLUGIN_PATH.fullmatch(name)
            if plugin:
                plugins.add(plugin.group(1))
            fonts = fonts or bool(FONT_PATH.fullmatch(name))
            if re.fullmatch(r'usr/lib/systemd/system/systemd-ask-password-(?:plymouth|console)\.(?:service|path)', name):
                report['password_units'] += 1
        pos += (end + 3) & ~3
    module_metadata_present = module_metadata_seen or bool(module_files)
    for driver, module in DRIVER_MODULES.items():
        if module in builtin:
            report['drivers'][driver] = 'builtin'
        elif module in module_files:
            report['drivers'][driver] = 'module_in_initramfs'
        elif module in dependencies:
            report['drivers'][driver] = 'index_only'
        elif module_metadata_present:
            report['drivers'][driver] = 'module_not_in_initramfs'
    # The local daemon config overrides the packaged defaults when it names a theme.
    theme_values = theme_settings[THEME_CONF[0]] or theme_settings[THEME_CONF[1]]
    if len(theme_values) == 1:
        selected_theme = next(iter(theme_values))
        definition_path = f'usr/share/plymouth/themes/{selected_theme}/{selected_theme}.plymouth'
        text = theme_definitions.get(definition_path)
        module_names = set(re.findall(r'^ModuleName\s*=\s*([A-Za-z0-9_-]+)\s*$', text, re.M)) if text else set()
        script_files = set(re.findall(r'^ScriptFile\s*=\s*([A-Za-z0-9_./-]+)\s*$', text, re.M)) if text else set()
        report['theme_selection'] = selected_theme
        report['theme_evidence']['theme_file'] = definition_path in theme_definitions
        report['theme_evidence']['script_plugin'] = 'script' in module_names and 'script' in plugins
        report['theme_evidence']['script_file'] = len(script_files) == 1 and (
            _script_member_path(next(iter(script_files)), selected_theme) in theme_member_paths)
    report['theme_evidence']['label_plugin'] = 'label' in plugins
    report['theme_evidence']['font'] = fonts
    return report


def _module_name(path):
    name = PurePosixPath(path).name
    name = re.sub(r'\.ko(?:\.(?:xz|gz|zst))?$', '', name)
    return name.replace('-', '_')
def _script_member_path(value, theme):
    """Normalize a Plymouth ScriptFile reference without resolving archive symlinks."""
    if value.startswith('//'):
        return None
    if value.startswith('/'):
        value = value[1:]
    else:
        value = f'usr/share/plymouth/themes/{theme}/{value}'
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts:
        return None
    return path.as_posix()


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
    partition_summary = []
    # Only EFI System Partition or XBOOTLDR GPT GUIDs. Generic Linux FS is
    # ambiguous (possibly root), so do not mount it to guess its role.
    roles = {'c12a7328-f81f-11d2-ba4b-00a0c93ec93b', 'bc13c2ff-59e6-4262-a352-b275fd6f7172'}
    for device, fs in filesystems.items():
        require(re.fullmatch(r'/dev/sda[0-9]+', device) is not None, 'unknown_partition_layout')
        number = int(device.removeprefix('/dev/sda'))
        guid = g.part_get_gpt_type('/dev/sda', number).lower()
        try:
            label = g.vfs_label(device)
        except Exception:
            label = None
        partition_summary.append({'index': number, 'gpt_type_guid': guid,
                                  'filesystem': fs, 'label': safe_partition_label(label)})
        labelled_boot = guid == '0fc63daf-8483-4772-8e79-3d69d8477de4' and label == 'boot'
        if guid in roles or labelled_boot:
            if fs not in ('vfat', 'ext4'):
                raise Refused('encrypted_or_unsupported_boot', {'partitions': partition_summary})
            candidates.append((device, fs))
    if not candidates:
        raise Refused('boot_role_unproven', {'partitions': partition_summary})
    reports = []
    selected = []
    for device, fs in candidates:
        g.mount_options('ro,noload' if fs == 'ext4' else 'ro', device, '/')
        try:
            default_entry = None
            require(not any(g.is_dir(path, followsymlinks=False) for path in ('/etc', '/root', '/home')), 'root_layout_refused')
            loader_root = None
            if g.is_symlink('/loader'):
                target = g.readlink('/loader')
                require(target in ('loader.0', 'loader.1'), 'guest_symlink')
                loader_root = '/' + target
                require(g.is_dir(loader_root, followsymlinks=False), 'guest_symlink')
            elif g.is_dir('/loader', followsymlinks=False):
                loader_root = '/loader'
            loader_config = loader_root + '/loader.conf' if loader_root else None
            entry_dir = loader_root + '/entries' if loader_root else None
            if entry_dir:
                require(not g.is_symlink(entry_dir), 'guest_symlink')
            for name in (loader_config, '/grub2/grubenv', '/EFI/BOOT/BOOTX64.EFI'):
                if name and g.is_file(name, followsymlinks=False):
                    data = read(name, 8*MIB if name.endswith('.EFI') else 65536)
                    if name in (loader_config, '/grub2/grubenv'):
                        pattern = r'^default[ \t]+([A-Za-z0-9_.-]+)$' if name == loader_config else r'^saved_entry=([A-Za-z0-9_.-]+)$'
                        matches = re.findall(pattern, data.decode('ascii', errors='replace'), re.M)
                        if len(matches) == 1:
                            default_entry = matches[0]
                    boot_metadata.append({'kind': 'loader_config' if name == loader_config else
                        'grub_environment' if name == '/grub2/grubenv' else 'efi_fallback',
                        'sha256':digest(data), 'bytes':len(data)})
            entries = []
            if entry_dir and g.is_dir(entry_dir, followsymlinks=False):
                names = g.ls(entry_dir)
                require(len(names) <= 16, 'boot_entry_limit')
                for name in sorted(names):
                    require(re.fullmatch(r'[A-Za-z0-9_.-]+\.conf', name) is not None, 'unknown_entry_name')
                    raw = read(entry_dir + '/' + name, 65536)
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
                    # Exact EL10 kernel release mapping only; never search encrypted root.
                    base = PurePosixPath(fields['linux']).name
                    if base.startswith('vmlinuz-'):
                        config_path = '/usr/lib/modules/' + base[8:] + '/config'
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
