#!/usr/bin/env python3
"""Opt-in fresh-install diagnostic supervisor. Never native qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def no_open_disk(path, deadline, *, proc_root=None):
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
            raise d.Refused('open_descriptor_scan_denied',
                            {'descriptor_denials': [observation]}) from None


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
                  'SupplementaryGroups')

    def __init__(self, command, env=None, memory_max=None, supplementary_groups=()):
        self.unit = 'tunaos-diag-' + uuid.uuid4().hex + '.service'
        self.invocation = None
        self.cgroup = None
        self.returncode = None
        self.stopped = False
        self.stop_attempted = False
        self.memory_max = memory_max
        self.supplementary_groups = tuple(supplementary_groups)
        OWNED_SERVICES.append(self)
        settings = [f'--setenv={key}={value}' for key,value in (env or {}).items()]
        memory_setting = ['--property=MemoryMax='+str(memory_max)] if memory_max is not None else []
        group_setting = ['--property=SupplementaryGroups='+','.join(self.supplementary_groups)] if self.supplementary_groups else []
        command = ['sudo','-n','systemd-run','--quiet','--remain-after-exit',
            '--service-type=exec','--unit='+self.unit,'--property=User='+str(os.getuid()),
            '--property=NoNewPrivileges=yes','--property=Delegate=no','--property=Restart=no',
            '--property=KillMode=control-group','--property=TimeoutStopSec=20',
            '--property=RuntimeMaxSec=3700','--property=StandardOutput=null','--property=StandardError=null',
            *memory_setting,*group_setting,'--working-directory='+str(ROOT),'--expand-environment=no',*settings,'--',*command]
        try:
            result = subprocess.run(command,capture_output=True,timeout=35,check=False)
            d.require(result.returncode == 0, 'service_start_failed')
            info = self.info(check_identity=False)
            d.require(info.get('User') == str(os.getuid()) and info.get('Delegate') == 'no'
                      and info.get('KillMode') == 'control-group' and info.get('Restart') == 'no'
                      and info.get('RemainAfterExit') == 'yes'
                      and set(info.get('SupplementaryGroups','').split()) == set(self.supplementary_groups),
                      'service_policy')
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
                'user':os.getuid(), 'delegated':False, 'stopped':self.stopped}

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
        before = d.regular(disk, output)
        d.require(before[2] <= 65*1024**3, 'disk_file_limit')
        d.qcow_header(disk)
        no_open_disk(disk, deadline)
        disk_hash = file_digest(disk, deadline)
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
    except Exception as error:
        report['reason'] = str(error) if isinstance(error, d.Refused) else 'diagnostic_internal_failure'
        if isinstance(error, d.Refused) and str(error) == 'open_descriptor_scan_denied':
            report['descriptor_denials'] = error.details['descriptor_denials']
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
