"""Inert fixtures only: never launch QEMU, mount a disk, or run journalctl."""
import importlib.util
import json
import os
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location(
    'strict_journal_extract', ROOT / 'scripts/strict-journal-extract.py')
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


def qcow2(path, backing=False, size=32 * 1024**3):
    header = (b'QFI\xfb' + struct.pack('>I', 2)
              + struct.pack('>Q', 8 if backing else 0)
              + struct.pack('>I', 4 if backing else 0)
              + struct.pack('>I', 16) + struct.pack('>Q', size)
              + struct.pack('>I', 0))
    path.write_bytes(header.ljust(104, b'\0'))


class FakeGuest:
    """Records the read-only inspection; never touches a disk."""
    def __init__(self, filesystems, journal=True, journal_at=None,
                 listings=None, partitions=None, blkid_map=None,
                 files=None):
        self.filesystems = dict(filesystems)
        self.journal = journal
        self.journal_at = journal_at
        self.listings = listings or {}
        self.partitions = partitions
        self.blkid_map = blkid_map or {}
        self.files = files or {}
        self.current = None
        self.calls = []
        self.opened = []

    def add_drive_opts(self, path, readonly, format):
        assert readonly and format == 'qcow2'
        self.calls.append(('add_drive_opts', path))

    def launch(self):
        self.calls.append(('launch',))

    def list_filesystems(self):
        return dict(self.filesystems)

    def luks_open(self, device, key, name):
        self.opened.append((device, name))
        assert key == 'test-pass'
        self.filesystems['/dev/mapper/tunaos-strict-journal'] = 'ext4'

    def mount_ro(self, device, point):
        assert point == '/'
        self.current = device
        self.calls.append(('mount_ro', device))

    def is_dir(self, path):
        if self.journal_at is None:
            return self.journal
        if path in self.journal_at.get(self.current, []):
            return True
        return path in self.listings.get(self.current, {})

    def ls(self, path):
        if path in extract.JOURNAL_PATHS:
            return ['system.journal', 'user-1000.journal']
        listed = self.listings.get(self.current, {}).get(path)
        if listed is None:
            raise RuntimeError(f'no listing for {path}')
        return list(listed)

    def is_symlink(self, path):
        return self.listings.get(self.current, {}).get('symlink:' + path, False)

    def list_partitions(self):
        if self.partitions is None:
            return sorted(self.filesystems)
        return list(self.partitions)

    def blkid(self, device):
        return dict(self.blkid_map.get(device, {}))

    def read_lines(self, path):
        if path not in self.files:
            raise RuntimeError(f'no file {path}')
        return list(self.files[path])

    def download(self, remote, local):
        Path(local).write_bytes(b'journal-bytes:' + remote.encode())

    def umount(self, point):
        self.calls.append(('umount', point))

    def umount_all(self):
        self.calls.append(('umount_all',))

    def close(self):
        self.calls.append(('close',))


def guest_factory(filesystems, journal=True, journal_at=None):
    made = {}
    def factory():
        made['guest'] = FakeGuest(filesystems, journal, journal_at)
        return SimpleNamespace(GuestFS=lambda python_return_dict: made['guest'])
    factory.made = made
    return factory


def journal_runner_factory():
    def runner(argv, **kwargs):
        assert argv[0] == 'journalctl'
        if '--list-boots' in argv:
            return SimpleNamespace(returncode=0, stdout='boot 1\n')
        return SimpleNamespace(
            returncode=0,
            stdout='line one gnome-initial-setup wedge\nline two\nline three\n')
    return runner


def run_extract(tmp_path, mode='plain', filesystems=None,
                journal=True, pid=None, key='k'):
    filesystems = filesystems if filesystems is not None else {'/dev/sda3': 'ext4'}
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)
    factory = guest_factory(filesystems, journal)
    summary = extract.extract(str(disk), mode, str(tmp_path), key, pid,
                              guest_factory=factory,
                              runner=journal_runner_factory())
    return summary, factory.made['guest']


