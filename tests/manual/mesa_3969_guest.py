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
import errno
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

from mesa_3969 import (
    INPUTS,
    LabError,
    check_runtime_path_budget,
    normalize_image_id,
    read_json,
    runtime_home,
    runtime_vm_name,
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
# The fix (c9b29866) changes src/egl only, so libEGL_mesa carries the patched
# bytes. Run 41051314549's crash frames are in libEGL_mesa and libgallium; the
# GLX, gbm and dri modules are the rest of Mesa a compositor can map.
MESA_LIBRARY = re.compile(
    r'/usr/lib64/(?:libEGL_mesa\.so[.0-9]*|libGLX_mesa\.so[.0-9]*|libgallium-[^/]+\.so'
    r'|libgbm\.so[.0-9]*|dri/[^/]+\.so|gbm/[^/]+\.so)')
MESA_LIBRARY_GLOBS = (
    'usr/lib64/libEGL_mesa.so*', 'usr/lib64/libGLX_mesa.so*', 'usr/lib64/libgallium-*.so',
    'usr/lib64/libgbm.so*', 'usr/lib64/dri/*.so', 'usr/lib64/gbm/*.so',
)
PATCHED_LIBRARY = 'libEGL_mesa.so'
MAX_LIBRARY_BYTES = 512 * 1024 * 1024
GUEST_ROOT = Path('/')
# Longer than one bounded observation (50 s) plus its group termination.
TEARDOWN_WAIT = 70
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


def process_start_ticks(pid: int) -> int | None:
    try:
        return int(Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()[19])
    except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
        return None


def group_is_ours(process) -> bool:
    """A recycled PID must not make us signal an unrelated process group.

    While our leader is gone its descendants keep the group alive, so the
    group id is ours. Once the number names a live process with a different
    start time, the kernel has recycled it and that group is not ours.
    """
    recorded = getattr(process, 'mesa_start_ticks', None)
    current = process_start_ticks(process.pid)
    return recorded is None or current is None or current == recorded


def stop_process(process: subprocess.Popen) -> None:
    if not group_is_ours(process):
        process.poll()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 5
    while live_process_group(process.pid) and time.monotonic() < deadline:
        process.poll()  # Reap the direct child without forgetting the group.
        time.sleep(0.05)
    if group_is_ours(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)
    deadline = time.monotonic() + 1
    while live_process_group(process.pid) and group_is_ours(process) and time.monotonic() < deadline:
        time.sleep(0.01)
    if live_process_group(process.pid) and group_is_ours(process):
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
    process.mesa_start_ticks = process_start_ticks(process.pid)
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


def digest_descriptor(fd: int) -> dict:
    """SHA-256 of an open file from offset 0, bounded; never a path re-resolution."""
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        return {'error': 'not-regular'}
    digest = hashlib.sha256()
    size = 0
    while chunk := os.pread(fd, 1 << 20, size):
        size += len(chunk)
        if size > MAX_LIBRARY_BYTES:
            return {'error': 'exceeds-bound'}
        digest.update(chunk)
    return {'sha256': digest.hexdigest(), 'size': size}


def open_beneath(root: Path, path: str) -> int:
    """Open an absolute image path inside root without following any symlink."""
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] != '/' or any(part in ('.', '..') for part in parts[1:]):
        raise LabError(f'invalid tree path: {path}')
    current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current)
            os.close(current)
            current = child
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=current)
    finally:
        os.close(current)


def tree_digests(root: Path, paths) -> dict:
    """Per-path digest or the reason there is none (absent, symlink, unreadable)."""
    result = {}
    linked: dict = {}  # Hard-linked driver names are one file: hash each inode once.
    for path in sorted(set(paths)):
        try:
            fd = open_beneath(root, path)
        except OSError as error:
            result[path] = {'error': {errno.ENOENT: 'absent', errno.ELOOP: 'symlink',
                                      errno.ENOTDIR: 'absent'}.get(error.errno, f'unreadable-{error.errno}')}
            continue
        except LabError:
            result[path] = {'error': 'invalid-path'}
            continue
        try:
            info = os.fstat(fd)
            key = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if key not in linked:
                linked[key] = digest_descriptor(fd)
            result[path] = dict(linked[key])
        finally:
            os.close(fd)
    return result


def library_paths(root: Path) -> list[str]:
    """Regular Mesa library files present under root, as absolute image paths."""
    found = set()
    for pattern in MESA_LIBRARY_GLOBS:
        for path in root.glob(pattern):
            if path.is_file() and not path.is_symlink():
                found.add('/' + path.relative_to(root).as_posix())
    return sorted(path for path in found if MESA_LIBRARY.fullmatch(path))


def mapped_mesa_libraries(fd: int, cache: dict) -> list[dict]:
    """Mesa files a live process maps, hashed through the mapping itself.

    Run 41051314549's candidate rpmdb named the patched packages while its
    crashing processes ran unpatched libEGL_mesa: neither rpmdb nor a path read
    later identifies loaded bytes. /proc/<pid>/map_files/<range> opens the
    exact mapped file (root only); the path is a recorded fallback whose inode
    is compared with the mapping. cache is keyed by mapping identity.
    """
    keys = []
    for line in read_at(fd, 'maps', limit=8 * 1024 * 1024).decode('utf-8', 'replace').splitlines():
        fields = line.split(None, 5)
        if len(fields) != 6:
            continue
        address, _permissions, _offset, device, inode, name = fields
        deleted = name.endswith(' (deleted)')
        path = name.removesuffix(' (deleted)')
        if not MESA_LIBRARY.fullmatch(path) or not inode.isdigit() or int(inode) == 0:
            continue
        key = (path, device, int(inode))
        if key not in keys:
            keys.append(key)
        if key in cache:
            continue
        record = {'path': path, 'device': device, 'inode': int(inode), 'deleted': deleted}
        try:
            mapped = os.open(f'map_files/{address}', os.O_RDONLY | os.O_CLOEXEC, dir_fd=fd)
            record['source'] = 'map_files'
        except OSError:
            try:
                mapped = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
                record['source'] = 'path'
            except OSError as error:
                cache[key] = dict(record, source='unavailable', error=f'unreadable-{error.errno}')
                continue
        try:
            record['inode_matches'] = os.fstat(mapped).st_ino == int(inode)
            record.update(digest_descriptor(mapped))
        finally:
            os.close(mapped)
        cache[key] = record
    return [cache[key] for key in sorted(keys)]


PTRACE_TRACEME, PTRACE_SYSCALL, PTRACE_SETOPTIONS = 0, 24, 0x4200
PTRACE_OPTIONS = 0x1 | 0x40 | 0x100000  # TRACESYSGOOD | TRACEEXIT | EXITKILL
WAIT_ALL = 0x40000000  # __WALL


class ProbeDeadline(LabError):
    pass


def _ptrace():
    import ctypes
    call = ctypes.CDLL(None, use_errno=True).ptrace
    call.restype = ctypes.c_long
    call.argtypes = (ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)

    def ptrace(request, pid=0, data=0):
        if call(request, pid, None, data or None) == -1:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
    return ptrace


