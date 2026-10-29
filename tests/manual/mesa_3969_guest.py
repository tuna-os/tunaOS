#!/usr/bin/env python3
"""Source-only authored Mesa #3969 lab; runtime entry requires live admission.

The pinned gate owns VM creation, keyboard transitions and deletion. This module
adds a pre-display probe and read-only renderer attribution, never a repair.

Tuna beta1's vendored Smithay has a genuine current-context GL Renderer log,
but its info! argument is lazy and the release installs no demonstrated sink.
The conditional consumer below cannot enable that query. Missing raw entries
remain missing evidence; native producer compatibility is unexercised and held.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time

from mesa_3969 import (
    INPUTS,
    LabError,
    normalize_image_id,
    read_json,
    sanitize_text,
    sha256_file,
    write_json,
)

LIBEXEC = Path('/usr/local/libexec/mesa-3969')
PROBE = LIBEXEC / 'repro-egldevice-swrast'
POLICY = Path('/usr/lib/systemd/user-environment-generators/60-tunaos-software-gl')
CASES = ('clean', 'software', 'override', 'combined')
RENDER_ENV = (
    'LIBGL_', 'MESA_', 'GALLIUM_', 'EGL_', '__EGL_', '__GLX_', 'GBM_',
    'MUTTER_', 'COGL_', 'CLUTTER_', 'LD_',
)
SESSION_ENV = {'GNOME_SHELL_SESSION_MODE', 'XDG_SESSION_TYPE', 'WAYLAND_DISPLAY', 'DISPLAY'}
JOURNAL_FIELDS = ('_BOOT_ID', '_PID', '_UID', '_EXE', '__MONOTONIC_TIMESTAMP', '__CURSOR', 'MESSAGE')
MAX_CAPTURE = 2 * 1024 * 1024
CHILDREN: set[subprocess.Popen] = set()
PROCESS_CLEANUP_ERRORS: list[str] = []


def live_process_group(pgid: int) -> bool:
    # A reaped leader is not a liveness oracle for its session's descendants.
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = path.read_text().rsplit(') ', 1)[1].split()
            if int(fields[2]) == pgid and fields[0] not in ('Z', 'X'):
                return True
        except (FileNotFoundError, ProcessLookupError):
            continue
    return False


def stop_process(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 5
    while live_process_group(process.pid) and time.monotonic() < deadline:
        process.poll()  # Reap the direct child without forgetting the group.
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)
    deadline = time.monotonic() + 1
    while live_process_group(process.pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    if live_process_group(process.pid):
        raise LabError('owned process group survived bounded termination')


def cancel(signum, _frame) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    for process in tuple(CHILDREN):
        try:
            stop_process(process)
        except (OSError, LabError, subprocess.SubprocessError) as error:
            PROCESS_CLEANUP_ERRORS.append(sanitize_text(str(error))[:2048])
            print(f'process cleanup failed: {sanitize_text(str(error))}', file=sys.stderr)
        finally:
            CHILDREN.discard(process)
    raise SystemExit(128 + signum)


def bounded_command(argv, *, timeout=30, limit=MAX_CAPTURE, env=None, check=True):
    """Bound time AND bytes, including descendants retaining stdout pipes."""
    process = subprocess.Popen(
        [str(part) for part in argv], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        start_new_session=True,
    )
    CHILDREN.add(process)
    buffers = [bytearray(), bytearray()]
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    try:
        for index, stream in enumerate((process.stdout, process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, index)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LabError(f'command timeout: {argv[0]}')
            for key, _ in selector.select(min(remaining, 0.25)):
                data = os.read(key.fileobj.fileno(), 16384)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                buffers[key.data].extend(data)
                if sum(map(len, buffers)) > limit:
                    raise LabError(f'command output exceeds bound: {argv[0]}')
        rc = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        stdout, stderr = (bytes(value).decode('utf-8', 'replace') for value in buffers)
        if check and rc:
            raise LabError(f'command failed ({rc}): {argv[0]}: {sanitize_text(stderr[-2048:])}')
        return rc, stdout, stderr
    finally:
        active_error = sys.exc_info()[1]
        try:
            stop_process(process)
        except (OSError, LabError, subprocess.SubprocessError) as error:
            PROCESS_CLEANUP_ERRORS.append(sanitize_text(str(error))[:2048])
            if active_error is None:
                raise
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
            CHILDREN.discard(process)


def boot_id() -> str:
    value = Path('/proc/sys/kernel/random/boot_id').read_text().strip().replace('-', '')
    if not re.fullmatch('[0-9a-f]{32}', value):
        raise LabError('invalid kernel boot identity')
    return value


def virtio_device() -> tuple[str | None, list[dict]]:
    devices = []
    selected = []
    for node in sorted(Path('/dev/dri').glob('card[0-9]*')):
        if not re.fullmatch(r'card[0-9]+', node.name) or not stat.S_ISCHR(node.stat().st_mode):
            continue
        device = Path('/sys/class/drm') / node.name / 'device'
        driver = (device / 'driver').resolve().name
        vendor = (device / 'vendor').read_text().strip() if (device / 'vendor').exists() else ''
        pci_id = (device / 'device').read_text().strip() if (device / 'device').exists() else ''
        devices.append({'node': str(node), 'driver': driver, 'vendor': vendor, 'device': pci_id})
        if driver == 'virtio_gpu' or (driver == 'virtio-pci' and vendor == '0x1af4' and pci_id == '0x1050'):
            selected.append(str(node))
    if len(selected) > 1:
        raise LabError('ambiguous virtio primary DRM nodes')
    return (selected[0] if selected else None), devices


def collect_probe(binary=PROBE) -> dict:
    result = {'schema_version': 1, 'boot_id': boot_id(), 'cases': [], 'status': 'failed'}
    # A oneshot runs before GDM; never stop/restart display-manager here.
    _, active, _ = bounded_command(
        ['systemctl', 'is-active', 'display-manager.service'], timeout=2, check=False,
    )
    if active.strip() in ('active', 'activating', 'reloading'):
        raise LabError('display manager already running; pre-display probe refused')
    result['binary_sha256'] = sha256_file(binary)
    device, devices = virtio_device()
    result.update(device=device, devices=devices)
    if device is None:
        result.update(status='not-run', reason='no-virtio-gpu-primary-node')
        return result
    for case in CASES:
        environment = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
        if case in ('software', 'combined'):
            environment['LIBGL_ALWAYS_SOFTWARE'] = '1'
        if case in ('override', 'combined'):
            environment['MESA_LOADER_DRIVER_OVERRIDE'] = 'swrast'
        started = time.monotonic_ns() // 1000
        try:
            rc, stdout, stderr = bounded_command(
                ['timeout', '--kill-after=5', '20', binary, device],
                timeout=26, limit=64 * 1024, env=environment, check=False,
            )
            normalized = 128 - rc if rc < 0 else rc
            status = ('initialized' if normalized == 0 and 'eglInitialize=success ' in stdout
                      else 'egldevice-unavailable' if normalized in (3, 4)
                      else 'crashed' if normalized in (132, 134, 135, 136, 139)
                      else 'timeout' if normalized in (124, 137) else 'failed')
            result['cases'].append({
                'case': case, 'exit': normalized, 'status': status,
                'started_us': started, 'ended_us': time.monotonic_ns() // 1000,
                'stdout': stdout, 'stderr': stderr,
            })
        except (OSError, LabError) as error:
            result['cases'].append({'case': case, 'exit': None, 'status': 'collection-failed', 'error': str(error)})
    result['status'] = 'collected'
    return result


def read_at(fd: int, name: str, limit=65536) -> bytes:
    with os.fdopen(os.open(name, os.O_RDONLY, dir_fd=fd), 'rb') as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise LabError(f'process {name} exceeds bound')
    return value


def process_identity(fd: int) -> dict:
    status = dict(line.split(':', 1) for line in read_at(fd, 'status').decode().splitlines() if ':' in line)
    uids = tuple(int(value) for value in status['Uid'].split())
    if len(uids) != 4 or len(set(uids)) != 1 or uids[0] <= 0:
        raise LabError('unstable or root compositor credentials')
    started = int(read_at(fd, 'stat').decode().rsplit(')', 1)[1].split()[19])
    return {
        'uid': uids[0], 'start_ticks': started,
        'comm': read_at(fd, 'comm').decode().strip(),
        'exe': os.readlink('exe', dir_fd=fd),
        'cgroups': read_at(fd, 'cgroup').decode().splitlines(),
    }


def session_records() -> list[dict]:
    _, output, _ = bounded_command(['loginctl', 'list-sessions', '--no-legend'], timeout=3)
    sessions = []
    for row in output.splitlines()[:32]:
        fields = row.split()
        if not fields or not re.fullmatch('[A-Za-z0-9_-]+', fields[0]):
            continue
        _, properties, _ = bounded_command([
            'loginctl', 'show-session', fields[0], '-p', 'Class', '-p', 'Service',
            '-p', 'Seat', '-p', 'User', '-p', 'Scope', '-p', 'Name', '-p', 'Type', '-p', 'Active',
        ], timeout=2)
        record = dict(line.split('=', 1) for line in properties.splitlines() if '=' in line)
        record['id'] = fields[0]
        sessions.append(record)
    return sessions


def process_environment(fd: int) -> dict:
    environment = {}
    for item in read_at(fd, 'environ').decode('utf-8', 'replace').split('\0'):
        key, separator, value = item.partition('=')
        if separator and (key.startswith(RENDER_ENV) or key in SESSION_ENV):
            if key in environment:
                raise LabError('duplicate compositor environment key')
            environment[key] = value
    return environment


def renderer_value(message: str) -> str | None:
    # Mutter 49.4 cogl/driver/gl/{gl3,gles2}/cogl-driver-*.c logs this
    # multiline feature report through COGL_NOTE(WINSYS), not EGL tools.
    if not re.search(r'\bWINSYS\b', message, re.IGNORECASE) or 'Checking features' not in message:
        return None
    match = re.search(r'^\s*GL_RENDERER:\s*([^\r\n]+)', message, re.MULTILINE)
    return match.group(1).strip()[:512] if match else None


def tuna_renderer_value(message: str) -> str | None:
    """Consume, never manufacture, the released Smithay diagnostic.

    d28578e's third-party/smithay/src/backend/renderer/gles/mod.rs:500-555
    makes the context current, then info!("GL Renderer: {:?}", CStr(...)).
    No subscriber/logger is established by that source: this format contract
    is conditional, not proof the shipped process can currently emit it.
    """
    if not isinstance(message, str) or len(message) > 4096:
        return None
    match = re.fullmatch(r'(?:[^\r\n]*[ \t])?GL Renderer: ("(?:[^"\\\r\n]|\\.){1,512}")\s*', message)
    if match is None:
        return None
    try:
        value = json.loads(match.group(1))
    except ValueError:
        return None
    return value if isinstance(value, str) and not any(ord(char) < 32 for char in value) else None


def drm_cards(fd: int) -> list[str]:
    directory = os.open('fd', os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)
    try:
        names = os.listdir(directory)
        if len(names) > 4096:
            raise LabError('compositor descriptor bound reached')
        return sorted({target for name in names
                       if re.fullmatch(r'/dev/dri/card[0-9]+',
                                       target := os.readlink(name, dir_fd=directory))})
    finally:
        os.close(directory)


def validate_renderer(record: dict, expected_boot: str) -> bool:
    try:
        process = record['process']
        journal = record['journal']
        session = record['session']
        environment = record['environment']
        observed = record['observed_us']
        start_us = process['start_ticks'] * 1_000_000 // record['clock_ticks']
        if (record['boot_id'] != expected_boot
                or record['identity_after'] != process
                or record['environment_after'] != environment
                or int(session['User']) != process['uid'] or session['Seat'] != 'seat0'
                or environment.get('LIBGL_ALWAYS_SOFTWARE') != '1'
                or environment.get('COGL_DEBUG') != 'winsys'):
            return False
        journal_us = int(journal['__MONOTONIC_TIMESTAMP'])
        if (journal['_BOOT_ID'] != expected_boot or journal['_PID'] != str(record['pid'])
                or journal['_UID'] != str(process['uid']) or journal['_EXE'] != process['exe']
                or not start_us <= journal_us <= observed):
            return False
        allowed = {'LIBGL_ALWAYS_SOFTWARE', 'COGL_DEBUG'}
        if any(key.startswith(RENDER_ENV) and key not in allowed for key in environment):
            return False
        groups = {part for line in process['cgroups'] for part in line.split(':', 2)[-1].split('/')}
        if record['role'] == 'greeter':
            if process['exe'] != '/usr/bin/gnome-shell' or process['comm'] != 'gnome-shell':
                return False
            if (session['Class'] != 'greeter' or session['Service'] != 'gdm-launch-environment'
                    or session['Type'] != 'wayland'
                    or environment.get('XDG_SESSION_TYPE') != 'wayland'
                    or environment.get('GNOME_SHELL_SESSION_MODE') != 'gdm'
                    or record['pid'] not in record['collector_greeter_pids']
                    or not (session['Scope'] in groups or
                            (f"user@{process['uid']}.service" in groups and
                             'org.gnome.Shell@gdm.service' in groups))):
                return False
        elif record['role'] == 'user':
            if (process['exe'] != '/usr/bin/tuna-compositor' or process['comm'] != 'tuna-compositor'
                    or record['drm_cards'] != record['drm_cards_after'] or len(record['drm_cards']) != 1
                    or not re.fullmatch(r'/dev/dri/card[0-9]+', record['drm_cards'][0])
                    or environment.get('DISPLAY') or environment.get('WAYLAND_DISPLAY')):
                return False
            if (session['Name'] != 'tuna-ci-login' or session['Type'] != 'wayland'
                    or session['Active'] != 'yes' or session['Class'] != 'user'
                    or environment.get('XDG_SESSION_TYPE') != 'wayland'
                    or environment.get('GNOME_SHELL_SESSION_MODE') == 'gdm'
                    or not (session['Scope'] in groups or f"user@{process['uid']}.service" in groups)):
                return False
        else:
            return False
        actual = (renderer_value(journal['MESSAGE']) if record['role'] == 'greeter'
                  else tuna_renderer_value(journal['MESSAGE']))
        return (actual == record['renderer'] and actual is not None
                and bool(re.match(r'^(llvmpipe|softpipe|Software Rasterizer|software rasterizer)(?:\b|\s|\()', actual)))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return False


def journal_entries(*matches, limit=256) -> list[dict]:
    _, output, _ = bounded_command([
        'journalctl', '-b', '--all', '--no-pager', '-o', 'json', '-n', str(limit), *matches,
    ], timeout=5)
    result = []
    for line in output.splitlines():
        entry = json.loads(line)
        if not isinstance(entry, dict):
            raise LabError('journal JSON is not an object')
        result.append(entry)
    if len(result) >= limit:
        raise LabError('journal event bound reached; crash absence cannot be proven')
    return result


def collect_renderers(boot: str) -> tuple[str, list[dict]]:
    _, collector, _ = bounded_command(
        ['bash', LIBEXEC / 'greeter-graphics-evidence.sh', 'once', '0'], timeout=30,
    )
    greeter_pids = [int(value) for value in re.findall(r'^--- pid ([0-9]+) comm=gnome-shell uid=[0-9]+$', collector, re.MULTILINE)]
    sessions = session_records()
    records = []
    for path in Path('/proc').glob('[0-9]*'):
        fd = None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            comm = read_at(fd, 'comm').strip()
            if comm not in (b'gnome-shell', b'tuna-compositor'):
                continue
            identity = process_identity(fd)
            environment = process_environment(fd)
            pid = int(path.name)
            for session in sessions:
                if session.get('User') != str(identity['uid']):
                    continue
                role = 'greeter' if comm == b'gnome-shell' else 'user'
                if role == 'greeter' and (pid not in greeter_pids or session.get('Class') != 'greeter'):
                    continue
                exe = '/usr/bin/gnome-shell' if role == 'greeter' else '/usr/bin/tuna-compositor'
                pattern = 'GL_RENDERER' if role == 'greeter' else 'GL Renderer:'
                journals = journal_entries(f'_PID={pid}', f'_UID={identity["uid"]}',
                                          f'_EXE={exe}', f'--grep={pattern}')
                cards = drm_cards(fd) if role == 'user' else []
                for journal in journals:
                    actual = (renderer_value(journal.get('MESSAGE', '')) if role == 'greeter'
                              else tuna_renderer_value(journal.get('MESSAGE', '')))
                    if actual is None:
                        continue
                    record = {
                        'role': role, 'pid': pid, 'boot_id': boot,
                        'process': identity, 'identity_after': process_identity(fd),
                        'environment': environment, 'session': session,
                        'environment_after': process_environment(fd),
                        'clock_ticks': os.sysconf('SC_CLK_TCK'),
                        'observed_us': time.monotonic_ns() // 1000,
                        'collector_greeter_pids': greeter_pids, 'renderer': actual,
                        'journal': {key: journal.get(key) for key in JOURNAL_FIELDS},
                        'drm_cards': cards,
                        'drm_cards_after': drm_cards(fd) if role == 'user' else [],
                    }
                    # Preserve mismatches as negative observations, never flags-as-success.
                    record['software_verified'] = validate_renderer(record, boot)
                    records.append(record)
        except (OSError, ValueError, KeyError, IndexError):
            continue
        finally:
            if fd is not None:
                os.close(fd)
    return collector, records


def collect_snapshot(identity_only=False) -> dict:
    from mesa_3969_packages import query_inventory

    # Fetch the already-completed four-case record before slower renderer
    # collection. The host retains this first observation even if control GDM
    # crashes and the pinned gate deletes its VM during the next sample.
    probe = read_json('/run/mesa-3969/probe.json')
    boot = boot_id()
    collector, records = ('', []) if identity_only else collect_renderers(boot)
    cores = journal_entries(
        'MESSAGE_ID=fc2e22bc6ee647b6b90729ab34a250b1',
        'COREDUMP_EXE=/usr/bin/gnome-shell', 'COREDUMP_EXE=/usr/bin/tuna-compositor',
        limit=128,
    )
    crashes = [{key: value.get(key) for key in (
        '_BOOT_ID', 'COREDUMP_PID', 'COREDUMP_UID', 'COREDUMP_TIMESTAMP',
        'COREDUMP_EXE', 'COREDUMP_SIGNAL', 'COREDUMP_SIGNAL_NAME',
    )} for value in cores]
    _, kernel, _ = bounded_command([
        'journalctl', '-k', '-b', '--no-pager', '-o', 'json',
        '--grep=(gnome-shell|tuna-compositor).*(segfault|trap|general protection)', '-n', '128',
    ], timeout=5)
    if len(kernel.splitlines()) >= 128:
        raise LabError('kernel crash event bound reached')
    _, enforcing, _ = bounded_command(['getenforce'], timeout=3)
    return {
        'schema_version': 1, 'boot_id': boot, 'renderer_records': records,
        'renderer_collection': 'not-requested' if identity_only else 'sampled',
        'greeter_evidence': collector, 'crashes': crashes,
        'kernel_crash': bool(kernel.strip()), 'selinux': enforcing.strip(),
        'software_policy_sha256': sha256_file(POLICY), 'inventory': query_inventory(),
        'probe': probe,
    }


def probe_verdict(probe: dict, arm: str, manifest: dict) -> dict:
    if not isinstance(probe, dict) or probe.get('binary_sha256') != manifest['probe']['binary_sha256']:
        return {'ok': False, 'reason': 'missing-or-wrong-probe'}
    if probe.get('status') != 'collected' or not probe.get('device'):
        return {'ok': False, 'reason': 'probe-not-run', 'observed': probe.get('reason')}
    cases = probe.get('cases', [])
    if [case.get('case') for case in cases] != list(CASES):
        return {'ok': False, 'reason': 'missing-or-reordered-probe-cases'}
    exits = [case.get('exit') for case in cases]
    if arm == 'control':
        return {'ok': exits == [0, 139, 139, 139] and cases[0].get('status') == 'initialized',
                'reason': 'control-reproduction', 'exits': exits}
    if cases[0].get('status') != 'initialized' or exits[0] != 0:
        return {'ok': False, 'reason': 'candidate-clean-did-not-initialize', 'exits': exits}
    outcomes = []
    for case in cases[1:]:
        if case.get('status') == 'initialized' and case.get('exit') == 0:
            outcomes.append({'case': case['case'], 'outcome': 'egl-initialized'})
        elif case.get('status') == 'egldevice-unavailable' and case.get('exit') in (3, 4):
            outcomes.append({
                'case': case['case'], 'exit': case['exit'],
                'outcome': ('unexercised-egldevice-enumeration' if case['exit'] == 3
                            else 'unexercised-no-matching-egldevice'),
            })
        else:
            return {'ok': False, 'reason': 'candidate-probe-crash-or-failure', 'exits': exits}
    return {'ok': True, 'reason': 'candidate-no-probe-crash', 'cases': outcomes}


def compare_arm(manifest: dict, arm: str, report: dict) -> dict:
    from mesa_3969_packages import select_closure, validate_installed

    failures = list(report.get('observer_errors', []))
    advisories = []
    snapshots = report.get('snapshots', [])
    if not snapshots:
        return {'ok': False, 'failures': ['no-live-guest-observation'], 'gate_exit': report.get('gate_exit')}
    boots = {snapshot['boot_id'] for snapshot in snapshots}
    if len(boots) != 1:
        failures.append('guest-boot-identity-changed')
    baseline = report['baseline_inventory']
    selected = select_closure(baseline, manifest['arms'][arm]['packages'])
    renderers = []
    probes = []
    for snapshot in snapshots:
        try:
            validate_installed(baseline, snapshot['inventory'], selected)
        except LabError as error:
            failures.append(f'installed-package-identity: {error}')
        if snapshot.get('software_policy_sha256') != manifest['baseline']['software_policy_sha256']:
            failures.append('software-policy-changed')
        if snapshot.get('selinux') != 'Enforcing':
            failures.append('selinux-not-enforcing')
        if snapshot.get('probe', {}).get('boot_id') != snapshot['boot_id']:
            failures.append('probe-boot-identity-mismatch')
        probes.append(snapshot.get('probe'))
        renderers.extend(snapshot.get('renderer_records', []))
        if arm == 'candidate' and (snapshot.get('crashes') or snapshot.get('kernel_crash')):
            failures.append('candidate-compositor-crash')
    if any(probe != probes[0] for probe in probes):
        failures.append('probe-record-changed')
    result = probe_verdict(probes[0], arm, manifest)
    if not result['ok']:
        failures.append(result['reason'])
    # A control GDM failure is retained and expected as a negative observation;
    # it never substitutes for the independently required four-case reproduction.
    if arm == 'candidate':
        if report.get('gate_exit') != 0:
            failures.append('candidate-real-gdm-gate-failed')
        transitions = report.get('transitions', {})
        if not all(transitions.get(key) for key in ('login', 'lock', 'unlock', 'same_session')):
            failures.append('missing-real-wayland-ui-transitions')
        if not all(report.get('screenshots', {}).get(key) for key in ('ready', 'logged-in', 'locked', 'unlocked')):
            failures.append('missing-visible-ui-evidence')
        # tuna-desktop is pre-alpha (owner decision 2026-10-29): its user-session
        # renderer is recorded when observed but never gates the verdict. The
        # GDM greeter (Mesa in gnome-shell) and the real login/lock/unlock above do.
        if not any(record.get('role') == 'greeter' and validate_renderer(record, record.get('boot_id', ''))
                   and record.get('boot_id') in boots for record in renderers):
            failures.append('missing-bound-software-greeter-renderer')
        session = transitions.get('session')
        if not any(record.get('role') == 'user' and record.get('session', {}).get('id') == session
                   and record.get('boot_id') in boots
                   and validate_renderer(record, record.get('boot_id', '')) for record in renderers):
            advisories.append('tuna-user-renderer-unobserved')
    return {'ok': not failures, 'failures': sorted(set(failures)), 'advisories': sorted(set(advisories)), 'probe': result,
            'gate_exit': report.get('gate_exit'), 'transitions': report.get('transitions'),
            'boot_ids': sorted(boots), 'renderer_record_count': len(renderers)}


def compare(manifest: dict, reports: dict) -> dict:
    arms = {arm: compare_arm(manifest, arm, reports[arm]) for arm in ('control', 'candidate')}
    distinct_boots = not set(arms['control'].get('boot_ids', [])) & set(arms['candidate'].get('boot_ids', []))
    ok = all(value['ok'] for value in arms.values()) and distinct_boots
    return {'schema_version': 1, 'verdict': 'lab-repair-demonstrated' if ok else 'repair-not-demonstrated',
            'ok': ok, 'arms': arms, 'distinct_arm_boots': distinct_boots,
            'scope': 'One VM per arm; not ISO, hardware or epic qualification.'}


def transition_evidence(log: str) -> dict:
    matches = {}
    for kind in ('LOGIN', 'LOCK', 'UNLOCK'):
        found = list(re.finditer(rf'^TUNAOS_GDM_{kind}_OK user=tuna-ci-login session=([A-Za-z0-9_-]+)$', log, re.MULTILINE))
        matches[kind] = found[-1] if found else None
    valid = all(matches.values())
    same = valid and len({match.group(1) for match in matches.values()}) == 1
    ordered = valid and matches['LOGIN'].start() < matches['LOCK'].start() < matches['UNLOCK'].start()
    return {'login': matches['LOGIN'] is not None, 'lock': matches['LOCK'] is not None,
            'unlock': matches['UNLOCK'] is not None, 'same_session': bool(same and ordered),
            'session': matches['LOGIN'].group(1) if matches['LOGIN'] else None}


def fixed_environment(home: Path, corral: str) -> dict:
    environment = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'ImageOS', 'ImageVersion') if key in os.environ}
    environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
                       XDG_DATA_HOME=str(home / '.local/share'), XDG_CACHE_HOME=str(home / '.cache'),
                       XDG_RUNTIME_DIR=str(home / '.runtime'),
                       CORRAL=corral, TUNAOS_GDM_LOGIN_CHECK='1', DISK_CONTRACT='desktop')
    return environment


def privileged_environment(environment: dict) -> list[str]:
    return ['sudo', '-n', 'env', '-i', *[f'{key}={value}' for key, value in environment.items()]]


def stage_helpers(repo: Path, target: Path) -> Path:
    for name in ('corral-boot-gate.sh', 'gdm-login-gate.sh', 'greeter-graphics-evidence.sh', 'lib/backend.sh'):
        _, content, _ = bounded_command(['git', '-C', repo, 'show', f'{INPUTS["helper_commit"]}:scripts/{name}'])
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o755)
    return target / 'corral-boot-gate.sh'


def retain_text(source: Path, destination: Path, *, limit=8 * 1024 * 1024) -> str:
    if not source.is_file():
        return ''
    with source.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise LabError(f'evidence exceeds bound: {source.name}')
    # Core evidence packing decodes selected text strictly, so an invalid byte
    # in the serial console must not discard the whole published bundle.
    text = data.decode('utf-8', 'replace')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding='utf-8')
    return text


def finish_arm_evidence(report: dict, raw: Path, selected: Path, observer_count: int) -> None:
    report['observer_unique_samples'] = observer_count
    log_text = retain_text(raw / 'gate.log', selected / 'gate.log')
    retain_text(raw / 'serial.log', selected / 'serial.log')
    retain_text(raw / 'vm-host-evidence.txt', selected / 'vm-host-evidence.txt')
    report['transitions'] = transition_evidence(log_text)
    collector_parts = []
    for path in (selected / 'greeter-graphics.txt', raw / 'greeter-graphics-evidence.txt',
                 raw / 'greeter-graphics-evidence-after-failure.txt'):
        if path.is_file():
            with path.open('rb') as stream:
                value = stream.read(2 * 1024 * 1024 + 1)
            if len(value) > 2 * 1024 * 1024:
                raise LabError('greeter evidence exceeds bound')
            collector_parts.append(f'\n==> {path.name}\n' + value.decode('utf-8', 'replace'))
    if collector_parts:
        (selected / 'greeter-graphics.txt').write_text(''.join(collector_parts))
    report['screenshots'] = {}
    for key, filename in {'ready': 'gdm-greeter.png', 'logged-in': 'gdm-logged-in.png',
                          'locked': 'gdm-locked.png', 'unlocked': 'gdm-unlocked.png'}.items():
        source = raw / filename
        exists = source.is_file() and 8 <= source.stat().st_size <= 4 * 1024 * 1024
        if exists:
            with source.open('rb') as stream:
                exists = stream.read(8) == b'\x89PNG\r\n\x1a\n'
        report['screenshots'][key] = exists
        if exists:
            destination = selected / 'screenshots' / f'{key}.png'
            destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, destination)
    if report['snapshots']:
        snapshot = report['snapshots'][0]
        write_json(selected / 'probe.json', snapshot['probe'])
        write_json(selected / 'renderer.json', {
            'boot_id': snapshot['boot_id'], 'records': snapshot['renderer_records'],
            'crashes': snapshot['crashes'], 'kernel_crash': snapshot['kernel_crash'],
        })
    write_json(selected / 'report.json', report)


def owned_ssh_argv(home: Path, raw: Path, name: str) -> list[str]:
    expected = f'mesa3969-{os.environ["GITHUB_RUN_ID"]}-'
    if name not in (expected + 'control', expected + 'candidate'):
        raise LabError('observer VM name is not owned by this runtime')
    vm = home / '.local/share/corral/vms' / name
    metadata_path = vm / 'metadata.json'
    identity = raw / 'corral/ssh/id_ed25519'
    for path, bound in ((metadata_path, 65536), (identity, 16384)):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or not 0 < info.st_size <= bound or path.resolve() != path):
            raise LabError('observer endpoint/identity is not a bounded owned regular file')
    if identity.stat().st_mode & 0o077:
        raise LabError('observer identity permissions are not private')
    metadata = read_json(metadata_path)
    port = metadata.get('ssh_port')
    if (metadata.get('name') != name or metadata.get('tailscale_ip') not in ('', '127.0.0.1')
            or type(port) is not int or not 1024 <= port <= 65535
            or metadata.get('serial_log') != str(vm / 'serial.log')):
        raise LabError('observer endpoint differs from owned loopback VM metadata')
    return [
        'ssh', '-F', '/dev/null', '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'LogLevel=ERROR',
        '-o', 'ConnectTimeout=5', '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
        '-i', str(identity), '-p', str(port), 'root@127.0.0.1',
    ]


def run_arm(arm: str, image: str, root: Path, gate: Path, baseline: list, corral: str,
            derived_resource: dict) -> dict:
    work = root / 'work' / arm
    home = work / 'home'
    home.mkdir(parents=True, mode=0o700)
    (home / '.runtime').mkdir(mode=0o700)
    raw = work / 'gate'
    raw.mkdir()
    selected = root / 'work' / 'selected' / arm
    selected.mkdir(parents=True)
    environment = fixed_environment(home, corral)
    name = f'mesa3969-{os.environ["GITHUB_RUN_ID"]}-{arm}'
    environment['GATE_NAME'] = name
    report = {'schema_version': 1, 'arm': arm, 'baseline_inventory': baseline,
              'snapshots': [], 'observer_errors': [], 'gate_exit': None}
    process = None
    observer_count = 0
    observed = set()
    try:
        with (raw / 'gate.log').open('wb') as log:
            process = subprocess.Popen(
                [*privileged_environment(environment), 'bash', str(gate), image, str(raw), '900'],
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
            )
            CHILDREN.add(process)
            while process.poll() is None:
                metadata = stored_metadata(['sudo', '-n', 'podman'], 'image', derived_resource['tag'])
                if metadata is not None:
                    image_id = runtime_image(metadata, derived_resource['parent'])
                    if derived_resource.get('id') not in (None, image_id):
                        raise LabError('derived Corral image changed while gate was live')
                    derived_resource['id'] = image_id
                # No gate pause or extra VM. A failed SSH observation cannot alter
                # the pinned gate exit; required missing evidence fails comparison.
                try:
                    _, output, _ = bounded_command([
                        *privileged_environment(environment), *owned_ssh_argv(home, raw, name),
                        'python3 /usr/local/libexec/mesa-3969/mesa_3969_guest.py observe'
                        + (' --identity-only' if not report['snapshots'] else ''),
                    ], timeout=50, limit=4 * 1024 * 1024)
                    snapshot = json.loads(output)
                    collector = snapshot.pop('greeter_evidence')
                    evidence = selected / 'greeter-graphics.txt'
                    if collector and not evidence.exists():
                        evidence.write_text(collector)
                    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
                    if fingerprint not in observed:
                        observed.add(fingerprint)
                        observer_count += 1
                        # Retain identities once, renderer records as a bounded
                        # union, and cumulative crashes; not hundreds of RPMdbs.
                        if not report['snapshots']:
                            report['snapshots'].append(snapshot)
                        else:
                            previous = report['snapshots'][-1]
                            if any(previous[key] != snapshot[key] for key in (
                                'boot_id', 'inventory', 'software_policy_sha256', 'selinux', 'probe',
                            )):
                                report['observer_errors'].append('live-guest-identity-or-policy-drift')
                            previous['renderer_records'] = list({
                                (item['boot_id'], item['pid'], item['process']['start_ticks'],
                                 item['role'], item['session']['id'],
                                 item['journal']['__MONOTONIC_TIMESTAMP'], item['renderer']): item
                                for item in previous['renderer_records'] + snapshot['renderer_records']
                            }.values())
                            previous['crashes'] = list({
                                json.dumps(item, sort_keys=True): item
                                for item in previous['crashes'] + snapshot['crashes']
                            }.values())
                            previous['kernel_crash'] |= snapshot['kernel_crash']
                            if snapshot['renderer_collection'] == 'sampled':
                                previous['renderer_collection'] = 'sampled'
                        if len(observed) > 2048:
                            raise LabError('observer sample count exceeds bound')
                except (OSError, ValueError, LabError) as error:
                    # Early SSH refusals are expected during installation/boot;
                    # preserve a bounded count and final diagnostic, not a pass.
                    report['last_observer_error'] = sanitize_text(str(error))[:2048]
                    if report['snapshots'] and process.poll() is None:
                        report['observer_errors'].append('live-observer-gap-after-first-observation')
                if len(json.dumps(report).encode()) > 3 * 1024 * 1024 or len(observed) > 2048:
                    raise LabError('observer evidence exceeds bound')
                if (raw / 'gate.log').stat().st_size > 8 * 1024 * 1024:
                    raise LabError('gate log exceeds evidence bound')
                time.sleep(1)
            report['gate_exit'] = process.wait()
    finally:
        active_error = sys.exc_info()[1]
        try:
            if process is not None:
                try:
                    stop_process(process)
                except (OSError, LabError, subprocess.SubprocessError) as error:
                    PROCESS_CLEANUP_ERRORS.append(sanitize_text(str(error))[:2048])
                    if active_error is None:
                        raise
                finally:
                    CHILDREN.discard(process)
                    if report['gate_exit'] is None:
                        report['gate_exit'] = process.returncode
        finally:
            try:
                finish_arm_evidence(report, raw, selected, observer_count)
            except (OSError, LabError, ValueError) as error:
                PROCESS_CLEANUP_ERRORS.append(sanitize_text(str(error))[:2048])
                if active_error is None:
                    raise
        # The pinned wrapper owns delete. Do not add a compensating second
        # delete, restart, display-manager repair or timeout-extension shim.
    return report


def stored_metadata(podman: list[str], kind: str, name: str) -> dict | None:
    code, _, _ = bounded_command([*podman, kind, 'exists', name], check=False)
    if code == 1:
        return None
    if code:
        raise LabError(f'cannot establish {kind} presence: {name}')
    _, output, _ = bounded_command([*podman, kind, 'inspect', '--format', '{{json .}}', name])
    value = json.loads(output)
    if not isinstance(value, dict):
        raise LabError(f'{kind} metadata is not an object')
    normalize_image_id(value.get('Id'))
    return value


def require_absent(podman: list[str], kind: str, name: str) -> None:
    if stored_metadata(podman, kind, name) is not None:
        raise LabError(f'refusing preexisting {kind}: {name}')


def runtime_image(metadata: dict, parent: dict) -> str:
    labels = metadata.get('Config', {}).get('Labels', {})
    if (labels.get('io.tunaos.mesa3969.runtime') != os.environ['GITHUB_RUN_ID']
            or labels.get('io.tunaos.mesa3969') != f'{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_SHA"]}'):
        raise LabError('runtime image ownership labels differ')
    image_id = normalize_image_id(metadata.get('Id'))
    parent_id = normalize_image_id(parent.get('Id'))
    layers = metadata.get('RootFS', {}).get('Layers')
    base_layers = parent.get('RootFS', {}).get('Layers')
    if (not isinstance(layers, list) or not isinstance(base_layers, list)
            or not 0 < len(base_layers) < len(layers) <= 512
            or any(not isinstance(layer, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', layer)
                   for layer in layers + base_layers)
            or layers[:len(base_layers)] != base_layers or image_id == parent_id):
        raise LabError('runtime image OCI rootfs ancestry differs')
    # OCI images may omit Parent; a multistep build may name an intermediate
    # rather than the installed base. Only actual RootFS diff-id ancestry,
    # exact inherited ownership and the absent-before-create reservation count.
    return image_id


def remove_runtime_image(podman: list[str], resource: dict) -> None:
    metadata = stored_metadata(podman, 'image', resource['tag'])
    if metadata is None:
        return
    image_id = runtime_image(metadata, resource['parent'])
    if resource.get('id') not in (None, image_id):
        raise LabError('runtime image identity changed after ownership snapshot')
    result_path = resource.get('result')
    if result_path is not None and result_path.exists():
        result = read_json(result_path)
        layer = result.get('layer', {})
        parent_id = normalize_image_id(resource['parent']['Id'])
        # BuildLayer initially records Image=Base; on ExitLayer it may leave
        # that value even after a partial build created the reserved tag.
        partial = (result.get('status') == 'failed' and result.get('exitCode') == 3
                   and layer.get('image') == parent_id)
        if (result.get('name') != resource['name'] or layer.get('derived') is not True
                or layer.get('base') != parent_id
                or (layer.get('image') != resource['tag'] and not partial)):
            raise LabError('Corral layer result contradicts owned image provenance')
    bounded_command([*podman, 'image', 'rm', image_id])


def run_runtime(root: Path) -> int:
    core = Path(__file__).with_name('mesa_3969.py')
    # Repeat admission in the privileged-effect orchestrator, not a local-input
    # bypass. The only destination is the core-authenticated fetch result.
    bounded_command([sys.executable, core, 'admit', '--runtime'])
    expected = Path(os.environ['RUNNER_TEMP']) / f'mesa-3969-{os.environ["GITHUB_RUN_ID"]}-runtime'
    if root != expected or root.is_symlink() or root.resolve() != expected.resolve():
        raise LabError('runtime root differs from admitted owned root')
    work = root / 'work'
    _, receipt, _ = bounded_command([
        sys.executable, core, 'fetch-inputs',
        '--artifact-id', os.environ['MESA_3969_ARTIFACT_ID'],
        '--artifact-digest', os.environ['MESA_3969_ARTIFACT_DIGEST'],
        '--destination', work / 'inputs',
    ], timeout=600)
    fetched = json.loads(receipt)
    transfer = work / 'inputs'
    if fetched['directory'] != str(transfer):
        raise LabError('fetch destination mismatch')
    manifest = read_json(transfer / 'manifest.json')
    baseline = read_json(transfer / 'baseline-inventory.json')
    corral = shutil.which('corral')
    if not corral:
        raise LabError('pinned Corral executable is missing')
    gate = stage_helpers(Path(__file__).resolve().parents[2], work / 'helpers')
    podman = ['sudo', '-n', 'podman']
    label = f'io.tunaos.mesa3969.runtime={os.environ["GITHUB_RUN_ID"]}'
    containers = []
    images = []
    derived = []
    reports = {}
    baseline_loaded = False
    try:
        require_absent(podman, 'image', manifest['baseline']['image_tag'])
        require_absent(podman, 'image', manifest['baseline']['image_id'])
        baseline_loaded = True
        bounded_command([*podman, 'load', '--input', transfer / 'baseline.oci.tar'], timeout=300)
        _, output, _ = bounded_command([*podman, 'image', 'inspect', '--format', '{{.Id}}', manifest['baseline']['image_tag']])
        baseline_id = normalize_image_id(output.strip())
        if baseline_id != manifest['baseline']['image_id']:
            raise LabError('loaded baseline image identity mismatch')
        _, configuration, _ = bounded_command([
            *podman, 'image', 'inspect', '--format', '{{json .Config}}', baseline_id,
        ])
        baseline_config = json.loads(configuration)
        if baseline_config.get('Labels', {}).get('io.tunaos.mesa3969') != (
                f'{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_SHA"]}'):
            raise LabError('loaded baseline has no exact run/head ownership label')
        baseline_metadata = stored_metadata(podman, 'image', baseline_id)
        mount = f'type=bind,src={transfer},dst=/run/mesa-3969-inputs,ro'
        verifier = f'mesa3969-{os.environ["GITHUB_RUN_ID"]}-verify'
        require_absent(podman, 'container', verifier)
        containers.append(verifier)
        bounded_command([
            *podman, 'run', '--name', verifier, '--rm', '--label', label,
            '--network=none', '--mount', mount, '--entrypoint=', baseline_id,
            'python3', LIBEXEC / 'mesa_3969_packages.py', 'verify-transfer', '--directory', '/run/mesa-3969-inputs',
        ], timeout=300)
        containers.remove(verifier)
        for arm in ('control', 'candidate'):
            name = f'mesa3969-{os.environ["GITHUB_RUN_ID"]}-{arm}-install'
            tag = f'localhost/mesa3969-{os.environ["GITHUB_RUN_ID"]}:{arm}'
            require_absent(podman, 'container', name)
            require_absent(podman, 'image', tag)
            containers.append(name)
            bounded_command([
                *podman, 'create', '--name', name, '--label', label, '--network=none', '--mount', mount,
                '--entrypoint=', baseline_id, 'python3', LIBEXEC / 'mesa_3969_packages.py',
                'install', '--directory', '/run/mesa-3969-inputs', '--arm', arm,
            ])
            bounded_command([*podman, 'start', '--attach', name], timeout=300)
            _, output, _ = bounded_command([*podman, 'inspect', '--format', '{{.State.ExitCode}}', name])
            if output.strip() != '0':
                raise LabError(f'{arm} offline package replacement failed')
            installed_resource = {'tag': tag, 'parent': baseline_metadata}
            images.append(installed_resource)
            bounded_command([
                *podman, 'commit', '--change', f'LABEL {label}',
                '--change', 'CMD ' + json.dumps(baseline_config.get('Cmd') or []),
                '--change', 'ENTRYPOINT ' + json.dumps(baseline_config.get('Entrypoint') or []),
                name, tag,
            ], timeout=300)
            bounded_command([*podman, 'rm', name])
            containers.remove(name)
            metadata = stored_metadata(podman, 'image', tag)
            image = runtime_image(metadata, baseline_metadata)
            installed_resource['id'] = image
            vm_name = f'mesa3969-{os.environ["GITHUB_RUN_ID"]}-{arm}'
            derived_tag = f'localhost/corral-vmtest/{vm_name}:latest'
            require_absent(podman, 'image', derived_tag)
            derived.append({
                'tag': derived_tag, 'parent': metadata, 'name': vm_name,
                'result': work / arm / 'gate/corral/result.json',
            })
            reports[arm] = run_arm(arm, image, root, gate, baseline, corral, derived[-1])
        result = compare(manifest, reports)
        write_json(work / 'selected' / 'comparison.json', result)
        return 0 if result['ok'] else 1
    except BaseException as error:
        selected = work / 'selected'
        selected.mkdir(parents=True, exist_ok=True)
        write_json(selected / 'comparison.json', {
            'schema_version': 1, 'ok': False, 'verdict': 'runtime-failed-or-cancelled',
            'reason': sanitize_text(str(error))[:2048],
        })
        raise
    finally:
        active_error = sys.exc_info()[1]
        process_errors = len(PROCESS_CLEANUP_ERRORS)
        cleanup_errors = list(PROCESS_CLEANUP_ERRORS)
        for name in containers:
            try:
                metadata = stored_metadata(podman, 'container', name)
                if metadata is None:
                    continue
                labels = metadata.get('Config', {}).get('Labels', {})
                if (labels.get('io.tunaos.mesa3969.runtime') != os.environ['GITHUB_RUN_ID']
                        or labels.get('io.tunaos.mesa3969') != f'{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_SHA"]}'
                        or normalize_image_id(metadata.get('Image')) != manifest['baseline']['image_id']):
                    raise LabError('runtime container ownership labels differ')
                bounded_command([*podman, 'container', 'rm', '--force', normalize_image_id(metadata['Id'])])
            except (OSError, ValueError, TypeError, AttributeError, LabError, subprocess.SubprocessError) as error:
                cleanup_errors.append(sanitize_text(str(error))[:2048])
        # Corral --user builds child images which survive VM deletion. Never
        # prune: inspect each reserved name and remove verified children first.
        for resource in [*reversed(derived), *reversed(images)]:
            try:
                remove_runtime_image(podman, resource)
            except (OSError, ValueError, TypeError, AttributeError, LabError, subprocess.SubprocessError) as error:
                cleanup_errors.append(sanitize_text(str(error))[:2048])
        if baseline_loaded:
            try:
                metadata = stored_metadata(podman, 'image', manifest['baseline']['image_tag'])
                if metadata is not None:
                    image_id = normalize_image_id(metadata.get('Id'))
                    if (image_id != manifest['baseline']['image_id']
                            or metadata.get('Config', {}).get('Labels', {}).get('io.tunaos.mesa3969')
                            != f'{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_SHA"]}'):
                        raise LabError('baseline cleanup identity/ownership differs')
                    bounded_command([*podman, 'image', 'rm', image_id])
            except (OSError, ValueError, TypeError, AttributeError, LabError, subprocess.SubprocessError) as error:
                cleanup_errors.append(sanitize_text(str(error))[:2048])
        # Cleanup itself can strand a process group; those errors arrive after
        # the copy above and must still reach comparison.json.
        cleanup_errors.extend(PROCESS_CLEANUP_ERRORS[process_errors:])
        selected = work / 'selected'
        if cleanup_errors:
            selected.mkdir(parents=True, exist_ok=True)
            result_path = selected / 'comparison.json'
            result = read_json(result_path) if result_path.exists() else {'schema_version': 1}
            result.update(ok=False, verdict='owned-resource-cleanup-failed', cleanup_errors=cleanup_errors)
            write_json(result_path, result)
        if selected.exists():
            try:
                bounded_command([sys.executable, core, 'pack-evidence', '--source', selected,
                                 '--output', root / 'evidence'], timeout=60)
            except (OSError, ValueError, LabError, subprocess.SubprocessError):
                if active_error is None:
                    raise
                print('runtime evidence packing failed during unwind', file=sys.stderr)
        if cleanup_errors and active_error is None:
            raise LabError('owned runtime resource cleanup failed; see comparison.json')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('probe')
    observation = commands.add_parser('observe')
    observation.add_argument('--identity-only', action='store_true')
    runtime = commands.add_parser('run')
    runtime.add_argument('--root', type=Path, required=True)
    comparison = commands.add_parser('compare')
    comparison.add_argument('--manifest', type=Path, required=True)
    comparison.add_argument('--control', type=Path, required=True)
    comparison.add_argument('--candidate', type=Path, required=True)
    comparison.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        if args.command == 'probe':
            try:
                result = collect_probe()
            except (OSError, ValueError, LabError) as error:
                result = {'schema_version': 1, 'status': 'collection-failed', 'error': str(error), 'cases': []}
            Path('/run/mesa-3969').mkdir(mode=0o700, exist_ok=True)
            write_json('/run/mesa-3969/probe.json', result)
            return 0  # Collection does not gate/repair display startup.
        if args.command == 'observe':
            def expired(_signum, _frame):
                raise LabError('guest observer exceeded its 40-second bound')
            signal.signal(signal.SIGALRM, expired)
            signal.alarm(40)
            print(json.dumps(collect_snapshot(args.identity_only), sort_keys=True))
            return 0
        if args.command == 'compare':
            result = compare(read_json(args.manifest), {
                'control': read_json(args.control), 'candidate': read_json(args.candidate),
            })
            write_json(args.output, result)
            return 0 if result['ok'] else 1
        return run_runtime(args.root)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'mesa-3969: refused/failed: {sanitize_text(str(error))}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