def test_plain_leg_collects_bounded_text(tmp_path):
    summary, guest = run_extract(tmp_path)
    assert ('add_drive_opts', str(tmp_path / 'install-disk.qcow2')) in guest.calls
    assert ('mount_ro', '/dev/sda3') in guest.calls
    assert (guest.calls[-2], guest.calls[-1]) == (('umount_all',), ('close',))
    tail = (tmp_path / 'journal-tail.txt').read_text()
    assert 'wedge' in tail
    picked = (tmp_path / 'journal-filtered.txt').read_text()
    assert 'wedge' in picked and 'line two' not in picked
    assert (tmp_path / 'journal-boots.txt').read_text() == 'boot 1\n'
    assert summary['picked'] == 1 and summary['lines'] == 3


def test_luks_leg_unlocks_with_passed_key_only(tmp_path):
    summary, guest = run_extract(
        tmp_path, mode='luks',
        filesystems={'/dev/sda3': 'crypto_LUKS'}, key='test-pass')
    assert guest.opened == [('/dev/sda3', 'tunaos-strict-journal')]
    assert ('mount_ro', '/dev/mapper/tunaos-strict-journal') in guest.calls


def test_luks_leg_without_key_refuses(tmp_path):
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)
    factory = guest_factory({'/dev/sda3': 'crypto_LUKS'})
    with pytest.raises(Exception, match='luks_key_missing'):
        extract.extract(str(disk), 'luks', str(tmp_path), None, None,
                        guest_factory=factory,
                        runner=journal_runner_factory())


def test_absent_journal_is_reported_not_fatal(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(extract, 'extract',
                        lambda *a, **k: (_ for _ in ()).throw(
                            extract.d.Refused('journal_absent')))
    rc = extract.main(['--disk', 'd', '--mode', 'plain',
                       '--out-dir', str(tmp_path),
                       '--journal-out', str(tmp_path / 'out')])
    assert rc == 0
    report = json.loads((tmp_path / 'out/strict-journal-extract.json').read_text())
    assert report == {'collected': False, 'reason': 'journal_absent',
                      'kind': 'Refused', 'stage': 'start', 'filesystems': {},
                      'seen': {}, 'mode': 'plain'}
    out = capsys.readouterr().out
    assert 'strict_journal=not_collected reason=journal_absent' in out
    assert 'kind=Refused stage=start' in out


def test_erofs_root_with_journal_is_collected(tmp_path):
    filesystems = {'/dev/sda1': 'vfat', '/dev/sda2': 'erofs'}
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)
    factory = guest_factory(filesystems,
                            journal_at={'/dev/sda2': ['/var/log/journal']})
    progress = {}
    summary = extract.extract(str(disk), 'plain', str(tmp_path), 'k', None,
                              guest_factory=factory,
                              runner=journal_runner_factory(), progress=progress)
    assert summary['device'] == '/dev/sda2'
    assert summary['journal_path'] == '/var/log/journal'
    assert summary['filesystems'] == filesystems
    assert progress['filesystems'] == filesystems


def test_split_var_partition_is_found_at_log_journal(tmp_path):
    filesystems = {'/dev/sda3': 'ext4', '/dev/sdb1': 'ext4'}
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)
    factory = guest_factory(filesystems,
                            journal_at={'/dev/sdb1': ['/log/journal']})
    summary = extract.extract(str(disk), 'plain', str(tmp_path), 'k', None,
                              guest_factory=factory,
                              runner=journal_runner_factory(), progress={})
    assert summary['device'] == '/dev/sdb1'
    assert summary['journal_path'] == '/log/journal'


