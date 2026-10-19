#!/usr/bin/env python3
"""Cold, local-only QEMU lifecycle for disposable installation proof disks."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import stat
import subprocess
import time


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DISK = load('qualify-fork-disk')
LOGIN = load('qualify-fork-login')
FIRMWARE = (
    ('/usr/share/OVMF/OVMF_CODE_4M.fd', '/usr/share/OVMF/OVMF_VARS_4M.fd'),
    ('/usr/share/OVMF/OVMF_CODE.fd', '/usr/share/OVMF/OVMF_VARS.fd'),
    ('/usr/share/qemu/edk2-x86_64-code.fd', '/usr/share/qemu/edk2-i386-vars.fd'),
    ('/usr/share/edk2/ovmf/OVMF_CODE.fd', '/usr/share/edk2/ovmf/OVMF_VARS.fd'),
)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def private_directory(path):
    path, info = DISK.checked_stat(str(path), 'private directory', directory=True)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('private directory must be owned with mode 0700')
    return path


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=60).stdout


def create_target(private):
    private = private_directory(private)
    target = private / 'install-target.qcow2'
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    initial = os.fstat(fd)
    os.close(fd)
    receipt = {'method': 'exclusive-new-file', 'path': str(target),
               'device': initial.st_dev, 'inode': initial.st_ino}
    run(['qemu-img', 'create', '-f', 'qcow2', str(target), str(DISK.TARGET_BYTES)])
    current = target.lstat()
    if (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino):
        raise ValueError('qemu-img replaced the exclusively created target')
    DISK.validate_image_info(json.loads(run(['qemu-img', 'info', '--output=json', str(target)])), str(target))
    return target, receipt


class VM:
    def __init__(self, private, phase, source, target, ssh_port=None, memory='8G', *, target_creation):
        self.private = private_directory(private)
        if phase not in ('source', 'target') or (source is None) != (phase == 'target'):
            raise ValueError('phase and source presence disagree')
        if memory != '8G' or (ssh_port is not None and (phase != 'source' or type(ssh_port) is not int or not 1024 <= ssh_port <= 65535)):
            raise ValueError('unsupported memory or forwarding request')
        target_path, target_stat = DISK.checked_stat(str(target), 'target')
        if target_path.parent != self.private or target_stat.st_mode & 0o077:
            raise ValueError('target must be a private direct child of the run directory')
        if target_creation != {'method': 'exclusive-new-file', 'path': str(target_path),
                               'device': target_stat.st_dev, 'inode': target_stat.st_ino}:
            raise ValueError('target exclusive-creation receipt does not match')
        if any(c in str(self.private) for c in ',:') or len(str(self.private / 'vm-target/qmp.sock').encode()) >= 108:
            raise ValueError('private path is unsafe for QEMU socket and file options')
        self.forced = False
        self.phase = phase
        self.directory = self.private / ('vm-' + phase)
        self.directory.mkdir(mode=0o700)
        self.qmp_path = self.directory / 'qmp.sock'
        self.serial_path = self.directory / 'serial.log'
        self.observer_path = self.directory / 'observer.jsonl'
        self.process = None
        self.log = None
        self.ssh_port = ssh_port
        self.receipt = {'phase': phase, 'network': 'none' if source is None else 'restricted-loopback-ssh', 'memory': memory}
        self.identities = {}
        self.source_spec = self.spec(source, 'source') if source is not None else None
        self.target_spec = self.spec(target, 'target')
        if self.source_spec and self.source_spec['path'] == self.target_spec['path']:
            raise ValueError('source and target must differ')
        self.qmp = LOGIN.QMP(self.qmp_path)

    def spec(self, path, role):
        path, info = DISK.checked_stat(str(path), role)
        if info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError('disk ownership or hard-link identity is unsafe')
        identity = (info.st_dev, info.st_ino)
        if identity in self.identities.values():
            raise ValueError('source and target alias the same inode')
        self.identities[str(path)] = identity
        image = json.loads(run(['qemu-img', 'info', '--output=json', str(path)]))
        DISK.validate_image_info(image, str(path), expected_size=DISK.TARGET_BYTES if role == 'target' else None)
        return {'path': str(path), 'node_name': role + '-node',
                'qdev': '/machine/peripheral/' + role + '-disk/virtio-backend',
                'serial': 'fork-' + role + '-' + secrets.token_hex(3)}

    def check_identities(self):
        for path, identity in self.identities.items():
            _, info = DISK.checked_stat(path, 'disk')
            if (info.st_dev, info.st_ino) != identity or info.st_nlink != 1:
                raise ValueError('disk changed since lifecycle admission')

    def command(self):
        code, template = next(((Path(c), Path(v)) for c, v in FIRMWARE if Path(c).is_file() and Path(v).is_file()), (None, None))
        if code is None:
            raise ValueError('installed OVMF firmware pair is unavailable')
        variables = self.directory / 'uefi-vars.fd'
        with template.open('rb') as src, variables.open('xb') as dst:
            shutil.copyfileobj(src, dst)
        variables.chmod(0o600)
        self.firmware = {'firmware-code': str(code), 'firmware-vars': str(variables)}
        self.receipt['firmware'] = {'code': str(code), 'code_sha256': digest(code), 'template_sha256': digest(template)}
        accelerator = 'kvm' if os.access('/dev/kvm', os.R_OK | os.W_OK) else 'tcg'
        args = ['qemu-system-x86_64', '-machine', 'q35,accel=' + accelerator,
                '-cpu', 'host' if accelerator == 'kvm' else 'max', '-smp', '4', '-m', '8G',
                '-nodefaults', '-no-reboot', '-display', 'none', '-vga', 'virtio',
                '-qmp', 'unix:' + str(self.qmp_path) + ',server=on,wait=off',
                '-chardev', 'file,id=serial0,path=' + str(self.serial_path), '-serial', 'chardev:serial0',
                '-chardev', 'file,id=fork-observer,path=' + str(self.observer_path),
                '-device', 'virtio-serial-pci,id=fork-observer-controller',
                '-device', 'virtserialport,bus=fork-observer-controller.0,chardev=fork-observer,name=org.tunaos.fork-observer',
                '-device', 'qemu-xhci,id=xhci', '-device', 'usb-tablet,bus=xhci.0', '-device', 'virtio-rng-pci']
        for name, path in self.firmware.items():
            args += ['-drive', 'if=pflash,format=raw,id=' + name + ',readonly=' + ('on' if name == 'firmware-code' else 'off') + ',file=' + path]
        for index, spec in enumerate(filter(None, (self.source_spec, self.target_spec))):
            node = {'driver': 'qcow2', 'backing': None, 'node-name': spec['node_name'], 'file': {'driver': 'file', 'filename': spec['path']}}
            role = 'source' if spec is self.source_spec else 'target'
            args += ['-blockdev', json.dumps(node), '-device',
                     f"virtio-blk-pci,id={role}-disk,drive={spec['node_name']},serial={spec['serial']},bootindex={index+1}"]
        if self.source_spec:
            if self.ssh_port is None:
                raise ValueError('source requires explicit loopback SSH forwarding')
            args += ['-netdev', f'user,id=net0,restrict=on,hostfwd=tcp:127.0.0.1:{self.ssh_port}-:22',
                     '-device', 'virtio-net-pci,netdev=net0']
        else:
            args += ['-nic', 'none']
        self.receipt['observer_channel'] = {'transport': 'virtio-serial', 'port': 'org.tunaos.fork-observer', 'shared_with_console': False}
        self.receipt['accelerator'] = accelerator
        return args

    def start(self):
        if self.process is not None:
            raise ValueError('VM lifecycle cannot be restarted')
        self.check_identities()
        for spec in filter(None, (self.source_spec, self.target_spec)):
            info = json.loads(run(['qemu-img', 'info', '--output=json', spec['path']]))
            DISK.validate_image_info(info, spec['path'], expected_size=DISK.TARGET_BYTES if spec is self.target_spec else None)
        self.receipt['disk_sha256_before'] = {path: digest(path) for path in self.identities}
        args = self.command()
        # Both character backends stay inside the exclusive private VM directory.
        # Their separate files prevent kernel/getty readiness output from corrupting JSON.
        for path in (self.serial_path, self.observer_path):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        self.log = (self.directory / 'qemu.log').open('xb')
        self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, start_new_session=True)
        self.receipt['pid'] = self.process.pid
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ValueError('QEMU exited before monitor readiness')
            if self.qmp_path.exists():
                try:
                    self.qmp.execute('query-status')
                    return self
                except (OSError, ValueError):
                    pass
            time.sleep(.2)
        raise TimeoutError('QEMU monitor did not become ready')

    def disk_evidence(self):
        raw = self.qmp.execute('query-block')
        disks = []
        firmware = []
        for block in raw:
            name = block.get('device')
            if name in self.firmware:
                if any(item.get('device') == name for item in firmware):
                    raise ValueError('duplicate firmware device')
                inserted = block.get('inserted', {})
                if inserted.get('file') != self.firmware[name] or inserted.get('drv') != 'raw':
                    raise ValueError('firmware block mapping changed')
                if name == 'firmware-code' and inserted.get('ro') is not True:
                    raise ValueError('firmware code is writable')
                firmware.append(block)
            else:
                disks.append(block)
        if {item.get('device') for item in firmware} != set(self.firmware):
            raise ValueError('firmware block mapping is incomplete')
        specs = list(filter(None, (self.source_spec, self.target_spec)))
        serials = [{'path': s['qdev'], 'property': 'serial', 'response': {'return': self.qmp.execute('qom-get', {'path': s['qdev'], 'property': 'serial'})}} for s in specs]
        return {'query_block': {'return': disks}, 'serial_queries': serials, 'raw_query_block': raw, 'firmware_blocks': firmware}

    def screenshot(self, path):
        from PIL import Image
        path = Path(path)
        temporary = self.directory / ('screen-' + secrets.token_hex(4) + '.ppm')
        self.qmp.execute('screendump', {'filename': str(temporary)})
        try:
            with Image.open(temporary) as image:
                image.save(path, format='PNG')
        finally:
            temporary.unlink(missing_ok=True)

    def stop(self, clean=True):
        if self.process is None or self.forced:
            raise ValueError('VM was not started or was forcibly cleaned up')
        if self.process.poll() is not None:
            raise RuntimeError('VM exited without an observed clean guest shutdown')
        guest_shutdown = False
        sock = socket.socket(socket.AF_UNIX)
        stream = None
        try:
            sock.settimeout(120)
            sock.connect(str(self.qmp_path))
            stream = sock.makefile('rwb', buffering=0)
            if 'QMP' not in json.loads(stream.readline()):
                raise ValueError('QMP greeting missing during shutdown')
            LOGIN.QMP.exchange(stream, 'qmp_capabilities')
            stream.write(b'{"execute":"system_powerdown"}\n')
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                sock.settimeout(max(.1, deadline - time.monotonic()))
                line = stream.readline()
                if not line:
                    break
                event = json.loads(line)
                if 'error' in event:
                    raise RuntimeError('QMP powerdown request failed')
                if event.get('event') == 'SHUTDOWN':
                    data = event.get('data', {})
                    guest_shutdown = data.get('guest') is True and data.get('reason') == 'guest-shutdown'
                    self.receipt['shutdown_event'] = data
                    break
            self.process.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            if not clean:
                self.close()
                return
            raise RuntimeError('guest did not shut down cleanly; proof is invalid') from None
        finally:
            if stream is not None:
                stream.close()
            sock.close()
        if not guest_shutdown or self.process.returncode != 0:
            raise RuntimeError('clean guest shutdown event and successful exit are required')
        self.check_identities()
        self.receipt['disk_sha256_after'] = {path: digest(path) for path in self.identities}
        self.receipt['clean_exit'] = True
        if self.log:
            self.log.close()
        self.diagnostics()

    def diagnostics(self):
        # This stream is QEMU's own stderr; guest serial has a separate file.
        # The fixed argv carries no account material or external credentials.
        path = self.directory / 'qemu.log'
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 8192))
                self.receipt['qemu_stderr_tail'] = stream.read(8192).decode('utf-8', errors='replace')

    def close(self):
        self.forced = True
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)
        if self.log:
            self.log.close()
        self.diagnostics()
