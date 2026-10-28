#!/usr/bin/env python3
"""Opt-in fresh-install diagnostic supervisor. Never native qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import select
import signal
import stat
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid

from lib import installed_boot_diagnostic as d

ROOT = Path(__file__).resolve().parents[1]
OWNED_SERVICES = []
# Root stderr stays disabled. Only these fixed refusals cross the service boundary.
ROOT_SCAN_REFUSALS = {
    'descriptor_scan_not_root': 80, 'descriptor_scan_owner': 81,
    'descriptor_scan_budget': 82, 'descriptor_scan_timeout': 83,
    'descriptor_disk_identity': 84, 'descriptor_result_changed': 85,
    'descriptor_result_directory': 86, 'descriptor_result_file': 87,
    'descriptor_metadata_handle': 88, 'descriptor_result_write': 89,
    'descriptor_ancestor_changed': 90, 'descriptor_object_changed': 91,
    'descriptor_object_type': 92, 'descriptor_handle_close_failed': 93,
    'descriptor_scan_arguments': 94, 'permission_denied': 95,
    'file_not_found': 96, 'os_error': 97, 'invalid_argument': 98,
}


def probe_descriptor_scan(output):
    """Two disposable inode controls; never build, boot, or inspect an image."""
    d.require(os.getuid() > 0 and os.geteuid() == os.getuid(), 'probe_runner_identity')
    output = Path(output).absolute()
    d.require(not any(p.is_symlink() for p in (output, *output.parents)), 'probe_output_symlink')
    output.mkdir(mode=0o700)
    report = {'schema': 'DescriptorScanReadiness/v1', 'qualification': False,
              'cases': [], 'passed': False}
    controls = []
    for name in ('closed', 'open'):
        directory = output / name
        directory.mkdir(mode=0o700)
        disk = directory / 'disposable-file'
        fd = os.open(disk, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        controls.append((name, directory, disk))
    try:
        for name, directory, disk in controls:
            expected = 'clear' if name == 'closed' else 'open'
            row = {'control': name, 'expected': expected, 'observed': 'unavailable',
                   'cleanup': 'not_started', 'passed': False}
            report['cases'].append(row)
            fd = os.open(disk, os.O_RDONLY | os.O_NOFOLLOW) if name == 'open' else None
            service_count = len(OWNED_SERVICES)
            evidence = {}
            reason = None
            try:
                identity = disk.stat()
                # Direct root readiness control, not a claimed permission denial.
                evidence = retry_denied_descriptor_scan(
                    disk, time.monotonic()+60, directory, {'stage': 'readiness_control'},
                    (identity.st_dev, identity.st_ino))
            except d.Refused as error:
                evidence, reason = error.details, str(error)
            except Exception:
                reason = 'probe_internal_failure'
            finally:
                if fd is not None:
                    os.close(fd)
            fallback = evidence.get('descriptor_fallback', {})
            row['observed'] = fallback.get('outcome', 'unavailable')
            row['cleanup'] = fallback.get('cleanup', 'not_started')
            code = fallback.get('service_exit_status')
            if type(code) is int and 0 <= code <= 255:
                row['service_exit_status'] = code
                if code:
                    row['service_refusal'] = next(
                        (key for key, value in ROOT_SCAN_REFUSALS.items() if value == code),
                        'unclassified')
            services = OWNED_SERVICES[service_count:]
            row['services_stopped'] = bool(services) and all(item.stopped for item in services)
            row['passed'] = (len(services) == 1 and row['services_stopped'] and
                             row['cleanup'] == 'stopped_result_retained' and
                             row['observed'] == expected and
                             reason == (None if name == 'closed' else 'disk_still_open'))
            if not row['services_stopped']:
                break
        report['passed'] = len(report['cases']) == 2 and all(row['passed'] for row in report['cases'])
    finally:
        stopped = True
        for service in OWNED_SERVICES:
            stopped = service.stop() and stopped
        report['services_stopped'] = stopped
        report['passed'] = report['passed'] and stopped
        # Upload this file only: no result tokens, paths, commands or raw errors.
        (output / 'report.json').write_text(json.dumps(report, sort_keys=True)+'\n')
    return 0 if report['passed'] else 77


def systemd_usec(value):
    if value.isdigit():
        return int(value)
    factors = {'us':1, 'ms':1000, 's':1000000, 'min':60000000, 'h':3600000000}
    total = 0
    for token in value.split():
        match = re.fullmatch(r'([0-9]+)(us|ms|s|min|h)', token)
        if not match:
            return None
        total += int(match.group(1)) * factors[match.group(2)]
    return total or None


def file_digest(path, deadline=None):
    path = Path(path).absolute()
    d.require(not any(p.is_symlink() for p in (path, *path.parents)), 'hash_symlink')
    before = path.stat()
    d.require(stat.S_ISREG(before.st_mode), 'hash_not_regular')
    h = hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        actual = os.fstat(stream.fileno())
        d.require((actual.st_dev,actual.st_ino) == (before.st_dev,before.st_ino), 'hash_file_changed')
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            d.require(deadline is None or time.monotonic() < deadline, 'hash_timeout')
            h.update(chunk)
    after = path.stat()
    d.require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) ==
              (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns), 'hash_file_changed')
    return 'sha256:' + h.hexdigest()


class OwnedQemu:
    """Lifetime-bound, non-restarting service per QEMU; never signal bare PIDs."""
    def __init__(self, executable, output):
        self.executable, self.output = executable, Path(output)
        self.children = []
        self.closed = self.stopped = False
        self.lock = threading.Lock()

    def launch(self, args):
        with self.lock:
            d.require(not self.closed and len(self.children) < 8, 'launch_closed_or_limit')
            d.require(all(child.poll() is not None for child in self.children), 'previous_qemu_alive')
            d.require(args.count('-daemonize') == 1 and args.count('-pidfile') == 1, 'launch_shape')
            pidfile = Path(args[args.index('-pidfile') + 1])
            d.require(pidfile == self.output/'qemu.pid', 'pidfile_not_owned')
            child = ContainedProcess([self.executable, *[arg for arg in args if arg != '-daemonize']],
                                     supplementary_groups=('kvm',))
            self.children.append(child)
            d.require(child.pid > 0 and sum(c.pid == child.pid for c in self.children) == 1, 'ambiguous_qemu_pid')
            deadline = time.monotonic()+30
            while time.monotonic() < deadline:
                d.require(child.poll() is None, 'qemu_start_failed')
                if pidfile.is_file() and not pidfile.is_symlink() and pidfile.read_text().strip() == str(child.pid):
                    return
                time.sleep(0.1)
            raise d.Refused('qemu_start_timeout')

    def signal_owned(self, number, pid):
        with self.lock:
            for child in self.children:
                if child.pid == pid:
                    if child.poll() is not None:
                        return 1
                    if number:
                        child.send_signal(number)
                    return 0
            return 64

    def reap(self):
        with self.lock:
            for child in self.children:
                if child.poll() is not None:
                    pidfile = self.output/'qemu.pid'
                    if pidfile.is_file() and not pidfile.is_symlink() and pidfile.read_text().strip() == str(child.pid):
                        pidfile.unlink()
                    d.require(child.stop(), 'qemu_stop_unproven')

    def stop(self):
        with self.lock:
            self.closed = True
            d.require(self.children, 'no_supervised_vm')
            failed = False
            for child in self.children:
                try:
                    if not child.stop():
                        failed = True
                except Exception:
                    failed = True
            d.require(not failed, 'qemu_stop_unproven')
            self.stopped = True
            return {'method':'owned-systemd-invocation-cgroup', 'exited_children':len(self.children),
                    'services':[child.proof() for child in self.children]}


def no_open_disk(path, deadline, output=None, *, proc_root=None):
    """Fail closed with one bounded, numeric observation; never inspect foreign FDs."""
    identity = path.stat()
    uid = os.getuid()
    counts = {'processes': 0, 'same_uid': 0, 'other_uid': 0, 'fds': 0}
    for proc in (proc_root if proc_root is not None else Path('/proc')).iterdir():
        d.require(time.monotonic() < deadline, 'descriptor_scan_timeout')
        if not proc.name.isascii() or not proc.name.isdigit():
            continue
        counts['processes'] += 1
        d.require(counts['processes'] <= 100000, 'descriptor_scan_limit')
        previous_uid = None
        stage = 'proc_stat'
        fd_number = None
        try:
            previous_uid = proc.stat().st_uid
            if previous_uid != uid:
                counts['other_uid'] += 1
                continue
            counts['same_uid'] += 1
            stage = 'fd_enumeration'
            for fd in (proc / 'fd').iterdir():
                counts['fds'] += 1
                d.require(counts['fds'] <= 100000 and time.monotonic() < deadline, 'descriptor_scan_limit')
                d.require(fd.name.isascii() and fd.name.isdigit(), 'descriptor_entry_invalid')
                fd_number = int(fd.name)
                stage = 'fd_stat'
                try:
                    st = fd.stat()
                except FileNotFoundError:
                    stage = 'fd_enumeration'
                    fd_number = None
                    continue
                d.require((st.st_dev, st.st_ino) != (identity.st_dev, identity.st_ino), 'disk_still_open')
                stage = 'fd_enumeration'
                fd_number = None
        except FileNotFoundError:
            continue
        except PermissionError as error:
            observation = {'stage': stage, 'pid': int(proc.name), 'errno': error.errno,
                           'previous_uid': previous_uid,
                           'ownership': 'same_uid_observed' if previous_uid == uid else 'unknown',
                           'counts': counts.copy()}
            if fd_number is not None:
                observation['fd'] = fd_number
            if previous_uid == uid and output is not None:
                return retry_denied_descriptor_scan(path, deadline, output, observation,
                                                    (identity.st_dev, identity.st_ino))
            raise d.Refused('open_descriptor_scan_denied',
                            {'descriptor_denials': [observation]}) from None
class ScanObject:
    """Hold every physical ancestor and the object; never act through a relookup."""
    def __init__(self, path, *, access=os.O_RDONLY):
        self.path = Path(path).absolute()
        self.fds = []
        self.names = self.path.parts[1:]
        try:
            self.fds.append(os.open('/', os.O_RDONLY | os.O_DIRECTORY))
            for index, name in enumerate(self.names):
                flags = os.O_NOFOLLOW | os.O_NONBLOCK
                flags |= access if index == len(self.names)-1 else os.O_RDONLY | os.O_DIRECTORY
                self.fds.append(os.open(name, flags, dir_fd=self.fds[-1]))
            self.identities = self.snapshot()
            self.validate()
        except BaseException:
            self.close()
            raise

    @property
    def fd(self):
        return self.fds[-1]

    def snapshot(self):
        values = []
        for index, fd in enumerate(self.fds):
            info = os.fstat(fd)
            values.append([info.st_dev, info.st_ino, info.st_ctime_ns if index < len(self.fds)-1 else 0])
        return values

    def validate(self):
        d.require(self.snapshot() == self.identities, 'descriptor_ancestor_changed')
        for index, name in enumerate(self.names):
            info = os.stat(name, dir_fd=self.fds[index], follow_symlinks=False)
            d.require([info.st_dev, info.st_ino] == self.identities[index+1][:2]
                      and not stat.S_ISLNK(info.st_mode), 'descriptor_object_changed')
        info = os.fstat(self.fd)
        d.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'descriptor_object_type')
        return info

    def close(self):
        fds, self.fds = self.fds, []
        failed = False
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                failed = True
        d.require(not failed, 'descriptor_handle_close_failed')


def scan_open_descriptors(identity, deadline, proc_root=Path('/proc'), same_uid=None, metadata_handle=None):
    """Compare inode metadata only. Root mode enumerates all users' descriptors."""
    counts = {'processes': 0, 'fds': 0}
    try:
        if time.monotonic() >= deadline:
            return 'timeout'
        for proc in proc_root.iterdir():
            if time.monotonic() >= deadline:
                return 'timeout'
            if not proc.name.isascii() or not proc.name.isdigit():
                continue
            counts['processes'] += 1
            if counts['processes'] > 100000:
                return 'limit'
            try:
                if same_uid is not None and proc.stat().st_uid != same_uid:
                    continue
                for fd in (proc / 'fd').iterdir():
                    if metadata_handle == (int(proc.name), int(fd.name)):
                        continue
                    counts['fds'] += 1
                    if counts['fds'] > 100000:
                        return 'limit'
                    if time.monotonic() >= deadline:
                        return 'timeout'
                    try:
                        opened = fd.stat()
                    except FileNotFoundError:
                        continue
                    if (opened.st_dev, opened.st_ino) == tuple(identity):
                        return 'open'
            except FileNotFoundError:
                continue
            except PermissionError:
                return 'denied'
    except (FileNotFoundError, PermissionError):
        return 'denied'
    return 'timeout' if time.monotonic() >= deadline else 'clear'


