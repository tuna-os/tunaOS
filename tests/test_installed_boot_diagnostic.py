"""Inert metadata/process fixtures only: never launch a VM or inspect a disk."""
import gzip
import importlib.util
import json
import lzma
import os
from pathlib import Path
import signal
import stat
import struct
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from lib import installed_boot_diagnostic as d
spec = importlib.util.spec_from_file_location('diagnostic_supervisor', ROOT / 'scripts/diagnose-installed-luks.py')
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


@pytest.fixture(autouse=True)
def no_runtime(monkeypatch):
    monkeypatch.setattr(supervisor, 'OWNED_SERVICES', [])
    def forbidden(*args, **kwargs):
        pytest.fail('runtime operation attempted')
    monkeypatch.setattr(supervisor.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(supervisor.subprocess, 'run', forbidden)
    monkeypatch.setattr(supervisor.os, 'killpg', forbidden)
    monkeypatch.setattr(supervisor.signal, 'pidfd_send_signal', forbidden, raising=False)
    monkeypatch.setattr(supervisor.os, 'pidfd_open', forbidden, raising=False)


def cpio(name, content=b'fixture', mode=stat.S_IFREG | 0o644):
    encoded = name.encode() + b'\0'
    fields = [1, mode, 0, 0, 1, 0, len(content), 0, 0, 0, 0, len(encoded), 0]
    raw = b'070701' + b''.join(f'{v:08x}'.encode() for v in fields) + encoded
    raw += b'\0' * (-len(raw) % 4)
    raw += content
    return raw + b'\0' * (-len(raw) % 4)


@pytest.mark.parametrize('compress', [lambda b:b, gzip.compress, lzma.compress])
def test_multisegment_archive_only_reports_public_components(compress):
    early = cpio('kernel/x86/microcode/GenuineIntel.bin') + cpio('TRAILER!!!', b'')
    source = cpio('usr/sbin/plymouthd') + cpio('secret.key', b'SECRET-SENTINEL')
    source += cpio('usr/share/plymouth/themes/spinner/spinner.png')
    source += cpio('usr/bin/link', b'../../secret', stat.S_IFLNK | 0o777)
    result = d.archive_metadata(early + compress(source))
    assert result['components']['plymouthd']['sha256'] == d.digest(b'fixture')
    assert result['theme_files'] == 1
    assert result['theme_selection'] == 'unresolved'
    assert result['theme_evidence'] == {
        'theme_file': False, 'script_file': False, 'script_plugin': False,
        'label_plugin': False, 'font': False}
    assert result['module_initialization'] == 'not_observed'
    assert 'SECRET' not in json.dumps(result) and 'secret.key' not in json.dumps(result)


def test_el10_initramfs_evidence_scales_with_realistic_archive():
    module_root = 'usr/lib/modules/6.12.0-278.el10.x86_64/'
    entries = [
        cpio(module_root + 'modules.builtin',
             b'kernel/drivers/gpu/drm/sysfb/simpledrm.ko\nkernel/drivers/gpu/drm/drm.ko\n'),
        cpio(module_root + 'modules.dep',
             b'kernel/drivers/gpu/drm/virtio/virtio-gpu.ko.xz: kernel/drivers/virtio/virtio_dma_buf.ko.xz\n'),
        cpio(module_root + 'kernel/drivers/gpu/drm/virtio/virtio-gpu.ko.xz'),
        cpio('usr/lib/dracut/modules.txt', b'plymouth crypt drm ostree\n'),
        cpio('usr/lib/dracut/build-parameter.txt', b'--zstd\n'),
        cpio('etc/plymouth/plymouthd.conf', b'[Daemon]\nTheme=spinner\n'),
        cpio('usr/share/plymouth/plymouthd.defaults', b'[Daemon]\nTheme=other\n'),
        cpio('usr/share/plymouth/themes/spinner/spinner.plymouth',
             b'[Plymouth Theme]\nModuleName=script\nScriptFile=/usr/share/plymouth/themes/spinner/spinner.script\n'),
        cpio('usr/share/plymouth/themes/spinner/spinner.script', b'Image.Text("password")\n'),
        cpio('usr/lib64/plymouth/script.so'), cpio('usr/lib64/plymouth/label.so'),
        cpio('usr/share/fonts/dejavu/DejaVuSans.ttf'),
        cpio('usr/lib/systemd/system/systemd-ask-password-plymouth.path'),
        cpio('usr/lib/systemd/system/systemd-ask-password-plymouth.service'),
        cpio('usr/bin/systemd-tty-ask-password-agent'),
    ]
    entries.extend(cpio(f'usr/share/empty/{index:04d}.dat', bytes([index % 251]) * 8192)
                   for index in range(3081))
    decoded = b''.join(entries)
    assert len(decoded) > 24 * d.MIB
    import zstandard
    archive = zstandard.ZstdCompressor(write_checksum=True).compress(decoded)
    result = d.archive_metadata(archive, deadline=time.monotonic() + 8)
    assert result['drivers'] == {
        'virtio_gpu': 'module_in_initramfs', 'simpledrm': 'builtin', 'drm': 'builtin'}
    assert result['dracut_modules'] == ['crypt', 'drm', 'ostree', 'plymouth']
    assert result['dracut_build_parameters_sha256'] == d.digest(b'--zstd\n')
    assert result['theme_selection'] == 'spinner'
    assert all(result['theme_evidence'].values())

    assert set(result['components']) >= {
        'password_agent', 'ask_password_plymouth_path', 'ask_password_plymouth_service'}

    started = time.monotonic()
    entries = b''.join(cpio(f'usr/share/empty/{index:04d}.dat') for index in range(3095))
    assert len(d.archive_metadata(entries, deadline=time.monotonic() + 8)['components']) == 0
    assert time.monotonic() - started < 8


def test_wrong_basename_theme_definition_is_not_selected():
    entries = [
        cpio('etc/plymouth/plymouthd.conf', b'[Daemon]\nTheme=spinner\n'),
        cpio('usr/share/plymouth/themes/spinner/other.plymouth',
             b'[Plymouth Theme]\nModuleName=script\nScriptFile=/usr/share/plymouth/themes/spinner/spinner.script\n'),
        cpio('usr/share/plymouth/themes/spinner/spinner.script'),
        cpio('usr/lib64/plymouth/script.so'),
    ]
    result = d.archive_metadata(b''.join(entries))
    assert result['theme_selection'] == 'spinner'
    assert not result['theme_evidence']['theme_file']
    assert not result['theme_evidence']['script_plugin']
    assert not result['theme_evidence']['script_file']


@pytest.mark.parametrize('token', [
    'rd.luks.uuid=luks-01234567-89ab-cdef-0123-456789abcdef',
    'rd.luks.name=luks-01234567-89ab-cdef-0123-456789abcdef=cryptroot',
    'rd.luks.options=luks-01234567-89ab-cdef-0123-456789abcdef=discard,no-read-workqueue',
])
def test_supported_luks_options_redact_their_values(token):
    result = d.safe_options(token)
    assert result['safe'] == [token.split('=')[0] + '=<redacted>']
    assert result['redacted_count'] == 0
    assert '01234567' not in json.dumps(result) and 'cryptroot' not in json.dumps(result)


def test_unknown_and_malformed_luks_options_are_redacted():
    result = d.safe_options(
        'rd.luks.SECRET rd.luks.SECRET=value rd.luks.name rd.luks.uuid=SECRET '
        'rd.luks.key=SECRET rd.luks=2')
    assert result['safe'] == []
    assert result['redacted_count'] == 6
    assert 'SECRET' not in json.dumps(result) and 'rd.luks.SECRET' not in json.dumps(result)


@pytest.mark.parametrize('member', [
    'usr/share/plymouth/themes/other/spinner.script',
    'usr/share/plymouth/themes/spinner/spinner.script',
])
def test_theme_script_evidence_requires_exact_regular_member_path(member):
    entries = [
        cpio('etc/plymouth/plymouthd.conf', b'[Daemon]\nTheme=spinner\n'),
        cpio('usr/share/plymouth/themes/spinner/spinner.plymouth',
             b'[Plymouth Theme]\nModuleName=script\nScriptFile=/usr/share/plymouth/themes/spinner/spinner.script\n'),
    ]
    if member.endswith('/spinner.script') and '/other/' in member:
        entries.append(cpio(member, b'not the referenced path'))
    else:
        entries.append(cpio(member, b'../other/spinner.script', stat.S_IFLNK | 0o777))
    result = d.archive_metadata(b''.join(entries))
    assert result['theme_selection'] == 'spinner'
    assert result['theme_evidence']['theme_file']
    assert not result['theme_evidence']['script_file']


def test_driver_absence_is_only_reported_when_module_metadata_exists():
    root = 'usr/lib/modules/6.12.0-278.el10.x86_64/'
    archive = cpio(root + 'modules.builtin',
                   b'kernel/drivers/gpu/drm/sysfb/simpledrm.ko\n')
    archive += cpio(root + 'modules.dep', b'kernel/drivers/misc/example.ko:\n')
    result = d.archive_metadata(archive)
    assert result['drivers'] == {
        'virtio_gpu': 'module_not_in_initramfs',
        'simpledrm': 'builtin',
        'drm': 'module_not_in_initramfs'}


def test_modules_dep_entry_without_cpio_module_is_index_only():
    root = 'usr/lib/modules/6.12.0-278.el10.x86_64/'
    archive = cpio(root + 'modules.dep',
                   b'kernel/drivers/gpu/drm/virtio/virtio-gpu.ko.xz: '
                   b'kernel/drivers/virtio/virtio_dma_buf.ko.xz\n')

    assert d.archive_metadata(archive)['drivers'] == {
        'virtio_gpu': 'index_only',
        'simpledrm': 'module_not_in_initramfs',
        'drm': 'module_not_in_initramfs'}



@pytest.mark.parametrize('blob,reason', [(cpio('../escape'), 'archive_traversal'),
    (cpio('/absolute'), 'archive_traversal'), (b'070701', 'truncated_cpio'),
    (b'unsupported-zstd', 'unsupported_archive_format'),
    (cpio('usr/sbin/plymouthd')*2, 'ambiguous_component')])
def test_archive_fail_closed(blob, reason):
    with pytest.raises(d.Refused, match=reason): d.archive_metadata(blob)


def test_expansion_and_entry_caps(monkeypatch):
    monkeypatch.setattr(d, 'MAX_EXPANDED', 1000)
    with pytest.raises(d.Refused): d.archive_metadata(gzip.compress(b'A'*10000))
    monkeypatch.setattr(d, 'MAX_ENTRIES', 1)
    with pytest.raises(d.Refused, match='entry_limit'): d.archive_metadata(cpio('a')+cpio('b'))


def test_builtin_absent_and_module_are_distinct():
    result = d.kernel_config(b'CONFIG_DRM=y\nCONFIG_DRM_VIRTIO_GPU=m\n# CONFIG_DRM_SIMPLEDRM is not set\n')
    assert result['CONFIG_DRM'] == 'y'
    assert result['CONFIG_DRM_VIRTIO_GPU'] == 'm'
    assert result['CONFIG_DRM_SIMPLEDRM'] == 'n'
    assert result['CONFIG_VIRTIO'] == 'unknown'
    with pytest.raises(d.Refused): d.kernel_config(b'CONFIG_DRM=y\nCONFIG_DRM=m\n')


def test_argument_value_redaction():
    result = d.safe_options(
        'rhgb quiet console=ttyS1,115200n8 console=tty0 console=SECRET drm.debug=0x1e '
        'rd.luks.key=SECRET rd.luks.name=luks-01234567-89ab-cdef-0123-456789abcdef=cryptroot '
        'rd.luks.SECRET rd.luks.SECRET=value systemd.show_status=1 '
        'plymouth.enable=0 rd.plymouth=0 rd.driver.blacklist=nouveau '
        'rd.driver.blacklist=SECRET video=HDMI-A-1:1920x1080 video=SECRET:1920x1080 '
        'vt.global_cursor_default=0 fbcon=nodefer nomodeset splash root=/dev/disk/by-uuid/SECRET')
    assert result['safe'] == [
        'rhgb', 'quiet', 'console=ttyS1,115200n8', 'console=tty0', 'drm.debug=0x1e',
        'rd.luks.name=<redacted>', 'systemd.show_status=1',
        'plymouth.enable=0', 'rd.plymouth=0', 'rd.driver.blacklist=nouveau',
        'video=HDMI-A-1:1920x1080', 'vt.global_cursor_default=0', 'fbcon=nodefer',
        'nomodeset', 'splash', 'root=<redacted>']
    assert result['redacted_count'] == 6
    assert 'SECRET' not in json.dumps(result) and 'cryptroot' not in json.dumps(result)


class Guest:
    def __init__(self, fs='ext4', guid='bc13c2ff-59e6-4262-a352-b275fd6f7172'):
        self.fs, self.guid, self.calls, self.links = fs, guid, [], set()
        self.link_targets = {}
        self.directories = {'/loader', '/loader/entries'}
        self.labels = {'/dev/sda1': 'EFI', '/dev/sda3': 'boot'}
        self.files = {'/loader/entries/test.conf': b'linux /vmlinuz-6.12.0-278.el10.x86_64\ninitrd /initramfs-6.12.0-278.el10.x86_64\noptions quiet secret=HIDDEN\n',
                      '/vmlinuz-6.12.0-278.el10.x86_64': b'kernel',
                      '/initramfs-6.12.0-278.el10.x86_64': cpio('usr/sbin/plymouthd'),
                      '/usr/lib/modules/6.12.0-278.el10.x86_64/config': b'CONFIG_DRM=y\n'}
    def list_filesystems(self): return {'/dev/sda1':'vfat', '/dev/sda2':'crypto_LUKS', '/dev/sda3':self.fs}
    def part_get_gpt_type(self, device, number):
        return 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b' if number==1 else (self.guid if number==3 else 'unknown-root-guid')
    def vfs_label(self, device): return self.labels.get(device)
    def mount_options(self, options, device, root):
        self.device = device
        self.calls.append((options, device, root))
    def umount_all(self): self.calls.append('umount')
    def is_symlink(self, path): return getattr(self,'device',None)=='/dev/sda3' and path in self.links
    def readlink(self, path): return self.link_targets.get(path)
    def is_dir(self, path, **kwargs): return self.device=='/dev/sda3' and path in self.directories
    def ls(self, path): return ['test.conf']
    def is_file(self, path, **kwargs): return path in self.files
    def filesize(self, path): return len(self.files[path])
    def pread(self, path, size, offset): return self.files[path][offset:offset+size]


def test_discovery_skips_empty_esp_and_reads_only_boot_candidate():
    guest = Guest()
    result = d.inspect_boot(guest)
    assert result['selection']=='unresolved' and result['qualified'] is False
    assert result['candidates'][0]['kernel_config']['CONFIG_DRM']=='y'
    assert guest.calls == [('ro','/dev/sda1','/'),'umount',('ro,noload','/dev/sda3','/'),'umount']
    assert 'HIDDEN' not in json.dumps(result)


def test_secret_argument_and_partition_label_are_redacted_in_report():
    guest = Guest()
    guest.files['/loader/entries/test.conf'] = (
        b'linux /vmlinuz-6.12.0-278.el10.x86_64\n'
        b'initrd /initramfs-6.12.0-278.el10.x86_64\n'
        b'options quiet console=SECRET root=SECRET rd.luks.SECRET rd.luks.SECRET=value\n')
    guest.labels['/dev/sda3'] = 'TOKEN_SECRET'

    result = d.inspect_boot(guest)
    serialized = json.dumps(result)

    assert 'SECRET' not in serialized
    assert 'rd.luks.SECRET' not in serialized
    assert result['candidates'][0]['options']['safe'] == ['quiet', 'root=<redacted>']
    assert result['candidates'][0]['options']['redacted_count'] == 3


def test_refusal_report_redacts_untrusted_partition_label(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import resource

    guest = Guest(fs='xfs')
    guest.labels['/dev/sda3'] = 'TOKEN_SECRET'
    guest.version = lambda: {'major': 1, 'minor': 52, 'release': 0}
    guest.set_backend = lambda *args: None
    guest.set_network = lambda *args: None
    guest.set_memsize = lambda *args: None
    guest.set_smp = lambda *args: None
    guest.add_drive_opts = lambda *args, **kwargs: None
    guest.launch = lambda: None
    guest.close = lambda: None
    monkeypatch.setitem(sys.modules, 'guestfs', SimpleNamespace(GuestFS=lambda **kwargs: guest))
    monkeypatch.setattr(resource, 'setrlimit', lambda *args: None)
    target = tmp_path/'report.json'
    with pytest.raises(d.Refused, match='encrypted_or_unsupported_boot'):
        supervisor.worker(tmp_path/'disk.qcow2', target, '1.52.0')

    report = json.loads(target.read_text())
    assert 'TOKEN_SECRET' not in json.dumps(report)
    assert report['partitions'][-1]['label'] == '<redacted>'


def test_ostree_loader_symlink_reads_only_validated_slot_directory():
    guest = Guest()
    guest.links.add('/loader')
    guest.link_targets['/loader'] = 'loader.0'
    guest.directories = {'/loader.0', '/loader.0/entries'}
    entry = guest.files.pop('/loader/entries/test.conf')
    guest.files['/loader.0/loader.conf'] = b'default test\n'
    guest.files['/loader.0/entries/test.conf'] = entry

    result = d.inspect_boot(guest)

    assert result['selection'] == 'configured_default_not_runtime_observed'
    assert result['boot_metadata'][0]['kind'] == 'loader_config'
    assert result['selected_entry_sha256'] == d.digest(entry)
    assert guest.calls == [('ro','/dev/sda1','/'),'umount',('ro,noload','/dev/sda3','/'),'umount']


@pytest.mark.parametrize('target', ['loader.2', '../loader.0', '/loader.0', 'loader.0/entries'])
def test_loader_symlink_rejects_any_noncanonical_target(target):
    guest = Guest()
    guest.links.add('/loader')
    guest.link_targets['/loader'] = target
    with pytest.raises(d.Refused, match='guest_symlink'):
        d.inspect_boot(guest)


@pytest.mark.parametrize('fs,guid', [('crypto_LUKS','bc13c2ff-59e6-4262-a352-b275fd6f7172'),
    ('xfs','bc13c2ff-59e6-4262-a352-b275fd6f7172'),('ext4','unknown-root-guid')])
def test_encrypted_unknown_and_root_layouts_fail_closed(fs,guid):
    guest=Guest(fs,guid)
    with pytest.raises(d.Refused): d.inspect_boot(guest)
    assert not any(isinstance(c,tuple) and c[1]=='/dev/sda3' for c in guest.calls)


def test_unsupported_layout_refusal_keeps_partition_only_facts():
    with pytest.raises(d.Refused, match='encrypted_or_unsupported_boot') as error:
        d.inspect_boot(Guest(fs='xfs'))
    assert error.value.details['partitions'][-1] == {
        'index': 3, 'gpt_type_guid': 'bc13c2ff-59e6-4262-a352-b275fd6f7172',
        'filesystem': 'xfs', 'label': 'boot'}


@pytest.mark.parametrize('path', ['/loader','/loader/entries/test.conf',
    '/initramfs-6.12.0-278.el10.x86_64'])
def test_guest_links_never_followed(path):
    guest=Guest(); guest.links.add(path)
    with pytest.raises(d.Refused,match='guest_symlink'): d.inspect_boot(guest)


def test_uki_is_explicitly_unsupported():
    guest=Guest(); guest.files['/loader/entries/test.conf']=b'efi /EFI/Linux/uki.efi\n'
    with pytest.raises(d.Refused,match='unsupported_boot_entry'): d.inspect_boot(guest)


def qcow():
    data=bytearray(104);data[:4]=b'QFI\xfb';struct.pack_into('>I',data,4,3)
    struct.pack_into('>Q',data,24,64*1024**3)
    return data


def test_only_owned_regular_files(tmp_path):
    path=tmp_path/'owned';path.write_bytes(qcow())
    assert d.regular(path,tmp_path)[2]==104
    d.qcow_header(path)
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(d.Refused): d.regular(link,tmp_path)
    os.link(path,tmp_path/'hardlink')
    with pytest.raises(d.Refused): d.regular(path,tmp_path)


@pytest.mark.parametrize('offset,fmt,value', [(8,'>Q',1),(72,'>Q',4),(32,'>I',1),(24,'>Q',65*1024**3)])
def test_backing_external_encrypted_and_oversized_refused(tmp_path,offset,fmt,value):
    path=tmp_path/'fixture';data=qcow();struct.pack_into(fmt,data,offset,value);path.write_bytes(data)
    with pytest.raises(d.Refused):d.qcow_header(path)


class Child:
    def __init__(self):
        self.waited=False; self.alive=False; self.pid=123; self.signals=[]
    def wait(self,timeout): self.waited=True
    def poll(self): return None if self.alive else 0
    def stop(self): self.waited=True; return not self.alive
    def send_signal(self,number): self.signals.append(number)
    def proof(self): return {'stopped':self.waited}


def test_stop_uses_retained_handle_not_reused_pid(monkeypatch,tmp_path):
    child=Child();owner=supervisor.OwnedQemu('/not-executed',tmp_path);owner.children=[child]
    events=[]
    monkeypatch.setattr(supervisor.select,'select',lambda *args: ([101],[],[]))
    monkeypatch.setattr(supervisor.os,'close',lambda fd:events.append(fd))
    assert owner.stop()=={'method':'owned-systemd-invocation-cgroup','exited_children':1,'services':[{'stopped':True}]}
    assert child.waited and owner.stopped
    with pytest.raises(d.Refused):owner.launch([])


def test_alive_process_blocks_collection(monkeypatch,tmp_path):
    child=Child();child.alive=True
    owner=supervisor.OwnedQemu('/none',tmp_path);owner.children=[child]
    with pytest.raises(d.Refused,match='qemu_stop_unproven'):owner.stop()


def test_no_owner_cannot_claim_stop(tmp_path):
    with pytest.raises(d.Refused,match='no_supervised_vm'):supervisor.OwnedQemu('/none',tmp_path).stop()


def test_report_upload_allowlist_and_limits(tmp_path,monkeypatch):
    target=tmp_path/'out'
    d.write_report(target,{'qualified':False,'strict_exit':3,'collection':'not_collected'})
    assert sorted(p.name for p in target.iterdir())==['manifest.json','report.json']
    manifest=json.loads((target/'manifest.json').read_bytes())
    assert manifest['files'][0]['sha256']==d.digest((target/'report.json').read_bytes())
    monkeypatch.setattr(d,'MAX_REPORT',10)
    with pytest.raises(d.Refused):d.write_report(tmp_path/'large',{'large':'x'*100})


def test_default_harness_does_not_enable_diagnostic():
    source=(ROOT/'scripts/iso-e2e.sh').read_text()
    assert '${TUNAOS_INSTALLED_BOOT_DIAGNOSTIC:-0}' in source
    assert 'strict qualification refuses per-boot GRUB argument overrides' in source
    assert 'NativeISOQualification/v2' in (ROOT/'scripts/native-iso-qualification.py').read_text()


def test_stop_exception_does_not_skip_other_children(monkeypatch,tmp_path):
    owner=supervisor.OwnedQemu('/none',tmp_path)
    first,second=Child(),Child();owner.children=[first,second]
    def fail(): raise OSError('fixture')
    first.stop=fail
    with pytest.raises(d.Refused,match='qemu_stop_unproven'):owner.stop()
    assert second.waited and owner.closed and not owner.stopped


def test_reaper_removes_only_exact_owned_pidfile(monkeypatch,tmp_path):
    child=Child();child.pid=123
    owner=supervisor.OwnedQemu('/none',tmp_path);owner.children=[child]
    pidfile=tmp_path/'qemu.pid';pidfile.write_text('999')
    monkeypatch.setattr(supervisor.select,'select',lambda *args:([101],[],[]))
    owner.reap()
    assert pidfile.read_text()=='999' and child.waited
    pidfile.write_text('123');owner.reap();assert not pidfile.exists()


def test_interrupt_handler_requests_cleanup_without_signalling_anything():
    with pytest.raises(InterruptedError):supervisor.interrupted(signal.SIGTERM,None)
    with pytest.raises(InterruptedError):supervisor.interrupted(signal.SIGINT,None)


def test_hash_deadline_and_input_cap(tmp_path):
    path=tmp_path/'ordinary';path.write_bytes(b'fixture')
    with pytest.raises(d.Refused,match='hash_timeout'):supervisor.file_digest(path,0)
    path.write_bytes(b'x'*(d.MIB+1))
    with pytest.raises(d.Refused,match='input_limit'):supervisor.read_json(path)


def test_current_run_binding_cannot_be_replayed():
    p={'repository':'tuna-os/tunaOS','run':7,'attempt':1}
    env={'GITHUB_REPOSITORY':'tuna-os/tunaOS','GITHUB_RUN_ID':'7','GITHUB_RUN_ATTEMPT':'1'}
    supervisor.validate_run(p,env)
    for key in env:
        with pytest.raises(d.Refused):supervisor.validate_run(p,{**env,key:'wrong'})


def test_no_encrypted_container_is_not_luks_diagnostic():
    guest=Guest();guest.list_filesystems=lambda:{'/dev/sda3':'ext4'}
    with pytest.raises(d.Refused,match='luks_not_observed'):d.inspect_boot(guest)
    assert not guest.calls


def test_bounded_reads_use_chunks_not_large_rpc():
    guest=Guest();guest.files['/large']=b'a'*300000
    original=guest.pread;sizes=[]
    def pread(path,size,offset):
        sizes.append(size);return original(path,size,offset)
    guest.pread=pread
    assert len(d.guest_regular(guest,'/large',400000))==300000
    assert max(sizes)<=128*1024 and len(sizes)==3


def test_config_and_efi_metadata_never_emits_raw_text():
    guest=Guest();guest.files['/grub2/grubenv']=b'saved_entry=SECRET'
    result=d.inspect_boot(guest)
    assert result['boot_metadata'][0]['kind']=='grub_environment'
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('primary,collected,expected',[(0,True,0),(0,False,1),(3,True,3),(3,False,3),(124,False,124)])
def test_diagnostic_failure_never_replaces_primary_failure(primary,collected,expected):
    assert supervisor.final_status(primary,collected)==expected


def test_labelled_linux_boot_requires_no_root_structure():
    guest=Guest(guid='0fc63daf-8483-4772-8e79-3d69d8477de4')
    assert d.inspect_boot(guest)['selection']=='unresolved'
    original=guest.is_dir
    guest.is_dir=lambda path,**kwargs:path=='/etc' or original(path,**kwargs)
    with pytest.raises(d.Refused,match='root_layout_refused'):d.inspect_boot(guest)


def test_metadata_names_do_not_become_upload_names():
    guest=Guest();guest.ls=lambda path:['../../SECRET.conf']
    with pytest.raises(d.Refused,match='unknown_entry_name'):d.inspect_boot(guest)


def test_partial_archive_is_not_success():
    with pytest.raises(d.Refused):d.archive_metadata(gzip.compress(cpio('usr/sbin/plymouthd'))[:-4])


def test_dead_owned_pid_cannot_signal_recycled_numeric_pid(monkeypatch,tmp_path):
    child=Child();child.pid=123
    owner=supervisor.OwnedQemu('/none',tmp_path);owner.children=[child]
    monkeypatch.setattr(supervisor.select,'select',lambda *args:([101],[],[]))
    assert owner.signal_owned(15,123)==1
    assert owner.signal_owned(0,123)==1
    assert owner.signal_owned(15,999)==64


def test_live_owned_pid_signals_only_owned_unit(tmp_path):
    child=Child();child.alive=True
    owner=supervisor.OwnedQemu('/none',tmp_path);owner.children=[child]
    assert owner.signal_owned(0,123)==0 and child.signals==[]
    assert owner.signal_owned(15,123)==0 and child.signals==[15]


def test_next_launch_refuses_live_previous_vm(tmp_path):
    child=Child();child.alive=True
    owner=supervisor.OwnedQemu('/none',tmp_path);owner.children=[child]
    with pytest.raises(d.Refused,match='previous_qemu_alive'):owner.launch(['-daemonize','-pidfile',str(tmp_path/'qemu.pid')])


def test_cleanup_race_is_reaped_and_other_errors_are_explicit(monkeypatch):
    class Running(Child):
        pid=123
        def poll(self): return None
    child=Running()
    def vanished(*args): raise ProcessLookupError('fixture')
    monkeypatch.setattr(supervisor.os,'killpg',vanished)
    assert supervisor.stop_group(child) and child.waited
    def denied(*args): raise PermissionError('fixture')
    monkeypatch.setattr(supervisor.os,'killpg',denied)
    assert supervisor.stop_group(Running()) is False


def test_hash_rejects_links_before_read(tmp_path):
    ordinary=tmp_path/'file';ordinary.write_bytes(b'ordinary')
    link=tmp_path/'link';link.symlink_to(ordinary)
    with pytest.raises(d.Refused,match='hash_symlink'):supervisor.file_digest(link)
    with pytest.raises(d.Refused,match='hash_not_regular'):supervisor.file_digest(tmp_path)


def zstd_frame(raw, **kwargs):
    import zstandard
    return zstandard.ZstdCompressor(write_checksum=True, **kwargs).compress(raw)


def test_zstd_early_cpio_and_concatenated_frames():
    raw = cpio('kernel/x86/microcode/GenuineIntel.bin')
    raw += zstd_frame(cpio('usr/sbin/plymouthd'))
    raw += zstd_frame(cpio('usr/bin/plymouth'))
    result = d.archive_metadata(raw)
    assert set(result['components']) == {'plymouthd', 'plymouth'}
    assert result['module_initialization'] == 'not_observed'


@pytest.mark.parametrize('cut', [1, 4, 6, 10, -1, -4])
def test_zstd_truncated(cut):
    with pytest.raises(d.Refused):
        d.archive_metadata(zstd_frame(cpio('usr/sbin/plymouthd'))[:cut])


def test_zstd_checksum_and_reserved_block():
    frame = zstd_frame(cpio('usr/sbin/plymouthd'))
    with pytest.raises(d.Refused, match='invalid_zstd'):
        d.archive_metadata(frame[:-1]+bytes([frame[-1]^1]))
    import zstandard
    offset = zstandard.frame_header_size(frame)
    broken = bytearray(frame)
    broken[offset] |= 6
    with pytest.raises(d.Refused, match='invalid_zstd_block'):
        d.archive_metadata(bytes(broken))


@pytest.mark.parametrize('known_size', [True, False])
def test_zstd_bomb_cap(monkeypatch, known_size):
    frame = zstd_frame(cpio('ignored', b'A'*100000), write_content_size=known_size)
    monkeypatch.setattr(d, 'MAX_EXPANDED', 4096)
    with pytest.raises(d.Refused, match='expanded_or_truncated_archive'):
        d.archive_metadata(frame)


def test_zstd_member_entry_and_deadline_caps(monkeypatch):
    frame = zstd_frame(cpio('TRAILER!!!', b''))
    with pytest.raises(d.Refused, match='compression_member_limit'):
        d.archive_metadata(frame*65)
    monkeypatch.setattr(d, 'MAX_ENTRIES', 1)
    with pytest.raises(d.Refused, match='entry_limit'):
        d.archive_metadata(frame*2)
    with pytest.raises(d.Refused, match='archive_timeout'):
        d.archive_metadata(frame, deadline=0)


def test_zstd_version_and_window_caps(monkeypatch):
    import zstandard
    frame = zstd_frame(cpio('usr/sbin/plymouthd'))
    monkeypatch.setattr(d, 'version', lambda name:'wrong')
    with pytest.raises(d.Refused, match='zstd_version'):
        d.archive_metadata(frame)
    monkeypatch.setattr(d, 'version', lambda name:'0.25.0')
    from types import SimpleNamespace
    monkeypatch.setattr(zstandard, 'get_frame_parameters', lambda b:SimpleNamespace(window_size=65*d.MIB))
    with pytest.raises(d.Refused, match='zstd_window_limit'):
        d.archive_metadata(frame)


def test_zstd_unknown_size_and_mixed_members():
    raw = zstd_frame(cpio('usr/sbin/plymouthd'), write_content_size=False)
    raw += gzip.compress(cpio('usr/bin/plymouth'))
    assert len(d.archive_metadata(raw)['components']) == 2
    with pytest.raises(d.Refused, match='truncated_zstd'):
        d.archive_metadata(raw + b'\x28\xb5\x2f\xfd\x00\x00')


def test_zstd_stream_deadline(monkeypatch):
    frame = zstd_frame(cpio('usr/sbin/plymouthd'))
    clock = iter([0, 0, 2])
    monkeypatch.setattr(d.time, 'monotonic', lambda:next(clock, 2))
    with pytest.raises(d.Refused, match='archive_timeout'):
        d.archive_metadata(frame, deadline=1)


def test_exited_leader_is_not_group_exit(monkeypatch):
    from types import SimpleNamespace
    child = SimpleNamespace(pid=12345, poll=lambda:0)
    probes=[]
    monkeypatch.setattr(supervisor.os, 'killpg', lambda pid,sig:probes.append((pid,sig)))
    assert supervisor.stop_group(child) is False
    assert probes == [(12345,0)]
    def absent(pid,sig):
        assert sig == 0
        raise ProcessLookupError()
    monkeypatch.setattr(supervisor.os, 'killpg', absent)
    assert supervisor.stop_group(child) is True


@pytest.mark.parametrize('state,populated,expected', [(b'inactive',0,True),(b'failed',0,True),(b'active',0,False),(b'inactive',1,False)])
def test_service_requires_cgroup_closure(tmp_path, monkeypatch, state, populated, expected):
    from types import SimpleNamespace
    item=supervisor.ContainedProcess.__new__(supervisor.ContainedProcess)
    item.unit='fixture.service';item.invocation='a'*32;item.stopped=False;item.stop_attempted=False
    item.cgroup=tmp_path/'service';item.cgroup.mkdir()
    (item.cgroup/'cgroup.events').write_text(f'populated {populated}\n')
    calls=[]
    item.info=lambda **kwargs:{'ActiveState':state.decode(),'InvocationID':item.invocation,'LoadState':'loaded'}
    def run(argv,**kwargs):
        calls.append(argv);return SimpleNamespace(returncode=0)
    monkeypatch.setattr(supervisor.subprocess,'run',run)
    assert supervisor.stop_group(item) is expected
    assert calls[0]==['sudo','-n','systemctl','stop','fixture.service']


def test_service_launch_is_non_delegated_and_bounded(tmp_path,monkeypatch):
    from types import SimpleNamespace
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv);return SimpleNamespace(returncode=0)
    def info(self,**kwargs):
        return {'User':str(os.getuid()),'Delegate':'no','KillMode':'control-group',
                'Restart':'no','RemainAfterExit':'yes','InvocationID':'a'*32,
                'ControlGroup':'/system.slice/'+self.unit,'MainPID':'12345',
                'SupplementaryGroups':'kvm'}
    monkeypatch.setattr(supervisor.subprocess,'run',run)
    monkeypatch.setattr(supervisor.ContainedProcess,'info',info)
    monkeypatch.setattr(supervisor.Path,'is_file',lambda path:True)
    supervisor.ContainedProcess(['fixture-command'],env={'LANG':'C'},supplementary_groups=('kvm',))
    command=calls[0]
    assert '--property=KillMode=control-group' in command
    assert '--property=RuntimeMaxSec=3700' in command and '--remain-after-exit' in command
    assert '--property=Delegate=no' in command and '--property=NoNewPrivileges=yes' in command
    assert '--property=SupplementaryGroups=kvm' in command
    assert command[-2:]==['--','fixture-command']


def test_inspector_memory_limit_and_oom_failure_cleanup(tmp_path, monkeypatch):
    from types import SimpleNamespace
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0)
    def info(self, **kwargs):
        return {'User':str(os.getuid()),'Delegate':'no','KillMode':'control-group',
                'Restart':'no','RemainAfterExit':'yes','InvocationID':'a'*32,
                'ControlGroup':'/system.slice/'+self.unit,'MainPID':'12345'}
    monkeypatch.setattr(supervisor.subprocess, 'run', run)
    monkeypatch.setattr(supervisor.ContainedProcess, 'info', info)
    monkeypatch.setattr(supervisor.Path, 'is_file', lambda path: True)
    monkeypatch.setattr(supervisor.Path, 'read_text', lambda path: str(4*1024**3))
    supervisor.ContainedProcess(['fixture'], memory_max=4*1024**3)
    assert '--property=MemoryMax=4294967296' in calls[0]
    supervisor.OWNED_SERVICES.clear()
    monkeypatch.undo()

    cgroup = tmp_path/'service'
    cgroup.mkdir()
    (cgroup/'memory.events').write_text('low 0\nhigh 0\nmax 0\noom 1\noom_kill 1\noom_group_kill 0\n')
    item = supervisor.ContainedProcess.__new__(supervisor.ContainedProcess)
    item.memory_max = 4*1024**3
    item.cgroup = cgroup
    stopped = []
    item.stop = lambda: stopped.append(True) or True
    with pytest.raises(d.Refused, match='inspector_memory_limit'):
        item.require_memory_ok()
    assert stopped == [True]