def traced_probe(argv, environment, *, deadline=20, limit=64 * 1024):
    """Run the pinned probe once and record every Mesa file it maps.

    The pinned probe dlopens libEGL, may crash inside eglInitialize and
    dlcloses on success, so no outside sample sees its mappings. It runs as
    our ptrace child: maps are read at every syscall stop, at the fatal-signal
    delivery stop and at PTRACE_EVENT_EXIT (before the address space goes),
    then the signal is re-delivered unchanged. If tracing is refused the probe
    still runs untraced and the case records that, not a mapping.
    """
    ptrace = _ptrace()

    def traceme():
        # A refused PTRACE_TRACEME leaves an untraced probe; the parent sees
        # no exec stop and records that instead of a mapping.
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit + 1, limit + 1))
        try:
            ptrace(PTRACE_TRACEME)
        except OSError:
            pass

    def expired(_signum, _frame):
        raise ProbeDeadline()

    cache: dict = {}
    trace = 'untraced: ptrace refused'
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                   env=environment, start_new_session=True, preexec_fn=traceme)
        previous = signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, deadline)
        status = None

        def capture():
            try:
                fd = os.open(f'/proc/{process.pid}', os.O_RDONLY | os.O_DIRECTORY)
            except OSError:
                return
            try:
                mapped_mesa_libraries(fd, cache)
            except ProbeDeadline:
                raise
            except (OSError, LabError):
                pass  # The tracee exited between stops; its exit status still counts.
            finally:
                os.close(fd)
        try:
            _, status = os.waitpid(process.pid, WAIT_ALL)
            if os.WIFSTOPPED(status):
                trace = 'ptrace'
                ptrace(PTRACE_SETOPTIONS, process.pid, PTRACE_OPTIONS)
                ptrace(PTRACE_SYSCALL, process.pid)
                _, status = os.waitpid(process.pid, WAIT_ALL)
            while os.WIFSTOPPED(status):
                capture()
                stopped = os.WSTOPSIG(status)
                # Syscall (SIGTRAP|0x80) and event stops resume; a real signal
                # (the crash) is delivered exactly as it would be untraced.
                deliver = 0 if stopped in (signal.SIGTRAP, signal.SIGTRAP | 0x80) else stopped
                ptrace(PTRACE_SYSCALL, process.pid, deliver)
                _, status = os.waitpid(process.pid, WAIT_ALL)
        except ProbeDeadline:
            status = None
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            while status is None or os.WIFSTOPPED(status):
                # Deadline, error or cancellation: never leave a stopped tracee.
                # A killed tracee still makes its PTRACE_EVENT_EXIT stop, so
                # it is resumed as well as killed or it waits on us forever.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if status is not None:
                    try:
                        ptrace(PTRACE_SYSCALL, process.pid)
                    except OSError:
                        pass
                try:
                    _, status = os.waitpid(process.pid, WAIT_ALL)
                except ChildProcessError:
                    status = None
                    break
        if status is None:
            normalized = 137
        else:
            normalized = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 128 + os.WTERMSIG(status)
        process.returncode = normalized
        output = []
        for stream in (out, err):
            stream.seek(0)
            data = stream.read(limit + 1)
            output.append(data)
        if sum(map(len, output)) > limit:
            raise LabError(f'command output exceeds bound: {argv[0]}')
    stdout, stderr = (value.decode('utf-8', 'replace') for value in output)
    return normalized, stdout, stderr, sorted(cache.values(), key=lambda item: (item['path'], item['inode'])), trace


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
            normalized, stdout, stderr, mapped, trace = traced_probe(
                [str(binary), device], environment, deadline=20, limit=64 * 1024,
            )
            status = ('initialized' if normalized == 0 and 'eglInitialize=success ' in stdout
                      else 'egldevice-unavailable' if normalized in (3, 4)
                      else 'crashed' if normalized in (132, 134, 135, 136, 139)
                      else 'timeout' if normalized in (124, 137) else 'failed')
            result['cases'].append({
                'case': case, 'exit': normalized, 'status': status,
                'started_us': started, 'ended_us': time.monotonic_ns() // 1000,
                'stdout': stdout, 'stderr': stderr, 'trace': trace, 'mapped_mesa': mapped,
            })
        except (OSError, LabError, subprocess.SubprocessError) as error:
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


def journalctl_output(argv) -> str:
    """journalctl stdout, where an unmatched --grep is no entries, not a failure.

    systemd 257 src/journal/journalctl-show.c returns -ENOENT (exit 1) when a
    --grep pattern matched nothing, "to mimic grep"; -o json implies --quiet, so
    that exit prints nothing at all. Run 41051314549's control guest had no
    gnome-shell segfault for the kernel query to match, so every observation
    failed and the arm recorded none. Any other failure still refuses.
    """
    rc, output, error = bounded_command(argv, timeout=5, check=False)
    if rc == 1 and not output and not error and any(str(part).startswith('--grep=') for part in argv):
        return ''
    if rc:
        raise LabError(f'command failed ({rc}): journalctl: {sanitize_text(error[-2048:])}')
    return output


def journal_entries(*matches, limit=256) -> list[dict]:
    output = journalctl_output([
        'journalctl', '-b', '--all', '--no-pager', '-o', 'json', '-n', str(limit), *matches,
    ])
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


def collect_mapped_libraries(sessions: list[dict]) -> list[dict]:
    """Mesa bytes each live gnome-shell maps; greeter role from its logind session."""
    greeter_uids = {session.get('User') for session in sessions if session.get('Class') == 'greeter'}
    cache: dict = {}
    result = []
    for path in Path('/proc').glob('[0-9]*'):
        fd = None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            if read_at(fd, 'comm').strip() != b'gnome-shell':
                continue
            identity = process_identity(fd)
            libraries = mapped_mesa_libraries(fd, cache)
            if process_identity(fd) != identity:
                continue
            result.append({
                'pid': int(path.name), 'process': identity, 'libraries': libraries,
                'role': 'greeter' if str(identity['uid']) in greeter_uids else 'other',
            })
        except (OSError, ValueError, KeyError, IndexError, LabError):
            continue
        finally:
            if fd is not None:
                os.close(fd)
    return sorted(result, key=lambda item: item['pid'])


def guest_provenance() -> dict:
    """Digests of the Mesa files in the running root and the booted ostree deployment.

    Paired with the host's committed and derived image digests, a mismatch
    shows where patched bytes were replaced: image commit, Corral's derived
    layer, or the ostree import that bootc install performed.
    """
    paths = library_paths(GUEST_ROOT)
    result = {'root': {'files': tree_digests(GUEST_ROOT, paths)}}
    try:
        _, current, _ = bounded_command(['ostree', 'admin', '--print-current-dir'], timeout=10)
        deployment = Path(current.strip())
        if not deployment.is_absolute() or deployment.is_symlink() or not deployment.is_dir():
            raise LabError('ostree deployment directory is not an absolute real directory')
        result['deployment'] = {'directory': str(deployment), 'files': tree_digests(deployment, paths)}
    except (OSError, LabError, subprocess.SubprocessError) as error:
        result['deployment'] = {'error': sanitize_text(str(error))[:512]}
    return result


