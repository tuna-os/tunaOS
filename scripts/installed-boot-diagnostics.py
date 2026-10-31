#!/usr/bin/env python3
"""Best-effort boot-only provenance after a pre-secret strict LUKS failure.

Never qualification. No root unlock, inspect_os, guest command, host device,
config dump, disk export or initramfs extraction. The existing boot inspector
owns partition selection, readonly mounts, symlink checks and archive decoding.
Only its allowlisted metadata and BLS-referenced public kernel/initrd paths
leave the appliance. Initrd bytes exist in memory only; no downloaded initrd
or appliance output is retained. The original boot failure remains decisive.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import signal
import stat
import subprocess
import sys

from lib import installed_boot_diagnostic as d

INSPECTION_SECONDS = 180
GUESTFS_VERSION = (1, 52, 0)
ENTRY_PATH = re.compile(r'/loader(?:\.[01])?/entries/[A-Za-z0-9_.-]{1,128}\.conf')
# bootc's BLS entries reference the public artifacts at the boot root or in
# /ostree/<deployment>. Do not let a forged BLS field read arbitrary configs.
BOOT_PREFIX = r'/(?:ostree/[A-Za-z0-9_.+-]{1,160}/)?'
BOOT_PATHS = {
    'linux': re.compile(BOOT_PREFIX + r'(?:vmlinuz(?:-[A-Za-z0-9_.+-]+)?|linux)'),
    'initrd': re.compile(BOOT_PREFIX + r'(?:initramfs|initrd)[A-Za-z0-9_.+-]*'),
}
REFUSALS = frozenset((
    'not_qcow2', 'backing_file', 'encrypted_qcow', 'unsupported_qcow_features',
    'unsupported_qcow_version', 'virtual_size', 'not_owned_regular_file',
    'disk_outside_owned_directory', 'symlink_path', 'disk_file_limit',
    'pre_secret_proof_missing', 'qemu_still_running', 'qemu_exit_unproven',
    'guestfs_version', 'disk_changed', 'luks_not_observed', 'boot_role_unproven',
    'encrypted_or_unsupported_boot', 'unknown_partition_layout', 'root_layout_refused',
    'partition_count', 'guest_symlink', 'guest_not_regular', 'guest_path',
    'guest_file_limit', 'guest_file_changed', 'guest_total_limit', 'boot_entry_limit',
    'unknown_entry_name', 'multiple_boot_fields', 'unsupported_boot_entry',
    'kernel_candidate_limit', 'uki_or_selection_unsupported', 'boot_path_refused',
    'boot_trace_limit', 'unmapped_boot_entry', 'invalid_utf8', 'archive_traversal',
    'unsupported_archive_format', 'initramfs_limit', 'entry_limit', 'archive_timeout',
    'zstd_dependency_missing', 'zstd_version', 'zstd_window_limit', 'zstd_dictionary',
    'expanded_or_truncated_archive', 'compression_member_limit', 'truncated_cpio',
    'invalid_cpio', 'cpio_limits', 'ambiguous_component', 'boot_trace_incomplete',
))


def refusal(error):
    """Never persist exception text, guest configuration or helper stderr."""
    return str(error) if isinstance(error, d.Refused) and str(error) in REFUSALS else 'inspection_refused'


def before_secret(receipt):
    if not isinstance(receipt, dict):
        return False
    observed = receipt.get('observations')
    frame = receipt.get('retained_frame')
    frames = receipt.get('frames')
    return (
        receipt.get('kind') == 'installed_boot_screen_gate'
        and receipt.get('status') == 'prompt_not_observed'
        and receipt.get('secret_entries') == []
        and isinstance(observed, dict)
        and observed.get('prompt') == 'prompt_not_observed'
        and observed.get('unlocked') is False
        and observed.get('emergency') is False
        and isinstance(frame, dict)
        and frame.get('phase') == 'before_secret_entry'
        and frame.get('captured_before_secret_entry') is True
        and frame.get('file') == 'frame-000.ppm'
        and isinstance(frame.get('sha256'), str)
        and re.fullmatch(r'[a-f0-9]{64}', frame['sha256']) is not None
        and isinstance(frames, list) and 0 < len(frames) <= 400
        and all(isinstance(f, dict) and f.get('phase') == 'before_secret_entry' for f in frames)
    )


def stopped(pid):
    d.require(type(pid) is int and pid > 1, 'qemu_exit_unproven')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    except OSError:
        raise d.Refused('qemu_exit_unproven') from None
    raise d.Refused('qemu_still_running')


def public_boot_path(value, kind):
    d.require(isinstance(value, str) and len(value) <= 512
              and '..' not in PurePosixPath(value).parts
              and BOOT_PATHS[kind].fullmatch(value) is not None, 'boot_path_refused')
    return value


class BootPaths:
    """Transparent adapter: the existing inspector still validates every read.

    Record only bounded BLS-entry reads while it runs. The raw entries remain
    private memory, used only to associate already-validated artifact paths
    with inspect_boot's entry hashes. Never retain options, titles or IDs.
    """
    def __init__(self, guest):
        self.guest = guest
        self.device = None
        self.entries = []
        self.artifacts = set()

    def __getattr__(self, name):
        return getattr(self.guest, name)

    def mount_options(self, options, device, mountpoint):
        d.require(options in ('ro', 'ro,noload') and mountpoint == '/', 'boot_path_refused')
        d.require(re.fullmatch(r'/dev/sda[0-9]{1,3}', device) is not None, 'unknown_partition_layout')
        self.guest.mount_options(options, device, mountpoint)
        self.device = device

    def pread(self, path, count, offset):
        entry = ENTRY_PATH.fullmatch(path)
        known_metadata = (path in ('/loader/loader.conf', '/loader.0/loader.conf',
                                  '/loader.1/loader.conf', '/grub2/grubenv', '/EFI/BOOT/BOOTX64.EFI')
                          or re.fullmatch(r'/usr/lib/modules/[A-Za-z0-9_.+-]+/config', path))
        d.require(entry or known_metadata or path in self.artifacts, 'boot_path_refused')
        chunk = self.guest.pread(path, count, offset)
        if entry:
            # guest_regular checks the 64 KiB entry limit before pread, so it
            # must arrive as one complete read. Refuse rather than partially
            # parsing a changing entry or caching private arbitrary data.
            d.require(offset == 0 and len(chunk) <= 65536 and len(chunk) == self.guest.filesize(path),
                      'boot_trace_incomplete')
            d.require(len(self.entries) < 16, 'boot_trace_limit')
            try:
                text = bytes(chunk).decode('utf-8')
            except UnicodeError:
                raise d.Refused('invalid_utf8') from None
            fields = {}
            for line in text.splitlines():
                key, separator, value = line.partition(' ')
                if separator and key in ('linux', 'initrd'):
                    d.require(key not in fields, 'multiple_boot_fields')
                    fields[key] = public_boot_path(value.strip(), key)
            d.require(set(fields) == {'linux', 'initrd'}, 'unsupported_boot_entry')
            self.artifacts.update(fields.values())
            self.entries.append({'boot_partition': self.device, 'entry_path': path,
                                 'entry_sha256': d.digest(chunk), 'kernel_path': fields['linux'],
                                 'initramfs_path': fields['initrd']})
        return chunk


def metadata(guest):
    """Use the existing inspector; project only the requested public facts."""
    paths = BootPaths(guest)
    inspected = d.inspect_boot(paths)
    candidates = []
    for item in inspected['candidates']:
        matches = [entry for entry in paths.entries if entry['entry_sha256'] == item['entry_sha256']]
        d.require(len(matches) > 0, 'unmapped_boot_entry')
        archive = item['archive']  # archive_metadata already decoded in memory, without extraction.
        selected_theme = archive['theme_selection']
        theme_valid = (isinstance(selected_theme, str)
                       and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', selected_theme)
                       and archive['theme_evidence']['theme_file'] is True)
        candidates.append({
            'paths': matches,
            'entry_sha256': item['entry_sha256'],
            'kernel_sha256': item['kernel_sha256'],
            'initramfs_sha256': item['initramfs_sha256'],
            'components': archive['components'],
            'drivers': archive['drivers'],
            'dracut_modules': archive['dracut_modules'],
            'theme_selection': selected_theme if theme_valid else 'unresolved',
            # Public asset availability, not raw contents. The initramfs hash
            # binds this evidence to the actual bytes read from the boot disk.
            'public_theme_assets': archive['theme_evidence'],
        })
    selected = inspected['selected_entry_sha256']
    # A configured default is not a runtime-observed selection. A duplicate
    # entry hash across boot partitions is ambiguous even if defaults match.
    resolved = selected is not None and sum(
        len(item['paths']) for item in candidates if item['entry_sha256'] == selected) == 1
    return {'selection': inspected['selection'] if resolved else 'unresolved',
            'selected_entry_sha256': selected if resolved else None,
            'runtime_initialization': 'not_observed',
            'candidates': candidates}


def owned_regular(path, directory):
    d.require('..' not in Path(path).parts and '..' not in Path(directory).parts, 'boot_path_refused')
    return d.regular(path, directory)


def read_receipt(receipt_path, directory):
    identity = owned_regular(receipt_path, directory)
    d.require(identity[2] <= d.MAX_REPORT, 'pre_secret_proof_missing')
    try:
        receipt = json.loads(Path(receipt_path).read_bytes())
    except (ValueError, UnicodeError):
        raise d.Refused('pre_secret_proof_missing') from None
    d.require(before_secret(receipt), 'pre_secret_proof_missing')
    d.require(identity == owned_regular(receipt_path, directory), 'disk_changed')
    return identity


def inspect_disk(disk, directory, receipt_path, pid, factory=None):
    """Attach exactly one owned qcow2, readonly, after proof QEMU exited."""
    stopped(pid)
    before = owned_regular(disk, directory)
    d.require(before[2] <= 65 * 1024**3, 'disk_file_limit')
    d.qcow_header(disk)
    receipt_before = read_receipt(receipt_path, directory)
    if factory is None:
        import guestfs
        factory = guestfs.GuestFS
    guest = factory(python_return_dict=True)
    try:
        version = guest.version()
        d.require(tuple(version[key] for key in ('major', 'minor', 'release')) == GUESTFS_VERSION,
                  'guestfs_version')
        guest.set_backend('direct')
        guest.set_network(False)
        guest.set_memsize(1024)
        guest.set_smp(2)
        guest.add_drive_opts(str(disk), readonly=True, format='qcow2')
        guest.launch()
        stopped(pid)
        result = metadata(guest)
        d.require(before == owned_regular(disk, directory)
                  and receipt_before == owned_regular(receipt_path, directory), 'disk_changed')
        return result
    finally:
        guest.close()  # The shared parser never downloads/extracts an initrd; nothing can become an artifact.


def safe_output(path, directory):
    root = Path(directory).absolute()
    path = Path(path).absolute()
    d.require('..' not in root.parts and '..' not in path.parts, 'boot_path_refused')
    d.require(path.parent == root and path.name == 'strict-installed-boot-diagnostics.log', 'boot_path_refused')
    for parent in (root, *root.parents):
        d.require(not parent.is_symlink(), 'symlink_path')
    # The workflow creates OUTPUT_DIR as the runner before entering sudo.
    # Like d.regular(), require ownership of files, not every ancestor:
    # the inspected disk and any existing report must belong to this UID.
    # The output directory itself must not be group/world writable.
    d.require(root.is_dir() and root.stat().st_mode & 0o022 == 0, 'not_owned_regular_file')
    if path.exists() or path.is_symlink():
        d.regular(path, root)
    return path


def write_output(path, report):
    data = json.dumps(report, sort_keys=True, indent=2).encode() + b'\n'
    d.require(len(data) <= d.MAX_REPORT, 'boot_trace_limit')
    # Refuse symlinks and hardlinks before truncating an existing destination.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        info = os.fstat(stream.fileno())
        d.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                  and info.st_uid == os.getuid(), 'not_owned_regular_file')
        stream.truncate()
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--observation', type=Path, required=True)
    parser.add_argument('--qemu-pid', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--eligible', action='store_true', help='Validate only the pre-secret receipt; never open a disk')
    args = parser.parse_args()
    if args.eligible:
        try:
            read_receipt(args.observation, args.directory)
        except Exception:  # noqa: BLE001 - eligibility has no free-form diagnostics
            return 1
        return 0
    report = {'kind': 'installed_boot_provenance_diagnostic', 'qualified': False, 'status': 'not_collected'}
    if args.worker:
        try:
            # Same appliance memory policy as the existing diagnostic worker.
            resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
            report['boot'] = inspect_disk(args.disk, args.directory, args.observation, args.qemu_pid)
            report['status'] = 'collected'
        except ImportError:
            report['reason'] = 'guestfs_dependency_missing'
        except Exception as error:  # noqa: BLE001 - sanitized diagnostic boundary
            report['reason'] = refusal(error)
        print(json.dumps(report))
        return 0
    output = safe_output(args.output, args.directory)
    # Persist unavailability even if launch/inspection fails. It can never
    # replace the original strict boot failure or produce qualification.
    write_output(output, report)
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--worker']
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True,
                                   env={'PATH': os.defpath, 'HOME': os.path.expanduser('~'),
                                        'LANG': 'C.UTF-8', 'LIBGUESTFS_BACKEND': 'direct'})
        stdout, _ = process.communicate(timeout=INSPECTION_SECONDS)
        d.require(process.returncode == 0 and len(stdout) <= d.MAX_REPORT, 'inspection_failed')
        result = json.loads(stdout)
        d.require(isinstance(result, dict) and result.get('qualified') is False
                  and result.get('kind') == report['kind'], 'inspection_failed')
        report = result
    except subprocess.TimeoutExpired:
        report['reason'] = 'inspection_timeout'
    except Exception as error:  # noqa: BLE001 - no paths, exception strings or child stderr
        report['reason'] = refusal(error)
    finally:
        if process is not None and process.poll() is None:
            # Still owned and unreaped: stop the worker's entire group,
            # including the appliance, on timeout or a parent-side failure.
            try:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                report = {'kind': report['kind'], 'qualified': False,
                          'status': 'not_collected', 'reason': 'inspector_stop_unproven'}
    write_output(output, report)
    print('INSTALLED_BOOT_DIAGNOSTICS status=' + report['status'])
    return 0 if report['status'] == 'collected' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001 - never publish free-form host or guest errors
        print('INSTALLED_BOOT_DIAGNOSTICS status=not_collected reason=collector_unavailable')
        raise SystemExit(1) from None