def test_diagnostic_registered_workflow_is_opt_in_and_bounded():
    import yaml
    producer=yaml.load((ROOT/'.github/workflows/live-iso-bootc.yml').read_text(),Loader=yaml.BaseLoader)
    consumer=yaml.load((ROOT/'.github/workflows/iso-e2e.yml').read_text(),Loader=yaml.BaseLoader)
    option=producer['on']['workflow_dispatch']['inputs']['installed_boot_diagnostic']
    assert option['default'] == 'false'
    assert '120' in producer['jobs']['build']['timeout-minutes']
    steps=next(job['steps'] for job in consumer['jobs'].values() if 'strategy' in job)
    strict=next(step for step in steps if step.get('id') == 'e2e')
    assert '!inputs.installed_boot_diagnostic' in strict['if']
    uploads=[step for step in steps if 'actions/upload-artifact@' in step.get('uses','')]
    diagnostic=next(step for step in uploads if step['with']['name']=='installed-boot-diagnostic')
    assert diagnostic['with']['retention-days']=='3'
    assert len(diagnostic['with']['path'].splitlines())==2
    assert all(line.endswith(('report.json','manifest.json')) for line in diagnostic['with']['path'].splitlines())
    assert all('!inputs.installed_boot_diagnostic' in step['if'] for step in uploads if step!=diagnostic)