def collect_snapshot(identity_only=False) -> dict:
    from mesa_3969_packages import query_inventory, verify_installed_files

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
    kernel = journalctl_output([
        'journalctl', '-k', '-b', '--no-pager', '-o', 'json',
        '--grep=(gnome-shell|tuna-compositor).*(segfault|trap|general protection)', '-n', '128',
    ])
    if len(kernel.splitlines()) >= 128:
        raise LabError('kernel crash event bound reached')
    _, enforcing, _ = bounded_command(['getenforce'], timeout=3)
    inventory = query_inventory()
    snapshot = {
        'schema_version': 1, 'boot_id': boot, 'renderer_records': records,
        'renderer_collection': 'not-requested' if identity_only else 'sampled',
        'greeter_evidence': collector, 'crashes': crashes,
        'kernel_crash': bool(kernel.strip()), 'selinux': enforcing.strip(),
        'software_policy_sha256': sha256_file(POLICY), 'inventory': inventory,
        'file_verification': verify_installed_files(inventory),
        'mapped_libraries': collect_mapped_libraries(session_records()),
        'probe': probe,
    }
    if identity_only:
        # Once per boot: the first retained observation carries the tree digests.
        snapshot['provenance'] = guest_provenance()
    return snapshot


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


def _payload_digest(table, path):
    entry = table.get(path) if isinstance(table, dict) else None
    return entry.get('sha256') if isinstance(entry, dict) else None


def loaded_library_verdict(arm: str, report: dict, snapshots: list) -> tuple[list, list, list]:
    """Compare mapped Mesa bytes with the transferred RPM payload of each arm.

    rpmdb identity is not loaded-byte identity (run 41051314549). Every mapped
    Mesa file in the pre-display probe and the greeter's gnome-shell must have
    exactly the arm's payload digest; the control must never map bytes that
    only the candidate ships. Unobserved patched-library mappings are missing
    evidence; only the control's crash-looping greeter is advisory.
    """
    payload = report.get('rpm_payload')
    if not isinstance(payload, dict) or not all(
            isinstance(payload.get(name), dict) and payload[name] for name in ('control', 'candidate')):
        return ['missing-rpm-payload-digests'], [], []
    failures, advisories = [], []
    probe = (snapshots[0].get('probe') or {}) if snapshots else {}
    sources = {
        'probe': [library for case in probe.get('cases') or [] for library in case.get('mapped_mesa') or []],
        'greeter': [library for snapshot in snapshots for process in snapshot.get('mapped_libraries') or []
                    if process.get('role') == 'greeter' for library in process.get('libraries') or []],
    }
    for source, libraries in sources.items():
        if not any(PurePosixPath(str(item.get('path', ''))).name.startswith(PATCHED_LIBRARY) for item in libraries):
            (advisories if arm == 'control' and source == 'greeter' else failures).append(
                f'{arm}-{source}-mapped-library-unobserved')
    mapped = [*sources['probe'], *sources['greeter']]
    for library in mapped:
        # map_files is the mapped file by construction; a path read whose inode
        # is not the mapping's (replaced since mapping) describes other bytes.
        stale = library.get('source') == 'path' and library.get('inode_matches') is not True
        actual = None if stale else library.get('sha256')
        if actual is None or actual != _payload_digest(payload[arm], library.get('path')):
            failures.append(f'{arm}-library-not-loaded')
        if (arm == 'control' and actual is not None
                and actual == _payload_digest(payload['candidate'], library.get('path'))
                and actual != _payload_digest(payload['control'], library.get('path'))):
            failures.append('control-maps-candidate-bytes')
    return failures, advisories, mapped


PROVENANCE_STAGES = ('committed_image', 'derived_image', 'guest_deployment', 'guest_root', 'mapped')


def byte_provenance(arm: str, report: dict, snapshots: list, mapped: list) -> dict:
    """Each Mesa library's digest at every stage, and the first stage that differs.

    Diagnostic only: the verdict is decided by the mapped bytes above. Values
    are digests, a recorded reason (absent, symlink, ...) or None when that
    stage recorded nothing for the path.
    """
    payload = (report.get('rpm_payload') or {}).get(arm) or {}
    host = report.get('provenance') or {}
    guest = ((snapshots[0].get('provenance') if snapshots else None) or {})
    tables = {
        'committed_image': (host.get('committed_image') or {}).get('files') or {},
        'derived_image': (host.get('derived_image') or {}).get('files') or {},
        'guest_deployment': (guest.get('deployment') or {}).get('files') or {},
        'guest_root': (guest.get('root') or {}).get('files') or {},
    }
    files = {}
    for path in sorted(name for name in payload if MESA_LIBRARY.fullmatch(name)):
        expected = _payload_digest(payload, path)
        row = {'rpm_payload': expected, 'first_divergence': None}
        for stage in PROVENANCE_STAGES:
            if stage == 'mapped':
                values = sorted({str(item.get('sha256')) for item in mapped if item.get('path') == path})
                row[stage] = values or None
                differs = any(value != expected for value in values)
            else:
                entry = tables[stage].get(path)
                row[stage] = (entry.get('sha256') or entry.get('error')) if isinstance(entry, dict) else None
                differs = row[stage] is not None and row[stage] != expected
            if differs and row['first_divergence'] is None:
                row['first_divergence'] = stage
        files[path] = row
    return {
        'stage_errors': {
            'committed_image': (host.get('committed_image') or {}).get('error'),
            'derived_image': (host.get('derived_image') or {}).get('error'),
            'guest_deployment': (guest.get('deployment') or {}).get('error'),
        },
        'files': files,
    }


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
        # Absent verification is unproven bytes, not a pass.
        if snapshot.get('file_verification') != []:
            failures.append('installed-files-differ-from-package-headers')
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
    loaded_failures, loaded_advisories, mapped = loaded_library_verdict(arm, report, snapshots)
    failures.extend(loaded_failures)
    advisories.extend(loaded_advisories)
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
            'boot_ids': sorted(boots), 'renderer_record_count': len(renderers),
            'byte_provenance': byte_provenance(arm, report, snapshots, mapped)}


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
    run_id = int(os.environ["GITHUB_RUN_ID"])
    if name not in (runtime_vm_name(run_id, 'control'), runtime_vm_name(run_id, 'candidate')):
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