def root_descriptor_scan(identity_json, result, owner_uid, deadline_text, result_identity_json, metadata_handle_json):
    d.require(os.geteuid() == 0, 'descriptor_scan_not_root')
    d.require(owner_uid.isdigit() and 0 < int(owner_uid) < 2**31, 'descriptor_scan_owner')
    d.require(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', deadline_text), 'descriptor_scan_budget')
    deadline = float(deadline_text)
    d.require(0 < deadline-time.monotonic() <= 600, 'descriptor_scan_timeout')
    identity = json.loads(identity_json)
    d.require(isinstance(identity, list) and len(identity) == 2 and
              all(type(v) is int and v >= 0 for v in identity), 'descriptor_disk_identity')
    # Mode 0602 grants this non-owner writer no DAC read access. READ_SEARCH
    # does not override a combined read/write request; the helper only pwrite()s.
    target = ScanObject(result, access=os.O_WRONLY)
    try:
        d.require(target.identities == json.loads(result_identity_json), 'descriptor_result_changed')
        parent = os.fstat(target.fds[-2])
        before = target.validate()
        d.require(parent.st_uid == int(owner_uid) and stat.S_IMODE(parent.st_mode) == 0o700,
                  'descriptor_result_directory')
        d.require(before.st_uid == int(owner_uid) and before.st_size == 0 and
                  stat.S_IMODE(before.st_mode) == 0o602, 'descriptor_result_file')
        metadata_handle = json.loads(metadata_handle_json)
        d.require(isinstance(metadata_handle, list) and len(metadata_handle) == 2 and
                  all(type(v) is int and v >= 0 for v in metadata_handle), 'descriptor_metadata_handle')
        status = scan_open_descriptors(identity, deadline, metadata_handle=tuple(metadata_handle))
        target.validate()
        # No truncate: only the validated, held original result receives bytes.
        data = (status + chr(10)).encode('ascii')
        d.require(os.pwrite(target.fd, data, 0) == len(data), 'descriptor_result_write')
        target.validate()
    finally:
        target.close()
    return 0


def retry_denied_descriptor_scan(path, deadline, output, observation, identity):
    evidence = {'descriptor_denials': [observation],
                'descriptor_fallback': {'outcome': 'setup_failed', 'cleanup': 'not_started'}}
    outcome = evidence['descriptor_fallback']
    disk = target = None
    service_count = len(OWNED_SERVICES)
    try:
        d.require(deadline-time.monotonic() > 36, 'descriptor_scan_timeout')
        output_stat = output.stat()
        d.require(stat.S_ISDIR(output_stat.st_mode) and output_stat.st_uid == os.getuid() and
                  stat.S_IMODE(output_stat.st_mode) == 0o700, 'descriptor_output_private')
        # Open the disk first to reject symlinked ancestors before result creation.
        disk = ScanObject(path, access=os.O_PATH)
        d.require(disk.identities[-1][:2] == list(identity), 'descriptor_disk_changed')
        result = output / 'descriptor-scan.result'
        d.require(output == path.parent, 'descriptor_output_mismatch')
        fd = os.open(result.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o602, dir_fd=disk.fds[-2])
        try:
            os.fchmod(fd, 0o602)
            created = os.fstat(fd)
            target = ScanObject(result, access=os.O_RDWR)
            d.require(target.identities[-1][:2] == [created.st_dev, created.st_ino],
                      'descriptor_result_changed')
        finally:
            os.close(fd)
        # Creation changes the parent ctime. Start the immutable chain snapshot now.
        disk.identities = disk.snapshot()
        disk.validate()
        remaining = deadline-time.monotonic()
        d.require(36 < remaining <= 600, 'descriptor_scan_timeout')
        outcome['outcome'] = 'start_failed'
        service = ContainedProcess(
            [sys.executable, str(Path(__file__).resolve()), 'scan-open-disk',
             json.dumps(list(identity)), str(result), str(os.getuid()), str(deadline),
             json.dumps(target.identities), json.dumps([os.getpid(), disk.fd])],
            memory_max=256 * 1024**2, service_user=0, runtime_max_sec=int(remaining),
            read_write_paths=(result,), capability_bounding_set=('CAP_DAC_READ_SEARCH', 'CAP_SYS_PTRACE'),
            protect_system='strict', private_network=True)
        outcome['outcome'] = 'wait_failed'
        remaining = deadline-time.monotonic()
        d.require(remaining > 0, 'descriptor_scan_timeout')
        try:
            code = service.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise d.Refused('descriptor_scan_timeout') from None
        d.require(time.monotonic() < deadline, 'descriptor_scan_timeout')
        outcome['outcome'] = 'service_failed'
        d.require(type(code) is int and 0 <= code <= 255, 'descriptor_scan_status')
        outcome['service_exit_status'] = code
        d.require(code == 0, 'descriptor_scan_failed')
        disk.validate()
        target.validate()
        d.require(os.fstat(target.fd).st_size <= 16, 'descriptor_result_limit')
        status = os.pread(target.fd, 17, 0).decode('ascii').strip()
        d.require(status in ('clear', 'open', 'denied', 'timeout', 'limit'), 'descriptor_scan_status')
        outcome['outcome'] = status
        reasons = {'open':'disk_still_open', 'timeout':'descriptor_scan_timeout',
                   'limit':'descriptor_scan_limit', 'denied':'open_descriptor_scan_denied'}
        if status != 'clear':
            raise d.Refused(reasons[status])
    except Exception as error:
        if outcome['outcome'] not in ('clear', 'open', 'timeout', 'limit', 'denied'):
            outcome['outcome'] = 'timeout' if isinstance(error, d.Refused) and str(error) == 'descriptor_scan_timeout' else outcome['outcome']
        reason = str(error) if isinstance(error, d.Refused) else 'descriptor_fallback_failed'
        raise d.Refused(reason, evidence) from None
    finally:
        # Cleanup has its own bounded service-stop grace; never grants scan time.
        stopped = True
        for item in OWNED_SERVICES[service_count:]:
            try:
                stopped = item.stop() and stopped
            except Exception:
                stopped = False
        outcome['cleanup'] = 'stopped_result_retained' if stopped else 'stop_failed_result_retained'
        # Retain the token even on success. Pathname unlink cannot atomically check
        # inode identity; a concurrent replacement must never be removed.
        final_refusal = None
        if outcome['outcome'] == 'clear' and stopped:
            try:
                disk.validate()
                target.validate()
                d.require(time.monotonic() < deadline, 'descriptor_scan_timeout')
            except Exception as error:
                final_refusal = str(error) if isinstance(error, d.Refused) else 'descriptor_object_changed'
        close_failed = False
        for held in (target, disk):
            if held is not None:
                try:
                    held.close()
                except Exception:
                    close_failed = True
        if close_failed:
            outcome['handles'] = 'close_failed'
        if not stopped:
            raise d.Refused('descriptor_scan_stop_unproven', evidence) from None
        if close_failed:
            raise d.Refused('descriptor_handle_close_failed', evidence) from None
        if final_refusal:
            outcome['post_cleanup'] = final_refusal
            raise d.Refused(final_refusal, evidence) from None
    return evidence

def worker(disk, target, version):
    # Separate process deadline bounds libguestfs calls and parsing as a whole.
    import guestfs
    g = guestfs.GuestFS(python_return_dict=True)
    try:
        v = g.version()
        actual = '.'.join(str(v[k]) for k in ('major', 'minor', 'release'))
        d.require(actual == version, 'guestfs_version_mismatch')
        g.set_backend('direct')
        g.set_network(False)
        g.set_memsize(1024)
        g.set_smp(2)
        g.add_drive_opts(str(disk), readonly=True, format='qcow2')
        g.launch()
        # Bound parsing after QEMU has allocated its guest memory.
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        result = d.inspect_boot(g)
        raw = json.dumps(result).encode()
        d.require(len(raw) <= d.MAX_REPORT, 'report_limit')
        target.write_bytes(raw)
    except d.Refused as error:
        target.write_text(json.dumps({'inspection_refusal':str(error), **error.details}))
        raise
    finally:
        g.close()


def proxy():
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(40)
        client.connect(os.environ['TUNAOS_DIAGNOSTIC_SOCKET'])
        request = sys.argv[2:]
        if sys.argv[1] == 'signal':
            request = {'signal': int(sys.argv[2]), 'pid': int(sys.argv[3])}
        client.sendall(json.dumps(request).encode() + b'\n')
        reply = client.recv(128)
        if reply in (b'0\n', b'1\n', b'64\n'):
            return int(reply)
        return 0 if reply == b'ok\n' else 77


def read_json(path):
    d.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= d.MIB, 'input_limit')
    return json.loads(path.read_bytes())