def test_prepare_rejects_cross_attempt_and_wrong_target():
    module_spec=importlib.util.spec_from_file_location('prepare_diagnostic',ROOT/'scripts/prepare-installed-boot-diagnostic.py')
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    sha='a'*40; digest='sha256:'+'b'*64
    env={'VARIANT':'skipjack','FLAVOR':'gnome','TUNAOS_QUAL_PLATFORM':'linux/amd64/v2',
         'GITHUB_REPOSITORY':'tuna-os/tunaOS','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}
    for key in ('source','overlay','installer','engine','media'):
        env['TUNAOS_QUAL_'+key.upper()+'_DIGEST']=digest
    binding={'producer_sha':sha,'producer_run':123,'producer_attempt':1,
             'artifact_id':456,'archive_digest':digest,'media_digest':digest}
    version = 'QEMU emulator version 8.2.2 (Debian 1:8.2.2+ds-0ubuntu1.18)'
    p,lock=module.prepare(env,binding,sha,digest,version)
    assert p['producer_run']==p['run'] and lock['guestfs_version']=='1.52.0'
    assert lock['qemu']['version']==version
    with pytest.raises(d.Refused,match='same_attempt_inputs'):
        module.prepare(env,{**binding,'producer_attempt':2},sha,digest,version)
    with pytest.raises(d.Refused,match='diagnostic_target'):
        module.prepare({**env,'VARIANT':'yellowfin'},binding,sha,digest,version)


def test_service_refuses_failed_stop(tmp_path,monkeypatch):
    from types import SimpleNamespace
    item=supervisor.ContainedProcess.__new__(supervisor.ContainedProcess)
    item.unit='fixture.service';item.invocation='a'*32;item.cgroup=tmp_path/'absent';item.stopped=False;item.stop_attempted=False
    item.info=lambda **kwargs:{'ActiveState':'inactive'}
    item.child=SimpleNamespace(wait=lambda **kwargs:0)
    monkeypatch.setattr(supervisor.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=1,stdout=b'inactive'))
    assert item.stop() is False


