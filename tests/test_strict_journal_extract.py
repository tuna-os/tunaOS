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
    def __init__(self, filesystems, journal=True):
        self.filesystems = dict(filesystems)
        self.journal = journal
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
        self.calls.append(('mount_ro', device))

    def is_dir(self, path):
        assert path == '/var/log/journal'
        return self.journal

    def ls(self, path):
        assert path == '/var/log/journal'
        return ['system.journal', 'user-1000.journal']

    def download(self, remote, local):
        Path(local).write_bytes(b'journal-bytes:' + remote.encode())

    def umount(self, point):
        self.calls.append(('umount', point))

    def umount_all(self):
        self.calls.append(('umount_all',))

    def close(self):
        self.calls.append(('close',))


def guest_factory(filesystems, journal=True):
    made = {}
    def factory():
        made['guest'] = FakeGuest(filesystems, journal)
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
    assert report == {'collected': False, 'reason': 'journal_absent', 'mode': 'plain'}
    assert 'strict_journal=not_collected reason=journal_absent' in capsys.readouterr().out


def test_backing_file_disk_refuses(tmp_path):
    disk = tmp_path / 'install-disk.qcow2'
    qcow2(disk, backing=True)
    with pytest.raises(Exception, match='backing_file'):
        extract.d.qcow_header(disk)


def test_running_qemu_refuses():
    with pytest.raises(Exception, match='qemu_still_running'):
        extract.stopped(os.getpid())