def validate_run(p, environment):
    d.require(environment.get('GITHUB_REPOSITORY') == p['repository'], 'run_repository')
    d.require(environment.get('GITHUB_RUN_ID') == str(p['run']) and
              environment.get('GITHUB_RUN_ATTEMPT') == str(p['attempt']), 'current_run_mismatch')


class ContainedProcess:
    """Non-delegated transient service; retain it until explicit stop."""
    properties = ('InvocationID','ControlGroup','User','Delegate','KillMode','RemainAfterExit',
                  'Restart','ActiveState','SubState','MainPID','ExecMainCode','ExecMainStatus','LoadState',
                  'SupplementaryGroups','NoNewPrivileges','RuntimeMaxUSec','ReadWritePaths',
                  'CapabilityBoundingSet','ProtectSystem','PrivateNetwork')

    def __init__(self, command, env=None, memory_max=None, supplementary_groups=(),
                 service_user=None, runtime_max_sec=3700, read_write_paths=(),
                 capability_bounding_set=(), protect_system=None, private_network=False):
        self.unit = 'tunaos-diag-' + uuid.uuid4().hex + '.service'
        self.invocation = None
        self.cgroup = None
        self.returncode = None
        self.stopped = False
        self.stop_attempted = False
        self.memory_max = memory_max
        self.supplementary_groups = tuple(supplementary_groups)
        self.service_user = os.getuid() if service_user is None else service_user
        self.runtime_max_sec = runtime_max_sec
        self.read_write_paths = tuple(Path(path).absolute() for path in read_write_paths)
        self.capability_bounding_set = tuple(capability_bounding_set)
        self.protect_system = protect_system
        self.private_network = private_network
        d.require(type(self.service_user) is int and self.service_user >= 0 and
                  type(runtime_max_sec) is int and 1 <= runtime_max_sec <= 3700, 'service_limits')
        if self.service_user == 0:
            d.require(self.read_write_paths and self.capability_bounding_set ==
                      ('CAP_DAC_READ_SEARCH', 'CAP_SYS_PTRACE') and protect_system == 'strict'
                      and private_network and not self.supplementary_groups, 'root_service_policy')
            d.require(all(path.is_absolute() and not any(parent.is_symlink()
                      for parent in (path, *path.parents)) for path in self.read_write_paths),
                      'root_service_write_path')
        else:
            d.require(self.service_user == os.getuid() and not self.read_write_paths and
                      not self.capability_bounding_set and protect_system is None and
                      not private_network, 'service_user_policy')
        OWNED_SERVICES.append(self)
        settings = [f'--setenv={key}={value}' for key,value in (env or {}).items()]
        memory_setting = ['--property=MemoryMax='+str(memory_max)] if memory_max is not None else []
        group_setting = ['--property=SupplementaryGroups='+','.join(self.supplementary_groups)] if self.supplementary_groups else []
        root_settings = []
        if self.read_write_paths:
            root_settings.append('--property=ReadWritePaths='+' '.join(map(str, self.read_write_paths)))
        if self.capability_bounding_set:
            root_settings.append('--property=CapabilityBoundingSet='+' '.join(self.capability_bounding_set))
        if self.protect_system:
            root_settings.append('--property=ProtectSystem='+self.protect_system)
        if self.private_network:
            root_settings.append('--property=PrivateNetwork=yes')
        command = ['sudo','-n','systemd-run','--quiet','--remain-after-exit',
            '--service-type=exec','--unit='+self.unit,'--property=User='+str(self.service_user),
            '--property=NoNewPrivileges=yes','--property=Delegate=no','--property=Restart=no',
            '--property=KillMode=control-group','--property=TimeoutStopSec=20',
            '--property=RuntimeMaxSec='+str(runtime_max_sec),'--property=StandardOutput=null',
            '--property=StandardError=null',*memory_setting,*group_setting,*root_settings,
            '--working-directory='+str(ROOT),'--expand-environment=no',*settings,'--',*command]
        try:
            result = subprocess.run(command,capture_output=True,timeout=35,check=False)
            d.require(result.returncode == 0, 'service_start_failed')
            info = self.info(check_identity=False)
            d.require(info.get('User') == str(self.service_user) and info.get('NoNewPrivileges') == 'yes'
                      and info.get('Delegate') == 'no' and info.get('KillMode') == 'control-group'
                      and info.get('Restart') == 'no' and info.get('RemainAfterExit') == 'yes'
                      and set(info.get('SupplementaryGroups','').split()) == set(self.supplementary_groups)
                      and systemd_usec(info.get('RuntimeMaxUSec','')) == runtime_max_sec * 1000000,
                      'service_policy')
            if self.service_user == 0:
                d.require(set(info.get('ReadWritePaths','').split()) == set(map(str, self.read_write_paths))
                          and set(info.get('CapabilityBoundingSet','').upper().split()) ==
                          set(self.capability_bounding_set) and info.get('ProtectSystem') == 'strict'
                          and info.get('PrivateNetwork') == 'yes', 'root_service_sandbox')
            d.require(len(info.get('InvocationID','')) == 32 and
                      all(c in '0123456789abcdef' for c in info['InvocationID']), 'service_invocation')
            path = info.get('ControlGroup','')
            d.require(path == '/system.slice/'+self.unit, 'service_cgroup')
            self.invocation = info['InvocationID']
            self.cgroup = Path('/sys/fs/cgroup')/path.lstrip('/')
            d.require((self.cgroup/'cgroup.events').is_file(), 'cgroup_v2_required')
            if memory_max is not None:
                d.require((self.cgroup/'memory.max').read_text().strip() == str(memory_max)
                          and (self.cgroup/'memory.events').is_file(), 'service_memory_limit')
            self.pid = int(info['MainPID'])
        except BaseException:
            self.stop()
            raise

    def info(self, check_identity=True):
        result = subprocess.run(['systemctl','show',self.unit,'--property='+','.join(self.properties)],
                                capture_output=True,timeout=10,check=False)
        d.require(result.returncode == 0 and len(result.stdout) <= 16384, 'service_query')
        info = dict(line.split('=',1) for line in result.stdout.decode('ascii').splitlines() if '=' in line)
        if check_identity:
            d.require(info.get('InvocationID') == self.invocation, 'service_identity_changed')
        return info

    def require_memory_ok(self):
        if self.memory_max is None:
            return
        events_path = self.cgroup/'memory.events'
        d.require(events_path.is_file(), 'service_memory_events')
        data = events_path.read_text()
        d.require(len(data) <= 4096, 'service_memory_events')
        events = {}
        for line in data.splitlines():
            fields = line.split()
            d.require(len(fields) == 2 and fields[1].isdigit() and fields[0] not in events,
                      'service_memory_events')
            events[fields[0]] = int(fields[1])
        d.require(all(key in events for key in ('oom', 'oom_kill', 'oom_group_kill')),
                  'service_memory_events')
        if any(events[key] for key in ('oom', 'oom_kill', 'oom_group_kill')):
            d.require(self.stop(), 'inspector_stop_unproven')
            raise d.Refused('inspector_memory_limit')

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        info = self.info()
        code, status = int(info['ExecMainCode']), int(info['ExecMainStatus'])
        if code:
            self.returncode = status if code == 1 else 128+status
        return self.returncode

    def wait(self, timeout=None):
        deadline = time.monotonic()+timeout if timeout is not None else float('inf')
        while self.poll() is None:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('owned-service',timeout)
            time.sleep(0.2)
        return self.returncode

    def send_signal(self, number):
        self.info()  # Verify invocation; service names are never reused here.
        result = subprocess.run(['sudo','-n','systemctl','kill','--kill-whom=main',
                                 '--signal='+str(number),self.unit],capture_output=True,timeout=10,check=False)
        d.require(result.returncode == 0, 'service_signal_failed')

    def proof(self):
        return {'invocation':self.invocation, 'cgroup':str(self.cgroup),
                'user':self.service_user, 'delegated':False, 'stopped':self.stopped}

    def stop(self):
        if self.stopped:
            return True
        if self.stop_attempted:
            return False
        self.stop_attempted = True
        try:
            if self.invocation is None:
                # Uncertain startup still owns this random name, but without
                # its captured invocation we cannot certify closure.
                subprocess.run(['sudo','-n','systemctl','stop',self.unit],capture_output=True,timeout=30,check=False)
                return False
            self.info()
            result = subprocess.run(['sudo','-n','systemctl','stop',self.unit],capture_output=True,timeout=30,check=False)
            info = self.info(check_identity=False)
            if result.returncode != 0 or info.get('ActiveState') not in ('inactive','failed'):
                return False
            # The manager may unload the unit only after explicit stop. The
            # cgroup path below was captured from its verified live invocation.
            if info.get('LoadState') != 'not-found' and info.get('InvocationID') not in (self.invocation,''):
                return False
            if self.cgroup.exists() and 'populated 0' not in (self.cgroup/'cgroup.events').read_text().splitlines():
                return False
            self.stopped = True
            return True
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False