@pytest.mark.parametrize('bad_key,bad_value', [('User','0'),('Delegate','yes'),('KillMode','process'),('RemainAfterExit','no'),('ControlGroup','/guessed/path'),('InvocationID','bad')])
def test_service_policy_mismatch_stops_exact_unit(monkeypatch,bad_key,bad_value):
    from types import SimpleNamespace
    calls=[]
    def run(argv,**kwargs):calls.append(argv);return SimpleNamespace(returncode=0)
    def info(self,**kwargs):
        value={'User':str(os.getuid()),'Delegate':'no','KillMode':'control-group',
               'Restart':'no','RemainAfterExit':'yes','ControlGroup':'/system.slice/'+self.unit,'InvocationID':'a'*32}
        value[bad_key]=bad_value
        return value
    monkeypatch.setattr(supervisor.subprocess,'run',run)
    monkeypatch.setattr(supervisor.ContainedProcess,'info',info)
    with pytest.raises(d.Refused):supervisor.ContainedProcess(['fixture'])
    assert calls[-1][:4]==['sudo','-n','systemctl','stop']
    assert calls[-1][-1] in calls[0][6]


def test_service_poll_preserves_signal_exit_and_requires_stop(monkeypatch):
    item=supervisor.ContainedProcess.__new__(supervisor.ContainedProcess)
    item.returncode=None;item.stopped=False;item.stop_attempted=False
    item.info=lambda:{'ExecMainCode':'2','ExecMainStatus':'15'}
    assert item.poll()==143 and item.stopped is False


