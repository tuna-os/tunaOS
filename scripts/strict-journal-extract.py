#!/usr/bin/env python3
"""Read-only guest journal after a failed strict first boot.

Best-effort post-mortem, never qualification. The persistent journal
(tunaOS#4471) survives on the stopped installed disk; the screenshots
alone could not say why grouper:gnome run 42720562346 ignored every
time-zone advance on both legs. This copies the journal out read-only
and renders bounded text from it. The original first-boot failure
remains decisive.

Safety shape mirrors strict_luks_failure_diagnostics: only a qcow2
with no backing file, owned by this user under the job output dir,
inspected after the QEMU exit is proven. The LUKS test passphrase
arrives by environment, is used once as the guestfs key, and is never
logged or persisted. Any failure (old image without a persistent
journal, missing guestfs, odd layout) is reported, never fatal.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import installed_boot_diagnostic as d

INSPECTION_SECONDS = 180
REFUSALS = frozenset((
    'not_qcow2', 'backing_file', 'encrypted_qcow', 'unsupported_qcow_version',
    'unsupported_qcow_features', 'virtual_size', 'not_owned_regular_file',
    'disk_outside_owned_directory', 'symlink_path', 'qemu_still_running',
    'qemu_exit_unproven', 'inspector_unavailable', 'unexpected_encryption',
    'luks_key_missing', 'no_readable_root', 'journal_absent',
    'journal_too_large', 'journalctl_failed',
))
TAIL_LINES = 3000
FILTERED_LINES = 5000
JOURNAL_BYTES = 56 * 1024 * 1024
OUTPUT_BYTES = 8 * 1024 * 1024
FILTER = ('gnome-initial-setup', 'gdm', 'timedated', 'geoclue',
          'gnome-shell', 'not responding')


def refusal(error):
    """Never persist exception text, guest configuration or helper stderr."""
    return str(error) if isinstance(error, d.Refused) and str(error) in REFUSALS else 'inspection_refused'


def stopped(pid):
    d.require(type(pid) is int and pid > 1, 'qemu_exit_unproven')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    except OSError:
        raise d.Refused('qemu_exit_unproven') from None
    raise d.Refused('qemu_still_running')


def ensure_guestfs():
    try:
        import guestfs  # noqa: PLC0415
        return guestfs
    except ImportError:
        pass
    try:
        subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends',
                        'libguestfs-tools', 'python3-guestfs', 'cryptsetup'],
                       capture_output=True, timeout=300, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        import guestfs  # noqa: PLC0415
        return guestfs
    except ImportError:
        raise d.Refused('inspector_unavailable') from None


def mount_root(g, key):
    """Return once a read-only / exposes var/log/journal, else refuse."""
    filesystems = g.list_filesystems()
    crypto = [dev for dev, fs in filesystems.items() if fs in ('crypto_LUKS', 'crypto')]
    if crypto:
        d.require(key is not None, 'luks_key_missing')
        for dev in sorted(crypto):
            try:
                g.luks_open(dev, key, 'tunaos-strict-journal')
            except Exception:
                raise d.Refused('unexpected_encryption') from None
        filesystems = g.list_filesystems()
    for dev in sorted(filesystems):
        if filesystems[dev] not in ('ext4', 'xfs', 'btrfs'):
            continue
        try:
            g.mount_ro(dev, '/')
        except Exception:
            continue
        try:
            if g.is_dir('/var/log/journal'):
                return dev
        except Exception:
            pass
        try:
            g.umount('/')
        except Exception:
            pass
    raise d.Refused('journal_absent')


def copy_journal(g, dest, clock=time.monotonic):
    deadline = clock() + INSPECTION_SECONDS
    total = 0
    for name in sorted(g.ls('/var/log/journal')):
        d.require(clock() < deadline, 'journal_too_large')
        if name in ('.', '..'):
            continue
        path = f'/var/log/journal/{name}'
        try:
            if g.is_dir(path):
                continue
        except Exception:
            continue
        target = dest / name
        g.download(path, str(target))
        total += target.stat().st_size
        d.require(total <= JOURNAL_BYTES, 'journal_too_large')


def render(directory, out, runner=None):
    runner = runner or subprocess.run
    def ctl(*args):
        done = runner(['journalctl', f'--directory={directory}', '--no-pager',
                       *args], capture_output=True, text=True, timeout=120)
        d.require(done.returncode == 0, 'journalctl_failed')
        return done.stdout
    boots = ctl('--list-boots')
    (out / 'journal-boots.txt').write_text(boots[-4096:])
    full = ctl('-o', 'short-precise')
    if len(full.encode()) > OUTPUT_BYTES:
        full = full.encode()[-OUTPUT_BYTES:].decode('utf-8', 'replace')
    lines = full.splitlines()
    (out / 'journal-tail.txt').write_text('\n'.join(lines[-TAIL_LINES:]) + '\n')
    picked = [line for line in lines
              if any(mark in line for mark in FILTER)][:FILTERED_LINES]
    (out / 'journal-filtered.txt').write_text('\n'.join(picked) + '\n')
    return {'boots': len(boots.splitlines()), 'lines': len(lines), 'picked': len(picked)}


def extract(disk, mode, out_dir, key, qemu_pid, guest_factory=None,
            clock=time.monotonic, runner=None):
    disk, out_dir = Path(disk).absolute(), Path(out_dir).absolute()
    if qemu_pid is not None:
        stopped(qemu_pid)
    d.regular(disk, out_dir)
    d.qcow_header(disk)
    guestfs = (guest_factory or ensure_guestfs)()
    key = key or None
    if mode == 'luks':
        d.require(bool(key), 'luks_key_missing')
    g = guestfs.GuestFS(python_return_dict=True)
    try:
        g.add_drive_opts(str(disk), readonly=1, format='qcow2')
        g.launch()
        device = mount_root(g, key)
        with tempfile.TemporaryDirectory(prefix='tunaos-strict-journal-') as tmp:
            staged = Path(tmp) / 'journal'
            staged.mkdir()
            copy_journal(g, staged, clock)
            summary = render(staged, out_dir, runner)
            summary['device'] = device
            return summary
    finally:
        try:
            g.umount_all()
        except Exception:
            pass
        try:
            g.close()
        except Exception:
            pass


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--disk', required=True)
    parser.add_argument('--mode', required=True, choices=('plain', 'luks'))
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--journal-out', required=True)
    parser.add_argument('--luks-pass-env', default='TUNAOS_JOURNAL_LUKS_PASS')
    parser.add_argument('--qemu-pid', type=int, default=None)
    args = parser.parse_args(argv)
    out = Path(args.journal_out)
    out.mkdir(parents=True, exist_ok=True)
    report = {'collected': False, 'reason': 'inspection_refused', 'mode': args.mode}
    try:
        key = os.environ.get(args.luks_pass_env)
        summary = extract(args.disk, args.mode, args.out_dir, key, args.qemu_pid)
        report = {'collected': True, 'mode': args.mode, **summary}
    except Exception as error:  # noqa: BLE001 - best-effort, reason only
        report['reason'] = refusal(error)
    finally:
        key = None
    (out / 'strict-journal-extract.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f"strict_journal={'collected' if report['collected'] else 'not_collected'}"
          f" reason={report.get('reason', 'ok')}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