def group_empty(pid):
    # A reaped leader alone does not prove that its helpers exited. Probe only:
    # never signal a group after its owned leader has been reaped (ID reuse).
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def stop_group(process):
    if isinstance(process, ContainedProcess):
        return process.stop()
    if process is None:
        return True
    try:
        if process.poll() is not None:
            return group_empty(process.pid)
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
        return group_empty(process.pid)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def final_status(primary, collected):
    return primary if primary else (0 if collected else 1)


def inspect_stopped_disk(disk, output, deadline, lock, env, report):
    before = d.regular(disk, output)
    d.require(before[2] <= 65*1024**3, 'disk_file_limit')
    d.qcow_header(disk)
    report.update(no_open_disk(disk, deadline, output) or {})
    d.require(time.monotonic() < deadline, 'descriptor_scan_timeout')
    d.require(before == d.regular(disk, output), 'disk_changed')
    disk_hash = file_digest(disk, deadline)
    d.require(time.monotonic() < deadline, 'inspection_timeout')
    target = output / 'private-inspection.json'
    process = ContainedProcess([sys.executable, str(Path(__file__).resolve()), 'inspect',
                                str(disk), str(target), lock['guestfs_version']],
                               env={k:v for k,v in env.items() if k in ('PATH','HOME','LANG')},
                               memory_max=4*1024**3, supplementary_groups=('kvm',))
    try:
        code = process.wait(timeout=max(1, deadline-time.monotonic()))
    except subprocess.TimeoutExpired:
        d.require(process.stop(), 'inspector_stop_unproven')
        raise d.Refused('inspection_timeout') from None
    process.require_memory_ok()
    d.require(stop_group(process), 'inspector_group_stop_unproven')
    if code != 0 and target.is_file() and target.stat().st_size <= d.MAX_REPORT:
        inspection = json.loads(target.read_bytes())
        refusal = inspection.get('inspection_refusal')
        if isinstance(inspection.get('partitions'), list) and len(inspection['partitions']) <= 32:
            report['layout_partitions'] = inspection['partitions']
        if isinstance(refusal, str) and refusal.replace('_','').isalnum():
            raise d.Refused(refusal)
    d.require(code == 0 and target.is_file() and target.stat().st_size <= d.MAX_REPORT, 'inspection_failed')
    d.require(before == d.regular(disk, output) and disk_hash == file_digest(disk, deadline), 'disk_changed')
    report.update(collection='collected', disk_sha256=disk_hash, disk_bytes=before[2],
                  metadata=json.loads(target.read_bytes()))
    target.unlink()