def test_service_identity_change_is_not_signal_authority(monkeypatch):
    from types import SimpleNamespace
    item=supervisor.ContainedProcess.__new__(supervisor.ContainedProcess)
    item.unit='fixture.service';item.invocation='a'*32
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv);return SimpleNamespace(returncode=0,stdout=b'InvocationID=other\n')
    monkeypatch.setattr(supervisor.subprocess,'run',run)
    with pytest.raises(d.Refused,match='service_identity_changed'):item.send_signal(15)
    assert len(calls)==1 and calls[0][0]=='systemctl'


def test_uncertain_service_start_remains_owned_and_blocks_inspection(monkeypatch):
    from types import SimpleNamespace
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        if 'systemd-run' in argv:raise supervisor.subprocess.TimeoutExpired('fixture',35)
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(supervisor.subprocess,'run',run)
    with pytest.raises(supervisor.subprocess.TimeoutExpired):supervisor.ContainedProcess(['fixture'])
    assert len(supervisor.OWNED_SERVICES)==1
    item=supervisor.OWNED_SERVICES[0]
    assert item.stopped is False and item.stop_attempted
    assert not all(service.stopped for service in supervisor.OWNED_SERVICES)
    assert item.stop() is False and len(calls)==2


@pytest.mark.parametrize('serial_text,expected', [(b'passphrase for disk root',77),(b'Entering emergency mode',2)])
def test_diagnostic_serial_observer_never_writes_to_guest(monkeypatch,serial_text,expected):
    # Execute the existing helper only with fake sockets and a deterministic clock.
    import runpy
    import socket
    import time
    class Serial:
        def connect(self,path):pass
        def settimeout(self,value):pass
        def recv(self,n):return serial_text
        def sendall(self,data):pytest.fail('guest input forbidden')
        def close(self):pass
    monkeypatch.setattr(socket,'socket',lambda *args,**kwargs:Serial())
    tick=iter([0,0,2,3,4,5])
    monkeypatch.setattr(time,'time',lambda:next(tick,100))
    monkeypatch.setattr(time,'sleep',lambda _:None)
    monkeypatch.setenv('TUNAOS_INSTALLED_BOOT_DIAGNOSTIC','1')
    monkeypatch.setenv('TUNAOS_LUKS_GRUB_APPEND','')
    monkeypatch.setattr(sys,'argv',['luks-first-boot.py','fixture-serial','fixture-monitor','NEVER-SENT','1'])
    with pytest.raises(SystemExit) as result:runpy.run_path(str(ROOT/'scripts/luks-first-boot.py'),run_name='__main__')
    assert result.value.code==expected