def teardown_event(state: Path, event: str, **fields) -> None:
    """Append one ordering record; CLOCK_MONOTONIC is shared by every process."""
    line = json.dumps({'event': event, 'monotonic_ns': time.monotonic_ns(), 'pid': os.getpid(), **fields},
                      sort_keys=True)
    fd = os.open(state / 'events.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, (line + '\n').encode())
    finally:
        os.close(fd)


def teardown_barrier(state: Path, corral: str, argv: list[str], wait=TEARDOWN_WAIT) -> int:
    """The pinned gate's EXIT-trap `corral delete`, after the live observation ends.

    Run 41051314549's candidate: the trap deleted the VM while the gate was
    still running, so the next SSH samples got "Connection refused" and were
    recorded as live-observer gaps. The request is published first, then the
    observer lock is taken: an in-flight sample finishes (or the bounded wait
    expires) before the delete, and no sample starts after the request.
    """
    teardown_event(state, 'delete-requested', argv=argv)
    os.close(os.open(state / 'teardown-requested', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600))
    lock = os.open(state / 'observer.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        started = time.monotonic()
        outcome = 'observer-idle'
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                outcome = 'observer-finished'
                if time.monotonic() - started >= wait:
                    outcome = 'observer-wait-timeout'
                    break
                time.sleep(0.05)
        teardown_event(state, outcome, waited_ms=int((time.monotonic() - started) * 1000))
        rc = subprocess.run([corral, *argv], stdin=subprocess.DEVNULL, check=False).returncode
        teardown_event(state, 'deleted', exit=rc)
        return rc
    finally:
        os.close(lock)


def corral_teardown_shim(path: Path, corral: str, state: Path) -> Path:
    """CORRAL for the pinned gate: only `delete` (its EXIT trap) passes the barrier."""
    path.write_text(
        '#!/bin/sh\n'
        'if [ "$1" = delete ]; then\n'
        f'\texec {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} teardown-barrier'
        f' --state {shlex.quote(str(state))} --corral {shlex.quote(corral)} -- "$@"\n'
        'fi\n'
        f'exec {shlex.quote(corral)} "$@"\n'
    )
    path.chmod(0o755)
    return path


def teardown_evidence(report: dict, state: Path) -> None:
    """Who won: the barrier's delete ordering and the observer's last sample."""
    events = []
    data = b''
    try:
        fd = os.open(state / 'events.jsonl', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            data = os.read(fd, 64 * 1024)
        finally:
            os.close(fd)
    except OSError as error:
        # Evidence only: an unreadable record never aborts the arm's evidence.
        PROCESS_CLEANUP_ERRORS.append(sanitize_text(f'teardown evidence unreadable: {error}')[:2048])
    for line in data.decode('utf-8', 'replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        events.append(event if isinstance(event, dict) else {'event': 'unparsed', 'line': line[:256]})
    report['teardown'] = {'events': events, 'last_sample': report.pop('last_observer_sample', None)}
    # Only a sample that outlived the bounded wait can have met a deleted VM.
    if any(event.get('event') == 'observer-wait-timeout' for event in events):
        report['observer_errors'].append('teardown-overlapped-live-observation')


def image_tree_digests(podman: list[str], image_id: str, paths: list[str]) -> dict:
    """Digests of paths in a stored image's merged rootfs, via a read-only image mount."""
    try:
        _, mountpoint, _ = bounded_command([*podman, 'image', 'mount', image_id], timeout=120)
        root = Path(mountpoint.strip())
        try:
            if not root.is_absolute() or root.is_symlink() or not root.is_dir():
                raise LabError('image mount point is not an absolute directory')
            return {'image': image_id, 'files': tree_digests(root, paths)}
        finally:
            bounded_command([*podman, 'image', 'unmount', image_id], timeout=120)
    except (OSError, LabError, subprocess.SubprocessError) as error:
        return {'image': image_id, 'error': sanitize_text(str(error))[:512]}


def provenance_paths(payload: dict, arm: str) -> list[str]:
    return sorted(path for path in payload[arm] if MESA_LIBRARY.fullmatch(path))


def merge_snapshot(previous: dict, snapshot: dict, report: dict) -> None:
    """Retain identities once, renderer and mapping records as bounded unions."""
    if any(previous[key] != snapshot[key] for key in (
        'boot_id', 'inventory', 'file_verification', 'software_policy_sha256', 'selinux', 'probe',
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
    # A crash-looping greeter yields a new PID per sample; one record per
    # distinct (role, mapped bytes) keeps the evidence without the churn.
    mappings: dict = {}
    for item in previous.get('mapped_libraries', []) + snapshot.get('mapped_libraries', []):
        mappings.setdefault((item['role'], json.dumps(item['libraries'], sort_keys=True)), item)
    previous['mapped_libraries'] = list(mappings.values())
    previous['kernel_crash'] |= snapshot['kernel_crash']
    if snapshot['renderer_collection'] == 'sampled':
        previous['renderer_collection'] = 'sampled'


def run_arm(arm: str, image: str, root: Path, gate: Path, baseline: list, corral: str,
            derived_resource: dict, payload: dict, provenance: dict) -> dict:
    work = root / 'work' / arm
    home = runtime_home(root, arm)
    home.mkdir(parents=True, mode=0o700)
    (home / '.runtime').mkdir(mode=0o700)
    raw = work / 'gate'
    raw.mkdir(parents=True)
    selected = root / 'work' / 'selected' / arm
    selected.mkdir(parents=True, exist_ok=True)  # Already holds the commit-boundary proof.
    barrier = raw / 'teardown'
    barrier.mkdir(mode=0o700)
    # The gate, and so its EXIT-trap barrier, runs through sudo as another
    # user. Every file both sides write exists before the gate starts and is
    # owned here, so a barrier-created 0600 file can never lock us out.
    for shared in ('events.jsonl', 'observer.lock'):
        os.close(os.open(barrier / shared, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600))
    environment = fixed_environment(home, corral)
    environment['CORRAL'] = str(corral_teardown_shim(work / 'corral-teardown-barrier', corral, barrier))
    name = runtime_vm_name(int(os.environ["GITHUB_RUN_ID"]), arm)
    environment['GATE_NAME'] = name
    report = {'schema_version': 1, 'arm': arm, 'baseline_inventory': baseline,
              'snapshots': [], 'observer_errors': [], 'gate_exit': None,
              'rpm_payload': payload, 'provenance': provenance}
    process = None
    observer_count = 0
    observed = set()
    lock = os.open(barrier / 'observer.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)

    def sample() -> None:
        nonlocal observer_count
        begin = time.monotonic_ns()
        record = report['last_observer_sample'] = {'begin_ns': begin, 'end_ns': None, 'ok': False}
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
                if not report['snapshots']:
                    report['snapshots'].append(snapshot)
                else:
                    merge_snapshot(report['snapshots'][-1], snapshot, report)
                if len(observed) > 2048:
                    raise LabError('observer sample count exceeds bound')
            record['ok'] = True
        except (OSError, ValueError, LabError) as error:
            # Early SSH refusals are expected during installation/boot. The
            # teardown barrier keeps the VM alive for this whole sample, so a
            # failure after the first observation is a real observer gap.
            report['last_observer_error'] = sanitize_text(str(error))[:2048]
            if report['snapshots'] and process.poll() is None:
                report['observer_errors'].append('live-observer-gap-after-first-observation')
        finally:
            record['end_ns'] = time.monotonic_ns()

    try:
        with (raw / 'gate.log').open('wb') as log:
            process = subprocess.Popen(
                [*privileged_environment(environment), 'bash', str(gate), image, str(raw), '900'],
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
            )
            CHILDREN.add(process)
            sampling = True
            while process.poll() is None:
                metadata = stored_metadata(['sudo', '-n', 'podman'], 'image', derived_resource['tag'])
                if metadata is not None:
                    image_id = runtime_image(metadata, derived_resource['parent'])
                    if derived_resource.get('id') not in (None, image_id):
                        raise LabError('derived Corral image changed while gate was live')
                    derived_resource['id'] = image_id
                # No gate pause or extra VM. A failed SSH observation cannot alter
                # the pinned gate exit; required missing evidence fails comparison.
                if sampling:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        sampling = False  # The barrier holds it: delete in progress.
                    else:
                        try:
                            if (barrier / 'teardown-requested').exists():
                                sampling = False
                            else:
                                sample()
                        finally:
                            fcntl.flock(lock, fcntl.LOCK_UN)
                    if not sampling:
                        try:
                            teardown_event(barrier, 'observer-stopped-for-teardown',
                                           last_sample=report.get('last_observer_sample'))
                        except OSError as error:
                            # The gate is mid-delete: an evidence write must
                            # never escape into the finally that kills it.
                            PROCESS_CLEANUP_ERRORS.append(
                                sanitize_text(f'teardown event unwritable: {error}')[:2048])
                if len(json.dumps(report).encode()) > 3 * 1024 * 1024 or len(observed) > 2048:
                    raise LabError('observer evidence exceeds bound')
                if (raw / 'gate.log').stat().st_size > 8 * 1024 * 1024:
                    raise LabError('gate log exceeds evidence bound')
                time.sleep(1)
            report['gate_exit'] = process.wait()
        # Corral's derived child image survives VM deletion until runtime cleanup.
        provenance['derived_image'] = (
            image_tree_digests(['sudo', '-n', 'podman'], derived_resource['id'], provenance_paths(payload, arm))
            if derived_resource.get('id') else {'error': 'derived Corral image was never observed'})
    finally:
        active_error = sys.exc_info()[1]
        os.close(lock)
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
                teardown_evidence(report, barrier)
                finish_arm_evidence(report, raw, selected, observer_count)
            except (OSError, LabError, ValueError) as error:
                PROCESS_CLEANUP_ERRORS.append(sanitize_text(str(error))[:2048])
                if active_error is None:
                    raise
        # The pinned wrapper owns delete; the barrier only orders it after the
        # observer. Do not add a second delete, restart or repair shim.
    return report


def stored_metadata(podman: list[str], kind: str, name: str, *, deadline=None) -> dict | None:
    code, _, _ = bounded_command(
        [*podman, kind, 'exists', name], check=False,
        timeout=30 if deadline is None else min(30, commit_remaining(deadline)))
    if code == 1:
        return None
    if code:
        raise LabError(f'cannot establish {kind} presence: {name}')
    _, output, _ = bounded_command(
        [*podman, kind, 'inspect', '--format', '{{json .}}', name],
        timeout=30 if deadline is None else min(30, commit_remaining(deadline)))
    value = json.loads(output)
    if not isinstance(value, dict):
        raise LabError(f'{kind} metadata is not an object')
    normalize_image_id(value.get('Id'))
    return value


def require_absent(podman: list[str], kind: str, name: str) -> None:
    if stored_metadata(podman, kind, name) is not None:
        raise LabError(f'refusing preexisting {kind}: {name}')


def require_install_base(metadata: dict, baseline_id: str) -> None:
    labels = metadata.get('Config', {}).get('Labels', {})
    if (normalize_image_id(metadata.get('Image')) != baseline_id
            or labels.get('io.tunaos.mesa3969.runtime') != os.environ['GITHUB_RUN_ID']
            or labels.get('io.tunaos.mesa3969') != f'{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_SHA"]}'):
        raise LabError('install container differs from the exact owned baseline')


def full_rootfs_digest(root: Path, *, entry_mtimes=None) -> dict:
    """Canonical streaming proof of all portable filesystem bytes and metadata.

    Covers paths, types/modes, uid/gid, tar-precision mtime, xattrs, symlink
    targets, hardlink topology and device numbers. Go tar WriteHeader rounds
    unspecified-format ModTime to the nearest second (parent's actual VFS
    smoke observed this on export). Only this whole-tree proof uses that
    declared serialization precision; selected RPM file_metadata.mtime_ns
    remains exact. The mountpoint root's mtime is not an image-entry timestamp:
    extraction creates that root anew. Only its mtime is omitted; its mode,
    uid/gid and xattrs remain exact. Inode/dev/ctime/atime are not portable
    across extraction. No file contents or secret values are retained.

    ``entry_mtimes``, when supplied, privately receives exact st_mtime_ns for
    every non-root directory, regular file (each hardlink path included) and
    symlink, excluding OCI whiteout names. It never enters the proof.
    """
    digest = hashlib.sha256()
    hardlinks = {}
    entries = total = 0
    deadline = time.monotonic() + 1200
    entry_path_bytes = 0

    def walk(path, relative):
        nonlocal entries, total, entry_path_bytes
        info = path.lstat()
        entries += 1
        if entries > 1_000_000 or time.monotonic() > deadline:
            raise LabError('full-rootfs identity bound reached')
        if (entry_mtimes is not None and relative != '/'
                and not path.name.startswith('.wh.')
                and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode))):
            # Bounds cover every captured entry, not just directories: the
            # walk itself stops at 1,000,000 entries.
            entry_path_bytes += len(os.fsencode(relative))
            if (len(entry_mtimes) >= 1_000_000 or len(os.fsencode(relative)) > 4096
                    or entry_path_bytes > 128 * 1024**2):
                raise LabError('entry timestamp capture bound reached')
            entry_mtimes[relative] = info.st_mtime_ns
        # Match Go archive/tar Header.ModTime.Round(time.Second), not truncate.
        # The mountpoint root itself has no portable image-entry timestamp.
        mtime_seconds = None if relative == '/' else (info.st_mtime_ns + 500_000_000) // 1_000_000_000
        record = [relative, info.st_mode, info.st_uid, info.st_gid, mtime_seconds]
        record.append([(name, hashlib.sha256(os.getxattr(path, name, follow_symlinks=False)).hexdigest())
                       for name in sorted(os.listxattr(path, follow_symlinks=False))])
        if stat.S_ISREG(info.st_mode):
            key = (info.st_dev, info.st_ino)
            linked = hardlinks.get(key) if info.st_nlink > 1 else None
            if linked is not None:
                record.extend(['hardlink', linked])
            else:
                if info.st_nlink > 1:
                    hardlinks[key] = relative
                content = hashlib.sha256()
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
                with os.fdopen(fd, 'rb') as stream:
                    while chunk := stream.read(1 << 20):
                        total += len(chunk)
                        if total > 64 * 1024**3 or time.monotonic() > deadline:
                            raise LabError('full-rootfs byte/time bound reached')
                        content.update(chunk)
                    after = os.fstat(stream.fileno())
                if (after.st_ino, after.st_size, after.st_mtime_ns) != (
                        info.st_ino, info.st_size, info.st_mtime_ns):
                    raise LabError('rootfs changed during identity capture')
                record.extend([info.st_size, content.hexdigest()])
        elif stat.S_ISLNK(info.st_mode):
            record.append(os.readlink(path))
        elif stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode):
            record.append(info.st_rdev)
        elif not stat.S_ISDIR(info.st_mode) and not stat.S_ISFIFO(info.st_mode):
            raise LabError('unsupported filesystem type in full-rootfs identity')
        encoded = json.dumps(record, ensure_ascii=True, separators=(',', ':')).encode()
        digest.update(len(encoded).to_bytes(8, 'big'))
        digest.update(encoded)
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir(), key=lambda entry: entry.name):
                walk(child, relative.rstrip('/') + '/' + child.name)

    walk(root, '/')
    return {'schema_version': 2, 'mtime_precision': 'nearest-second',
            'root_mtime_policy': 'mountpoint-not-an-image-entry',
            'sha256': digest.hexdigest(), 'entries': entries, 'regular_bytes': total}


def commit_snapshot(podman: list[str], kind: str, identity: str, paths: list[str],
                    *, entry_mtimes=None) -> dict:
    """Capture a stopped container or image without executing any of its code."""
    prefix = [*podman, *(['image'] if kind == 'image' else [])]
    _, mounted, _ = bounded_command([*prefix, 'mount', identity], timeout=120)
    root = Path(mounted.strip())
    active_error = None
    try:
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise LabError('commit identity mount is not an absolute real directory')
        metadata = {}
        for path in paths:
            fd = open_beneath(root, path)
            try:
                info = os.fstat(fd)
                metadata[path] = {'size': info.st_size, 'mode': info.st_mode, 'uid': info.st_uid,
                                  'gid': info.st_gid, 'mtime_ns': info.st_mtime_ns}
            finally:
                os.close(fd)
        return {'files': tree_digests(root, paths), 'file_metadata': metadata,
                'full_rootfs': (full_rootfs_digest(root) if entry_mtimes is None else
                                full_rootfs_digest(root, entry_mtimes=entry_mtimes))}
    except BaseException as error:
        # Track only this function's failure, not an exception active in a
        # caller's surrounding except block. In particular preserve SIGTERM's
        # SystemExit(143) when the unmount also fails.
        active_error = error
        raise
    finally:
        try:
            bounded_command([*prefix, 'unmount', identity], timeout=120)
        except (OSError, LabError, subprocess.SubprocessError) as error:
            PROCESS_CLEANUP_ERRORS.append(sanitize_text(str(error))[:2048])
            if active_error is None:
                raise


def commit_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LabError('native commit entry timestamp serialization exceeded its 1200-second bound')
    return remaining


def rewrite_entry_delta(source, destination, entry_mtimes: dict, deadline: float) -> str:
    """Copy a native tar byte-for-byte except entry-local PAX mtime records.

    Native Podman tails carry no PAX mtime and USTAR truncates to seconds. Every
    non-root directory, regular file, hardlink and symlink captured by the
    frozen installed walk therefore gets an exact PAX mtime; all other PAX
    records (xattrs, owners, paths, link targets), the USTAR header and file
    data stay raw bytes. OCI whiteouts, devices, FIFOs and non-directories
    absent from the capture are copied untouched; an absent directory fails.
    Unsupported extension formats fail closed instead of losing metadata.
    """
    digest = hashlib.sha256()
    consumed = entries = path_bytes = 0
    seen = set()

    def read_exact(size):
        nonlocal consumed
        commit_remaining(deadline)
        consumed += size
        if consumed > 64 * 1024**3:
            raise LabError('native delta byte bound reached')
        data = source.read(size)
        if len(data) != size:
            raise LabError('truncated native delta tar')
        return data

    def emit(data):
        commit_remaining(deadline)
        destination.write(data)
        digest.update(data)

    def pax_records(data):
        records = {}
        while data:
            length, separator, _ = data.partition(b' ')
            if not separator or not length.isdigit() or len(length) > 8:
                raise LabError('malformed native delta PAX length')
            size = int(length)
            if size <= len(length) + 3 or size > len(data) or data[size - 1:size] != b'\n':
                raise LabError('malformed native delta PAX record')
            key, separator, value = data[len(length) + 1:size - 1].partition(b'=')
            if not separator or not key or key in records or b'\0' in key:
                raise LabError('ambiguous native delta PAX record')
            if key.startswith(b'GNU.sparse') or key in (b'size', b'hdrcharset'):
                raise LabError('unsupported native delta PAX extension')
            if key in (b'mtime', b'atime', b'ctime') and not re.fullmatch(rb'[+-]?[0-9]+(?:\.[0-9]+)?', value):
                raise LabError('malformed native delta PAX timestamp')
            if key in (b'uid', b'gid') and not re.fullmatch(rb'[0-9]+', value):
                raise LabError('malformed native delta PAX owner')
            if key == b'linkpath' and (b'\0' in value or len(value) > 4096):
                raise LabError('malformed native delta PAX link target')
            records[key] = (value, data[:size])
            data = data[size:]
        return records

    def pax_record(key, value):
        body = b' ' + key + b'=' + value + b'\n'
        length = len(body) + 1
        while len(str(length)) + len(body) != length:
            length = len(str(length)) + len(body)
        return str(length).encode() + body

    pending = b''
    records = {}
    while True:
        header = read_exact(512)
        if header == bytes(512):
            if pending or read_exact(512) != bytes(512):
                raise LabError('malformed native delta tar trailer')
            emit(bytes(1024))
            while chunk := source.read(1 << 20):
                commit_remaining(deadline)
                consumed += len(chunk)
                if consumed > 64 * 1024**3 or any(chunk):
                    raise LabError('invalid or oversized native delta tar trailer')
                emit(chunk)
            return 'sha256:' + digest.hexdigest()
        try:
            info = tarfile.TarInfo.frombuf(header, 'utf-8', 'surrogateescape')
        except (tarfile.HeaderError, ValueError) as error:
            raise LabError('invalid native delta tar header') from error
        if header[257:263] != b'ustar\0' or info.size < 0:
            raise LabError('unsupported native delta tar format')
        if info.type == tarfile.XHDTYPE:
            if pending or info.size > MAX_CAPTURE:
                raise LabError('nested or oversized native delta PAX header')
            payload = read_exact((info.size + 511) // 512 * 512)
            records = pax_records(payload[:info.size])
            pending = header + payload
            continue
        if info.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE,
                             tarfile.LNKTYPE, tarfile.SYMTYPE, tarfile.CHRTYPE,
                             tarfile.BLKTYPE, tarfile.FIFOTYPE):
            raise LabError('unsupported native delta entry type')
        name = records.get(b'path', (info.name.encode('utf-8', 'surrogateescape'),))[0]
        path = name.decode('utf-8', 'surrogateescape')
        while path.startswith('./'):
            path = path[2:]
        path = path.rstrip('/')
        if path == '.':
            path = ''
        if (len(name) > 4096 or path.startswith('/') or '\0' in path
                or (path and any(part in ('', '.', '..') for part in path.split('/')))):
            raise LabError('unsafe native delta entry path')
        if not path and not info.isdir():
            raise LabError('native delta root entry is not a directory')
        entries += 1
        path_bytes += len(name)
        if entries > 1_000_000 or path_bytes > 32 * 1024**2 or path in seen:
            raise LabError('duplicate or oversized native delta path set')
        seen.add(path)
        if info.type != tarfile.REGTYPE and info.type != tarfile.AREGTYPE and info.size:
            raise LabError('non-file native delta entry has data')
        whiteout = path.rpartition('/')[2].startswith('.wh.')
        ns = None
        if path and not whiteout and info.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE,
                                                   tarfile.LNKTYPE, tarfile.SYMTYPE):
            ns = entry_mtimes.get('/' + path)
            if info.isdir() and type(ns) is not int:
                raise LabError('native delta directory absent from frozen installed metadata')
            if ns is not None and type(ns) is not int:
                raise LabError('malformed frozen installed entry timestamp')
        # A non-directory absent from the installed walk is not this
        # container's entry: copy it raw so the final full-rootfs identity
        # guard reports the change with complete provenance.
        if ns is not None:
            seconds, fraction = divmod(abs(ns), 1_000_000_000)
            exact = ('-' if ns < 0 else '') + f'{seconds}.{fraction:09d}'
            payload = b''.join(raw for key, (_, raw) in records.items() if key != b'mtime')
            payload += pax_record(b'mtime', exact.encode())
            pax = tarfile.TarInfo('./PaxHeaders/entry')
            pax.type = tarfile.XHDTYPE
            pax.size = len(payload)
            emit(pax.tobuf(format=tarfile.USTAR_FORMAT))
            emit(payload + bytes(-len(payload) % 512))
        else:
            emit(pending)
        emit(header)
        remaining = (info.size + 511) // 512 * 512
        while remaining:
            chunk = read_exact(min(remaining, 1 << 20))
            emit(chunk)
            remaining -= len(chunk)
        pending, records = b'', {}


def rewrite_native_oci(layout: Path, entry_mtimes: dict, baseline_layers: list,
                       source_id: str, deadline: float) -> str:
    """Rewrite exactly one derived tail; preserve every ancestor descriptor/blob."""
    manifest_type = 'application/vnd.oci.image.manifest.v1+json'
    config_type = 'application/vnd.oci.image.config.v1+json'
    layer_types = ('application/vnd.oci.image.layer.v1.tar',
                   'application/vnd.oci.image.layer.v1.tar+gzip')
    validated_bytes = 0

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise LabError('duplicate OCI JSON key')
            result[key] = value
        return result

    def decode(data):
        try:
            value = json.loads(data, object_pairs_hook=unique_object)
        except (ValueError, UnicodeError) as error:
            raise LabError('malformed OCI JSON') from error
        if not isinstance(value, dict):
            raise LabError('OCI JSON must be an object')
        return value

    def small_file(path):
        fd = open_beneath(layout, '/' + path)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise LabError('OCI metadata is not a regular file')
            data = stream.read(MAX_CAPTURE + 1)
        if len(data) > MAX_CAPTURE:
            raise LabError('OCI metadata exceeds bound')
        return data

    def blob(descriptor, media_types, *, small=False):
        nonlocal validated_bytes
        if (not isinstance(descriptor, dict) or descriptor.get('mediaType') not in media_types
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(descriptor.get('digest')))
                or type(descriptor.get('size')) is not int
                or not 0 <= descriptor['size'] <= (MAX_CAPTURE if small else 64 * 1024**3)
                or any(key in descriptor for key in ('urls', 'data', 'artifactType'))):
            raise LabError('unsupported OCI descriptor')
        validated_bytes += descriptor['size']
        if validated_bytes > 64 * 1024**3:
            raise LabError('native OCI aggregate blob byte bound reached')
        path = 'blobs/sha256/' + descriptor['digest'][7:]
        fd = open_beneath(layout, '/' + path)
        digest = hashlib.sha256()
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != descriptor['size']:
                raise LabError('OCI blob size/type mismatch')
            while chunk := stream.read(1 << 20):
                commit_remaining(deadline)
                digest.update(chunk)
        if 'sha256:' + digest.hexdigest() != descriptor['digest']:
            raise LabError('OCI blob digest mismatch')
        return decode(small_file(path)) if small else layout / path

    def put(data, media_type):
        digest = hashlib.sha256(data).hexdigest()
        path = layout / 'blobs' / 'sha256' / digest
        if path.exists():
            if small_file('blobs/sha256/' + digest) != data:
                raise LabError('OCI output digest collision')
        else:
            with path.open('xb') as stream:
                stream.write(data)
        return {'mediaType': media_type, 'digest': 'sha256:' + digest, 'size': len(data)}

    def encode(value):
        return json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()

    if decode(small_file('oci-layout')) != {'imageLayoutVersion': '1.0.0'}:
        raise LabError('unsupported OCI layout')
    index = decode(small_file('index.json'))
    manifests = index.get('manifests')
    if (index.get('schemaVersion') != 2 or not isinstance(manifests, list) or len(manifests) != 1
            or 'subject' in index or 'artifactType' in index):
        raise LabError('native OCI export must contain exactly one image')
    manifest = blob(manifests[0], (manifest_type,), small=True)
    if manifest.get('schemaVersion') != 2 or any(key in manifest for key in ('subject', 'artifactType')):
        raise LabError('unsupported native OCI image manifest')
    config = blob(manifest.get('config'), (config_type,), small=True)
    if manifest['config']['digest'] != normalize_image_id(source_id):
        raise LabError('native OCI export config identity differs')
    rootfs = config.get('rootfs')
    layers = manifest.get('layers')
    if (not isinstance(rootfs, dict) or rootfs.get('type') != 'layers'
            or not isinstance(layers, list) or not 0 < len(baseline_layers) < 512
            or len(layers) != len(baseline_layers) + 1
            or not isinstance(rootfs.get('diff_ids'), list)
            or len(rootfs['diff_ids']) != len(layers)
            or rootfs['diff_ids'][:-1] != baseline_layers
            or any(not re.fullmatch(r'sha256:[0-9a-f]{64}', str(value))
                   for value in rootfs['diff_ids'])):
        raise LabError('native OCI export must have exact baseline ancestry and one derived tail')
    layer_paths = [blob(layer, layer_types) for layer in layers]
    tail = layers[-1]
    # Hash the original uncompressed tail too: config identity alone cannot
    # authenticate the relationship between the tar and its declared diff-id.
    original = hashlib.sha256()
    opener = gzip.open if tail['mediaType'].endswith('+gzip') else open
    total = 0
    with opener(layer_paths[-1], 'rb') as stream:
        while chunk := stream.read(1 << 20):
            total += len(chunk)
            commit_remaining(deadline)
            if total > 64 * 1024**3:
                raise LabError('native delta decompression bound reached')
            original.update(chunk)
    if 'sha256:' + original.hexdigest() != rootfs['diff_ids'][-1]:
        raise LabError('native OCI tail diff-id mismatch')
    rewritten = layout / 'entry-delta.tmp'
    with opener(layer_paths[-1], 'rb') as source, rewritten.open('xb') as raw:
        if tail['mediaType'].endswith('+gzip'):
            with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, compresslevel=6) as destination:
                diff_id = rewrite_entry_delta(source, destination, entry_mtimes, deadline)
        else:
            diff_id = rewrite_entry_delta(source, raw, entry_mtimes, deadline)
    digest = hashlib.sha256()
    with rewritten.open('rb') as stream:
        while chunk := stream.read(1 << 20):
            commit_remaining(deadline)
            digest.update(chunk)
    replacement = dict(tail, digest='sha256:' + digest.hexdigest(), size=rewritten.stat().st_size)
    target = layout / 'blobs' / 'sha256' / digest.hexdigest()
    if target.exists():
        blob(replacement, layer_types)
        rewritten.unlink()
    else:
        rewritten.rename(target)
    layers[-1] = replacement
    rootfs['diff_ids'][-1] = diff_id
    manifest['config'] = dict(manifest['config'], **put(encode(config), config_type))
    index['manifests'][0] = dict(manifests[0], **put(encode(manifest), manifest_type))
    annotations = dict(index['manifests'][0].get('annotations') or {})
    annotations['org.opencontainers.image.ref.name'] = 'corrected'
    index['manifests'][0]['annotations'] = annotations
    (layout / 'index.json').write_bytes(encode(index))
    commit_remaining(deadline)
    return manifest['config']['digest']