def test_composefs_physical_root_journal_is_found_under_state(tmp_path):
    # Run 42858374248 grouper:gnome: sda2 root [composefs, ostree, state,
    # var] with var holding only cache; bootc's composefs backend keeps
    # the shared /var at state/os/default/var.
    filesystems = {'/dev/sda1': 'vfat', '/dev/sda2': 'ext4'}
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)
    factory = guest_factory(
        filesystems,
        journal_at={'/dev/sda2': ['/state/os/default/var/log/journal']})
    summary = extract.extract(str(disk), 'plain', str(tmp_path), 'k', None,
                              guest_factory=factory,
                              runner=journal_runner_factory(), progress={})
    assert summary['device'] == '/dev/sda2'
    assert summary['journal_path'] == '/state/os/default/var/log/journal'


def test_absent_journal_reports_layout_seen(tmp_path):
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)
    factory = guest_factory({'/dev/sda3': 'ext4'}, journal_at={})
    progress = {}
    with pytest.raises(Exception, match='journal_absent'):
        extract.extract(str(disk), 'plain', str(tmp_path), 'k', None,
                        guest_factory=factory,
                        runner=journal_runner_factory(), progress=progress)
    assert progress['filesystems'] == {'/dev/sda3': 'ext4'}
    assert progress['seen']['devices']['partitions'] == ['/dev/sda3']
    assert progress['seen']['mounts'] == {'/dev/sda3': {'root': 'unavailable'}}


def test_absent_journal_reports_var_contents(tmp_path):
    filesystems = {'/dev/sda1': 'vfat', '/dev/sda2': 'ext4'}
    listings = {'/dev/sda2': {'/': ['boot', 'var', 'etc'],
                              '/var': ['log', 'lib'],
                              '/var/log': ['installer']}}
    blkid_map = {'/dev/sda1': {'TYPE': 'vfat'},
                 '/dev/sda2': {'TYPE': 'ext4', 'LABEL': 'root'}}
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)
    made = {}

    def factory():
        made['guest'] = FakeGuest(filesystems, journal_at={},
                                  listings=listings,
                                  partitions=['/dev/sda1', '/dev/sda2'],
                                  blkid_map=blkid_map)
        return SimpleNamespace(GuestFS=lambda python_return_dict: made['guest'])

    progress = {}
    with pytest.raises(Exception, match='journal_absent'):
        extract.extract(str(disk), 'plain', str(tmp_path), 'k', None,
                        guest_factory=factory,
                        runner=journal_runner_factory(), progress=progress)
    seen = progress['seen']
    assert seen['devices']['blkid']['/dev/sda2'] == {'TYPE': 'ext4',
                                                     'LABEL': 'root'}
    mount = seen['mounts']['/dev/sda2']
    assert mount['root'] == ['boot', 'etc', 'var']
    assert mount['var'] == ['lib', 'log']
    assert mount['var_log'] == ['installer']
    assert mount['var_islink'] is False


def test_blkid_crypto_unlocks_even_when_unlisted(tmp_path):
    # Run 42858374248: list_filesystems showed only the ESP while blkid
    # named sda2 crypto_LUKS. The unlock must use both views.
    filesystems = {'/dev/sda1': 'vfat'}
    blkid_map = {'/dev/sda1': {'TYPE': 'vfat', 'LABEL': 'EFI-SYSTEM'},
                 '/dev/sda2': {'TYPE': 'crypto_LUKS'}}
    listings = {'/dev/mapper/tunaos-strict-journal':
                {'/': ['var'], '/var': ['log'], '/var/log': ['installer']}}
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)
    made = {}

    def factory():
        made['guest'] = FakeGuest(filesystems, journal_at={},
                                  listings=listings,
                                  partitions=['/dev/sda1', '/dev/sda2'],
                                  blkid_map=blkid_map)
        made['guest'].journal = False
        return SimpleNamespace(GuestFS=lambda python_return_dict: made['guest'])

    progress = {}
    with pytest.raises(Exception, match='journal_absent'):
        extract.extract(str(disk), 'luks', str(tmp_path), 'test-pass', None,
                        guest_factory=factory,
                        runner=journal_runner_factory(), progress=progress)
    assert made['guest'].opened == [('/dev/sda2', 'tunaos-strict-journal')]
    assert ('mount_ro', '/dev/mapper/tunaos-strict-journal') in made['guest'].calls
    assert progress['filesystems']['/dev/mapper/tunaos-strict-journal'] == 'ext4'