class ProcFixture:
    """No method here accesses procfs, commands, environments, or link targets."""
    def __init__(self, name, *, uid=None, denied=None, entries=(), disk=False):
        self.name = name
        self.uid = os.getuid() if uid is None else uid
        self.denied = denied
        self.entries = entries
        self.disk = disk
        self.enumerated = False

    def stat(self):
        from types import SimpleNamespace
        if self.denied in ('proc_stat', 'fd_stat'):
            raise PermissionError(13, 'SECRET /private/path executable environment cmdline')
        return SimpleNamespace(st_uid=self.uid, st_dev=1, st_ino=1 if self.disk else 2)

    def __truediv__(self, name):
        assert name == 'fd'
        assert self.uid == os.getuid(), 'other-user FDs must never be enumerated'
        return self

    def iterdir(self):
        self.enumerated = True
        if self.denied == 'fd_enumeration':
            raise PermissionError(13, 'SECRET /private/target')
        yield from self.entries


@pytest.mark.parametrize('stage', ['proc_stat', 'fd_enumeration', 'fd_stat'])
def test_descriptor_denial_observations_are_numeric_bounded_and_redacted(stage):
    fd = ProcFixture('7', denied='fd_stat' if stage == 'fd_stat' else None)
    proc = ProcFixture('123', denied=stage if stage != 'fd_stat' else None, entries=[fd])
    root = ProcFixture('root', entries=[proc])
    with pytest.raises(d.Refused, match='open_descriptor_scan_denied') as caught:
        supervisor.no_open_disk(ProcFixture('disk', disk=True), time.monotonic()+10, proc_root=root)
    facts = caught.value.details['descriptor_denials']
    assert len(facts) == 1
    fact = facts[0]
    assert fact['stage'] == stage and fact['pid'] == 123 and fact['errno'] == 13
    assert fact['previous_uid'] == (None if stage == 'proc_stat' else os.getuid())
    assert fact['ownership'] == ('unknown' if stage == 'proc_stat' else 'same_uid_observed')
    assert ('fd' in fact) == (stage == 'fd_stat')
    if stage == 'fd_stat':
        assert fact['fd'] == 7
    assert fact['counts']['processes'] == 1
    assert fact['counts']['fds'] == (1 if stage == 'fd_stat' else 0)
    assert set(fact) <= {'stage', 'pid', 'errno', 'previous_uid', 'ownership', 'counts', 'fd'}
    assert len(json.dumps(facts)) < 512 and 'SECRET' not in json.dumps(facts)