def run(args):
    p = d.provenance(read_json(args.provenance))
    validate_run(p, os.environ)
    d.require(args.binding.stat().st_size <= d.MIB, 'binding_limit')
    binding = read_json(args.binding)
    for key, other in (('producer_sha', 'producer_sha'), ('producer_run', 'producer_run'),
                       ('producer_attempt', 'producer_attempt'), ('artifact_id', 'artifact_id'),
                       ('archive', 'archive_digest'), ('media', 'media_digest')):
        d.require(p[key] == binding.get(other), 'artifact_binding_mismatch')
    d.require(binding.get('media_filename') == args.iso.name and
              args.iso.name.startswith('skipjack-gnome-') and args.iso.name.endswith('.iso'), 'target_media_name')
    d.require(binding.get('repository') == p['repository'] and
              binding.get('status') == 'download_verified_not_boot_tested' and
              binding.get('producer_workflow') == '.github/workflows/live-iso-bootc.yml' and
              binding.get('producer_status') in ('in_progress','completed') and
              binding.get('producer_build_conclusion') == 'success' and
              p['producer_run'] == p['run'] and p['producer_attempt'] == p['attempt'] and
              p['producer_sha'] == p['collector_sha'], 'artifact_not_verified')
    d.regular(args.iso, args.iso.parent)
    d.require(args.iso.stat().st_size <= 12 * 1024**3 and file_digest(args.iso, time.monotonic()+300) == p['media'], 'media_digest_mismatch')
    # Exact approved tool bytes are supplied by a reviewed lock, never discovered
    # from PATH. Dependency acquisition belongs to the reviewed CI setup.
    lock = read_json(args.tool_lock)
    d.require(set(lock) == {'qemu', 'guestfs_version'} and set(lock['qemu']) == {'path', 'sha256', 'version'}, 'tool_lock_schema')
    qemu = Path(lock['qemu']['path'])
    d.require(qemu.is_absolute() and qemu.is_file() and not qemu.is_symlink(), 'qemu_path')
    d.require(file_digest(qemu) == lock['qemu']['sha256'], 'qemu_identity')
    qemu_version = subprocess.check_output([str(qemu), '--version'], text=True, timeout=10).splitlines()[0]
    d.require(qemu_version == lock['qemu']['version'] and len(qemu_version) <= 256, 'qemu_version_mismatch')
    d.require(lock['guestfs_version'] == '1.52.0', 'guestfs_pin')
    actual_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    d.require(actual_sha == p['collector_sha'], 'collector_source_mismatch')
    d.require(not subprocess.check_output(['git', 'status', '--porcelain', '--', '.', ':!native-iso-input'], cwd=ROOT), 'dirty_source')
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    output = args.output.resolve()
    owner = OwnedQemu(str(qemu), output)
    endpoint = output / 'qemu-supervisor.sock'

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                self.connection.settimeout(40)
                raw = self.rfile.readline(32769)
                d.require(len(raw) <= 32768, 'request_limit')
                command = json.loads(raw)
                if isinstance(command, dict):
                    d.require(set(command) == {'signal','pid'} and type(command['pid']) is int and command['pid'] > 0
                              and command['signal'] in (0,9,15), 'signal_request')
                    self.wfile.write(f"{owner.signal_owned(command['signal'],command['pid'])}\n".encode())
                    return
                d.require(isinstance(command, list) and all(isinstance(a, str) for a in command), 'request_type')
                owner.launch(command)
                self.wfile.write(b'ok\n')
            except Exception:
                self.wfile.write(b'refused\n')

    server = socketserver.UnixStreamServer(str(endpoint), Handler)
    os.chmod(endpoint, 0o600)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    wrapper = output / 'qemu-proxy'
    # Arguments/paths are passed through exec, never interpolated into shell code.
    wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\nos.execv(' +
                       repr(sys.executable) + ', [' + repr(sys.executable) + ',' +
                       repr(str(Path(__file__).resolve())) + ',"proxy",*sys.argv[1:]])\n')
    wrapper.chmod(0o700)
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'LANG')}
    env.update(QEMU=str(wrapper), TUNAOS_DIAGNOSTIC_SOCKET=str(endpoint),
               TUNAOS_INSTALLED_BOOT_DIAGNOSTIC='1', TBOX_E2E_GPU='plain',
               TUNAOS_QUAL_EXECUTION_KIND='native-qemu', STRICT_PUBLISHED_MEDIA='1',
               VARIANT='skipjack', FLAVOR='gnome', TUNAOS_QUAL_PLATFORM='linux/amd64')
    for key in ('source', 'overlay', 'installer', 'engine', 'media'):
        env['TUNAOS_QUAL_' + key.upper() + '_DIGEST'] = p[key]
    report = {'schema': 'InstalledBootDiagnostic/v1', 'fresh_install': True,
              'label': 'fresh reproduction, not the disk from run 40093907774',
              'reference_run': 40093907774,
              'qualified': False, 'provenance': p, 'collection': 'not_collected',
              'input_digest_status': 'verified_media_inputs_not_installed_identity',
              'expected_target': {'variant':'skipjack','flavor':'gnome','platform':'linux/amd64'},
              'tools': {'qemu_sha256':lock['qemu']['sha256'], 'qemu_version':qemu_version,
                        'guestfs_version':lock['guestfs_version'], 'zstandard_version':'0.25.0'},
              'gpu_policy':'plain', 'runtime_initialization':'not_observed'}
    rc = 77
    harness = None
    process = None
    try:
        harness = ContainedProcess(['bash', str(ROOT / 'scripts/iso-e2e.sh'), str(args.iso.resolve()),
                                    '--strict-offline-gui=luks', '--output', str(output),
                                    '--timeout', '600', '--memory', '4096', '--cpus', '4'],
                                   env=env, supplementary_groups=('kvm',))
        try:
            until = time.monotonic()+2700
            while harness.poll() is None:
                owner.reap()
                if time.monotonic() >= until:
                    raise subprocess.TimeoutExpired('harness',2700)
                time.sleep(1)
            rc = harness.returncode
        except subprocess.TimeoutExpired:
            rc = 124
            d.require(harness.stop(), 'harness_stop_unproven')
        server.shutdown()
        server.server_close()
        thread.join(timeout=45)
        report['stop'] = owner.stop()
        d.require(stop_group(harness), 'harness_group_stop_unproven')
        d.require(all(item.stopped for item in OWNED_SERVICES), 'registered_service_stop_unproven')
        disk = output / 'strict-luks-disk.qcow2'
        # Completion must be recorded by the actual installer walkthrough.
        record = output / 'walkthrough-luks/walkthrough-gnome.json'
        d.require(record.stat().st_size <= d.MIB, 'install_report_limit')
        installed = json.loads(record.read_bytes())
        d.require(all(installed.get(k) is True for k in ('submitted', 'accepted', 'completed')), 'install_not_complete')
        boot_log = output/'strict-luks-installed-serial.log'
        d.regular(boot_log, output)
        d.require(boot_log.stat().st_size <= d.MIB, 'observer_log_limit')
        observed = boot_log.read_text(errors='replace')
        report['cold_boot_observation'] = ('prompt_seen_no_unlock' if 'DIAGNOSTIC_PROMPT_OBSERVED_NO_UNLOCK' in observed
            else 'emergency_seen_no_commands' if 'DIAGNOSTIC_EMERGENCY_OBSERVED' in observed
            else 'prompt_not_observed')
        deadline = time.monotonic()+600
        inspect_stopped_disk(disk, output, deadline, lock, env, report)
    except Exception as error:
        report['reason'] = str(error) if isinstance(error, d.Refused) else 'diagnostic_internal_failure'
        if isinstance(error, d.Refused):
            for key in ('descriptor_denials', 'descriptor_fallback'):
                if key in error.details:
                    report[key] = error.details[key]
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        groups_stopped = stop_group(process)
        groups_stopped = stop_group(harness) and groups_stopped
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            groups_stopped = False
        try:
            if not owner.stopped:
                owner.stop()
        except Exception:
            groups_stopped = False
        for item in OWNED_SERVICES:
            groups_stopped = item.stop() and groups_stopped
        if not groups_stopped:
            report['collection'] = 'not_collected'
            report['reason'] = 'stop_unproven'
            report.pop('metadata', None)
        report['helper_services'] = [item.proof() for item in OWNED_SERVICES]
        report['strict_exit'] = rc
        try:
            d.write_report(output / 'installed-boot-diagnostic', report)
        except (OSError, ValueError):
            report['collection'] = 'not_collected'
            print('diagnostic report write failed', file=sys.stderr)
    return final_status(rc, report['collection'] == 'collected')