def require_commit_bytes(arm: str, expected: dict, before: dict, after: dict) -> None:
    for stage, snapshot in (('installed-container', before), ('committed-image', after)):
        mismatches = [path for path, entry in expected.items()
                      if snapshot.get('files', {}).get(path, {}).get('sha256') != entry['sha256']]
        if mismatches:
            raise LabError(f'{arm}-{stage}-payload-mismatch: ' + ', '.join(mismatches[:8]))
    for snapshot in (before, after):
        proof = snapshot.get('full_rootfs') or {}
        if (proof.get('schema_version') != 2 or proof.get('mtime_precision') != 'nearest-second'
                or proof.get('root_mtime_policy') != 'mountpoint-not-an-image-entry'):
            raise LabError(f'{arm}-commit-full-rootfs-proof-format-mismatch')
    if before['full_rootfs'] != after['full_rootfs']:
        raise LabError(f'{arm}-commit-full-rootfs-identity-changed')
    if before.get('file_metadata') != after.get('file_metadata'):
        raise LabError(f'{arm}-commit-rpm-file-metadata-changed')


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
    from mesa_3969_packages import validate_payload_digests

    core = Path(__file__).with_name('mesa_3969.py')
    # Repeat admission in the privileged-effect orchestrator, not a local-input
    # bypass. The only destination is the core-authenticated fetch result.
    bounded_command([sys.executable, core, 'admit', '--runtime'])
    _, owned, _ = bounded_command([sys.executable, core, 'validate-root', '--role', 'runtime'])
    expected = Path(owned.strip())
    if root != expected or root.is_symlink() or root.resolve() != root:
        raise LabError('runtime root differs from admitted owned root')
    check_runtime_path_budget(root, int(os.environ["GITHUB_RUN_ID"]))
    podman = ['sudo', '-n', 'podman', '--storage-opt',
              'overlay.mountopt=nodev,metacopy=off,redirect_dir=off']
    _, store, _ = bounded_command([*podman, 'info', '--format', '{{json .Store}}'])
    storage = json.loads(store)
    driver = storage.get('GraphDriverName', storage.get('graphDriverName'))
    status = storage.get('GraphStatus', storage.get('graphStatus')) or {}
    native = status.get('Native Overlay Diff', status.get('NativeOverlayDiff'))
    if native is not True and not (isinstance(native, str) and native.lower() == 'true'):
        raise LabError('runtime storage requires overlay with Native Overlay Diff=true')
    if driver != 'overlay':
        raise LabError('runtime storage requires overlay with Native Overlay Diff=true')
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
        # Verification precedes hashing in the same offline container: the
        # expected loaded bytes come from the signed transferred RPM payloads.
        _, digests, _ = bounded_command([
            *podman, 'run', '--name', verifier, '--rm', '--label', label,
            '--network=none', '--mount', mount, '--entrypoint=', baseline_id,
            'python3', LIBEXEC / 'mesa_3969_packages.py', 'payload-digests', '--directory', '/run/mesa-3969-inputs',
        ], timeout=600)
        containers.remove(verifier)
        payload = validate_payload_digests(json.loads(digests))
        for arm in ('control', 'candidate'):
            name = f'mesa3969-{os.environ["GITHUB_RUN_ID"]}-{arm}-install'
            tag = f'localhost/mesa3969-{os.environ["GITHUB_RUN_ID"]}:{arm}'
            raw_tag = tag + '-native'
            require_absent(podman, 'container', name)
            require_absent(podman, 'image', tag)
            require_absent(podman, 'image', raw_tag)
            containers.append(name)
            bounded_command([
                *podman, 'create', '--name', name, '--label', label, '--network=none', '--mount', mount,
                '--entrypoint=', baseline_id, 'python3', LIBEXEC / 'mesa_3969_packages.py',
                'install', '--directory', '/run/mesa-3969-inputs', '--arm', arm,
            ])
            require_install_base(stored_metadata(podman, 'container', name), baseline_id)
            bounded_command([*podman, 'start', '--attach', name], timeout=300)
            _, output, _ = bounded_command([*podman, 'inspect', '--format', '{{.State.ExitCode}}', name])
            if output.strip() != '0':
                raise LabError(f'{arm} offline package replacement failed')
            # Keep native ancestry and native file payloads. Only entry mtime
            # serialization in the new tail is replaced with exact PAX ns.
            entry_mtimes = {}
            before = commit_snapshot(podman, 'container', name, sorted(payload[arm]),
                                     entry_mtimes=entry_mtimes)
            raw_resource = {'tag': raw_tag, 'parent': baseline_metadata}
            images.append(raw_resource)
            deadline = time.monotonic() + 1200
            bounded_command([
                *podman, 'commit', '--change', f'LABEL {label}',
                '--change', 'CMD ' + json.dumps(baseline_config.get('Cmd') or []),
                '--change', 'ENTRYPOINT ' + json.dumps(baseline_config.get('Entrypoint') or []),
                name, raw_tag,
            ], timeout=commit_remaining(deadline))
            raw_metadata = stored_metadata(podman, 'image', raw_tag, deadline=deadline)
            raw_image = runtime_image(raw_metadata, baseline_metadata)
            raw_resource['id'] = raw_image
            temporary = Path(tempfile.mkdtemp(prefix=f'{arm}-native-oci-', dir=work))
            layout_error = None
            try:
                layout = temporary / 'layout'
                bounded_command([*podman, 'save', '--format', 'oci-dir', '--output', layout, raw_image],
                                timeout=commit_remaining(deadline))
                corrected_id = rewrite_native_oci(
                    layout, entry_mtimes, baseline_metadata['RootFS']['Layers'], raw_image, deadline)
                installed_resource = {'tag': tag, 'parent': baseline_metadata}
                images.append(installed_resource)
                bounded_command([
                    'sudo', '-n', 'skopeo', 'copy', '--preserve-digests',
                    f'oci:{layout}:corrected', f'containers-storage:{tag}',
                ], timeout=commit_remaining(deadline))
                metadata = stored_metadata(podman, 'image', tag, deadline=deadline)
                image = runtime_image(metadata, baseline_metadata)
                installed_resource['id'] = image
                if image != corrected_id:
                    raise LabError('loaded corrected OCI image identity differs')
                commit_remaining(deadline)
            except BaseException as error:
                layout_error = error
                raise
            finally:
                try:
                    shutil.rmtree(temporary)
                except OSError as error:
                    PROCESS_CLEANUP_ERRORS.append(sanitize_text(str(error))[:2048])
                    if layout_error is None:
                        raise
            entry_mtimes.clear()
            commit_remaining(deadline)
            after = commit_snapshot(podman, 'image', image, sorted(payload[arm]))
            provenance = {'storage': storage, 'installed_container': before,
                          'committed_image': dict(after, image=image)}
            selected = work / 'selected' / arm
            selected.mkdir(parents=True, exist_ok=True)
            write_json(selected / 'report.json', {'arm': arm, 'rpm_payload': payload, 'provenance': provenance})
            require_commit_bytes(arm, payload[arm], before, after)
            bounded_command([*podman, 'rm', name])
            containers.remove(name)
            vm_name = runtime_vm_name(int(os.environ["GITHUB_RUN_ID"]), arm)
            derived_tag = f'localhost/corral-vmtest/{vm_name}:latest'
            require_absent(podman, 'image', derived_tag)
            derived.append({
                'tag': derived_tag, 'parent': metadata, 'name': vm_name,
                'result': work / arm / 'gate/corral/result.json',
            })
            reports[arm] = run_arm(arm, image, root, gate, baseline, corral, derived[-1], payload, provenance)
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
                # Container commands take the raw hex ID, not sha256: notation.
                bounded_command([*podman, 'container', 'rm', '--force', normalize_image_id(metadata['Id']).removeprefix('sha256:')])
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
    barrier = commands.add_parser('teardown-barrier', help='the gate EXIT-trap delete, after the observer')
    barrier.add_argument('--state', type=Path, required=True)
    barrier.add_argument('--corral', required=True)
    barrier.add_argument('corral_args', nargs=argparse.REMAINDER)
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
        if args.command == 'teardown-barrier':
            corral_args = args.corral_args[1:] if args.corral_args[:1] == ['--'] else args.corral_args
            return teardown_barrier(args.state, args.corral, corral_args)
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