def test_descriptor_scan_skips_foreign_processes_and_refuses_open_disk():
    foreign = ProcFixture('1', uid=os.getuid()+1, entries=[ProcFixture('8', disk=True)])
    root = ProcFixture('root', entries=[foreign])
    supervisor.no_open_disk(ProcFixture('disk', disk=True), time.monotonic()+10, proc_root=root)
    assert not foreign.enumerated
    own = ProcFixture('2', entries=[ProcFixture('7', disk=True)])
    with pytest.raises(d.Refused, match='disk_still_open'):
        supervisor.no_open_disk(ProcFixture('disk', disk=True), time.monotonic()+10,
                                proc_root=ProcFixture('root', entries=[foreign, own]))


def test_descriptor_scan_limits_and_deadline_remain_fail_closed():
    with pytest.raises(d.Refused, match='descriptor_scan_timeout'):
        supervisor.no_open_disk(ProcFixture('disk'), 0,
                                proc_root=ProcFixture('root', entries=[ProcFixture('1')]))
    proc = ProcFixture('1', entries=(ProcFixture(str(i)) for i in range(100001)))
    with pytest.raises(d.Refused, match='descriptor_scan_limit'):
        supervisor.no_open_disk(ProcFixture('disk', disk=True), time.monotonic()+30,
                                proc_root=ProcFixture('root', entries=[proc]))


def test_descriptor_denials_are_reported_before_hash_and_inspection():
    source = (ROOT/'scripts/diagnose-installed-luks.py').read_text()
    assert source.index('no_open_disk(disk, deadline)') < source.index('disk_hash = file_digest')
    assert source.index('disk_hash = file_digest') < source.index("'inspect',")
    assert "report['descriptor_denials'] = error.details['descriptor_denials']" in source