def test_absent_journal_reports_boot_options_and_state(tmp_path):
    listings = {'/dev/sda2': {'/': ['boot', 'state', 'var'],
                              '/boot/loader/entries': ['ostree.conf'],
                              '/state': ['journal-old']}}
    files = {'/boot/loader/entries/ostree.conf':
             ['title Grouper', 'options root=UUID=x console=ttyS0']}
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)
    made = {}

    def factory():
        made['guest'] = FakeGuest({'/dev/sda2': 'ext4'}, journal_at={},
                                  listings=listings, files=files)
        return SimpleNamespace(GuestFS=lambda python_return_dict: made['guest'])

    progress = {}
    with pytest.raises(Exception, match='journal_absent'):
        extract.extract(str(disk), 'plain', str(tmp_path), 'k', None,
                        guest_factory=factory,
                        runner=journal_runner_factory(), progress=progress)
    boot = progress['seen']['mounts']['/dev/sda2']['boot']
    assert boot['/boot/loader/entries'] == {
        'ostree.conf': ['root=UUID=x console=ttyS0']}
    assert boot['state'] == ['journal-old']


def test_launch_failure_reports_kind_and_stage(tmp_path):
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk)

    class DeadGuest(FakeGuest):
        def launch(self):
            raise RuntimeError('appliance failed')

    made = {}
    def factory():
        made['guest'] = DeadGuest({'/dev/sda3': 'ext4'}, True)
        return SimpleNamespace(GuestFS=lambda python_return_dict: made['guest'])
    progress = {}
    with pytest.raises(RuntimeError):
        extract.extract(str(disk), 'plain', str(tmp_path), 'k', None,
                        guest_factory=factory,
                        runner=journal_runner_factory(), progress=progress)
    assert progress == {'stage': 'launch'}


def test_backing_file_disk_refuses(tmp_path):
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk, backing=True)
    with pytest.raises(Exception, match='backing_file'):
        extract.d.qcow_header(disk)


def test_running_qemu_refuses():
    with pytest.raises(Exception, match='qemu_still_running'):
        extract.stopped(os.getpid())


class TreeGuest:
    """A guest journal directory laid out the way journald writes it."""
    def __init__(self, tree):
        self.tree = tree
        self.downloaded = []

    def _node(self, path):
        node = self.tree
        for part in path.strip('/').split('/'):
            node = node[part]
        return node

    def ls(self, path):
        return list(self._node(path))

    def is_dir(self, path):
        return isinstance(self._node(path), dict)

    def download(self, remote, local):
        self.downloaded.append(remote)
        Path(local).write_bytes(self._node(remote))


def test_copy_keeps_the_machine_id_directory(tmp_path):
    # Run 42895494800: the journal sat in <journal dir>/<machine-id>/ and the
    # flat copy rendered "-- No entries --" on both legs.
    mid = '0123456789abcdef0123456789abcdef'
    guest = TreeGuest({'state': {'os': {'default': {'var': {'log': {'journal': {
        mid: {'system.journal': b'sys', 'user-1000.journal': b'usr'},
        'remote': {'ignored.journal': b'x'},
    }}}}}}})
    extract.copy_journal(guest, tmp_path, '/state/os/default/var/log/journal')
    assert sorted(p.relative_to(tmp_path).as_posix()
                  for p in tmp_path.rglob('*.journal')) == [
        f'{mid}/system.journal', f'{mid}/user-1000.journal']
    assert (tmp_path / mid / 'system.journal').read_bytes() == b'sys'