def interrupted(signum, frame):
    raise InterruptedError('diagnostic_interrupted')


def main():
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if len(sys.argv) > 1 and sys.argv[1] == 'probe-descriptor-scan':
        signal.signal(signal.SIGTERM, lambda *args: sys.exit(124))
        signal.signal(signal.SIGINT, lambda *args: sys.exit(124))
        parser = argparse.ArgumentParser(description='Disposable root-scan readiness; never qualification')
        parser.add_argument('--output', type=Path, required=True)
        return probe_descriptor_scan(parser.parse_args(sys.argv[2:]).output)
    if len(sys.argv) > 1 and sys.argv[1] == 'scan-open-disk':
        try:
            d.require(len(sys.argv) == 8, 'descriptor_scan_arguments')
            return root_descriptor_scan(*sys.argv[2:])
        except d.Refused as error:
            return ROOT_SCAN_REFUSALS.get(str(error), 77)
        except PermissionError:
            return ROOT_SCAN_REFUSALS['permission_denied']
        except FileNotFoundError:
            return ROOT_SCAN_REFUSALS['file_not_found']
        except OSError:
            return ROOT_SCAN_REFUSALS['os_error']
        except (ValueError, TypeError):
            return ROOT_SCAN_REFUSALS['invalid_argument']
    if len(sys.argv) > 1 and sys.argv[1] in ('proxy', 'signal'):
        return proxy()
    if len(sys.argv) > 1 and sys.argv[1] == 'inspect':
        worker(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('iso', 'binding', 'provenance', 'tool-lock', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    return run(parser.parse_args())


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('diagnostic preflight refused; no qualification', file=sys.stderr)
        raise SystemExit(77)
