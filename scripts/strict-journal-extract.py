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
import re
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
# GNOME's first-boot setup, then the greeter login of an installer-created
# account (KDE, XFCE, COSMIC, niri): the greeter, PAM's verdict and any
# SELinux denial on the way.
FILTER = ('gnome-initial-setup', 'gdm', 'timedated', 'geoclue',
          'gnome-shell', 'not responding',
          'plasmalogin', 'plasma-login', 'sddm', 'lightdm', 'cosmic-greeter', 'greetd',
          'pam_unix', 'unix_chkpwd', 'pam_faillock', 'avc:  denied')


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
    # The runner user is not root: apt-get alone fails on hosted runners, and
    # a stale package index fails it too. gurnard-pantheon run 44490304237
    # refused inspector_unavailable while run 44463276563 on the same image
    # collected, so try the plain call, then sudo with a fresh index.
    packages = ['libguestfs-tools', 'python3-guestfs', 'cryptsetup']
    attempts = [['apt-get', 'install', '-y', '--no-install-recommends', *packages]]
    if os.geteuid() != 0:
        attempts += [['sudo', '-n', 'apt-get', 'update'],
                     ['sudo', '-n', 'apt-get', 'install', '-y', '--no-install-recommends', *packages]]
    for argv in attempts:
        try:
            subprocess.run(argv, capture_output=True, timeout=300, check=False,
                           env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            import guestfs  # noqa: PLC0415
            return guestfs
        except ImportError:
            continue
    try:
        import guestfs  # noqa: PLC0415
        return guestfs
    except ImportError:
        raise d.Refused('inspector_unavailable') from None


CANDIDATE_FILESYSTEMS = ('ext4', 'xfs', 'btrfs', 'erofs')
# A root filesystem exposes var/log/journal; a standalone mounted /var
# exposes the same tree at log/journal. Run 42757784060 proved the
# layout cannot be assumed: grouper may ship composefs (erofs) with a
# split /var, so check both shapes on every mountable filesystem.
# A bootc install's physical root keeps /var per stateroot instead:
# composefs at state/os/default/var (bootc-sysroot(7)), ostree at
# ostree/deploy/default/var. Run 42858374248 (grouper:gnome, composefs)
# refused journal_absent with root [composefs, ostree, state, var] and a
# top-level var holding only cache, so the stateroot paths come too.
JOURNAL_PATHS = ('/var/log/journal', '/log/journal',
                 '/state/os/default/var/log/journal',
                 '/ostree/deploy/default/var/log/journal')

# journald keeps a persistent journal in <journal dir>/<machine-id>/, never
# flat. Run 42895494800 (grouper:gnome) found /state/os/default/var/log/journal
# and still rendered "-- No entries --" on both legs: the copy skipped every
# directory, so it copied nothing. journalctl --directory reads machine-id
# subdirectories itself, so the copy keeps that one level.
MACHINE_ID = re.compile(r'[0-9a-f]{32}')


SEEN_ENTRIES = 24


def survey_mount(g, dev):
    """Bounded visible layout of one mounted candidate: names only."""
    seen = {}
    try:
        seen['root'] = sorted(g.ls('/'))[:SEEN_ENTRIES]
    except Exception:
        seen['root'] = 'unavailable'
        return seen
    try:
        seen['var_islink'] = bool(g.is_symlink('/var'))
    except Exception:
        seen['var_islink'] = 'unavailable'
    try:
        if g.is_dir('/var'):
            seen['var'] = sorted(g.ls('/var'))[:SEEN_ENTRIES]
    except Exception:
        seen['var'] = 'unavailable'
    try:
        if g.is_dir('/var/log'):
            seen['var_log'] = sorted(g.ls('/var/log'))[:SEEN_ENTRIES]
    except Exception:
        seen['var_log'] = 'unavailable'
    return seen


def survey_devices(g):
    """Partition table and blkid view: names and types only, no secrets."""
    seen = {}
    try:
        seen['partitions'] = sorted(g.list_partitions())
    except Exception:
        seen['partitions'] = 'unavailable'
    blkid = {}
    for dev in seen.get('partitions', []) if isinstance(
            seen.get('partitions'), list) else []:
        try:
            info = g.blkid(dev) or {}
            blkid[dev] = {k: info[k] for k in ('TYPE', 'LABEL') if k in info}
        except Exception:
            blkid[dev] = 'unavailable'
    seen['blkid'] = blkid
    return seen


def survey_boot(g):
    """Boot loader entries' kernel options: the booted config, bounded."""
    seen = {}
    for directory in ('/boot/loader/entries', '/loader/entries'):
        try:
            if not g.is_dir(directory):
                continue
            names = sorted(g.ls(directory))[:SEEN_ENTRIES]
        except Exception:
            continue
        entries = {}
        for name in names:
            if not name.endswith('.conf'):
                continue
            path = f'{directory}/{name}'
            try:
                options = [line for line in g.read_lines(path)
                           if line.startswith('options ')]
                entries[name] = [line[len('options '):][:512]
                                 for line in options[:4]]
            except Exception:
                entries[name] = 'unavailable'
        if entries:
            seen[directory] = entries
    try:
        if g.is_dir('/state'):
            seen['state'] = sorted(g.ls('/state'))[:SEEN_ENTRIES]
    except Exception:
        seen['state'] = 'unavailable'
    return seen


def mount_root(g, key, progress):
    """Return (device, journal path) once a read-only mount exposes it."""
    filesystems = g.list_filesystems()
    progress['filesystems'] = dict(filesystems)
    # Run 42836512627 refused on both legs at mount with a filesystems
    # map but no journal: plain showed sda1 vfat + sda2 ext4 with neither
    # journal path, luks showed only the ESP (no crypto device at all).
    # Record what each mount actually exposes so the next refusal names
    # where /var went instead of only naming the miss.
    progress['seen'] = {'devices': survey_devices(g), 'mounts': {}}
    # Run 42858374248: list_filesystems omitted the LUKS member entirely
    # (only the ESP was listed) while blkid named sda2 crypto_LUKS, so
    # unlock candidates come from both views. A kernel cmdline carries no
    # secrets; options lines name the booted config for the serial gap.
    blkid = progress['seen']['devices'].get('blkid', {})
    crypto = {dev for dev, fs in filesystems.items()
              if fs in ('crypto_LUKS', 'crypto')}
    crypto.update(dev for dev, info in blkid.items()
                  if isinstance(info, dict)
                  and info.get('TYPE') in ('crypto_LUKS', 'crypto'))
    if crypto:
        d.require(key is not None, 'luks_key_missing')
        for i, dev in enumerate(sorted(crypto)):
            name = ('tunaos-strict-journal' if i == 0
                    else f'tunaos-strict-journal-{i}')
            try:
                g.luks_open(dev, key, name)
            except Exception:
                raise d.Refused('unexpected_encryption') from None
        filesystems = g.list_filesystems()
        progress['filesystems'] = dict(filesystems)
    for dev in sorted(filesystems):
        if filesystems[dev] not in CANDIDATE_FILESYSTEMS:
            continue
        try:
            g.mount_ro(dev, '/')
        except Exception:
            continue
        try:
            mounted = survey_mount(g, dev)
            boot = survey_boot(g)
            if boot:
                mounted['boot'] = boot
            progress['seen']['mounts'][dev] = mounted
            for path in JOURNAL_PATHS:
                if g.is_dir(path):
                    return dev, path
        except Exception:
            pass
        try:
            g.umount('/')
        except Exception:
            pass
    raise d.Refused('journal_absent')


def password_state(field):
    """Classify a shadow password field without exposing it: `locked`
    (leading `!`), `empty`, `none` (`*`), or the hash scheme only."""
    if field.startswith('!'):
        return 'locked'
    if field == '':
        return 'empty'
    if field in ('*', 'x'):
        return 'none'
    parts = field.split('$')
    return f'hash:${parts[1]}$' if len(parts) > 2 else 'hash:other'


def deployment_etcs(g):
    """(label, etc dir) of each deployment on a mounted physical root:
    ostree at ostree/deploy/<stateroot>/deploy/<id>/etc, composefs at
    state/deploy/<id>/etc (gurnard-pantheon run 44504177436 is composefs, and
    the ostree-only walk found no accounts)."""
    out = []
    for stateroot_base in ('/ostree/deploy',):
        try:
            stateroots = g.ls(stateroot_base)
        except Exception:
            stateroots = []
        for root in stateroots:
            try:
                deploys = g.ls(f'{stateroot_base}/{root}/deploy')
            except Exception:
                continue
            out += [(f'ostree/{root}/{dep}', f'{stateroot_base}/{root}/deploy/{dep}/etc')
                    for dep in deploys]
    try:
        deploys = g.ls('/state/deploy')
    except Exception:
        deploys = []
    out += [(f'composefs/{dep}', f'/state/deploy/{dep}/etc') for dep in deploys]
    return out


def var_dirs(g):
    """Each stateroot's /var on a mounted physical root (ostree and composefs)."""
    out = []
    try:
        out += [f'/ostree/deploy/{root}/var' for root in g.ls('/ostree/deploy')]
    except Exception:
        pass
    try:
        out += [f'/state/os/{root}/var' for root in g.ls('/state/os')]
    except Exception:
        pass
    return out


def account_states(g):
    """Login accounts (uid >= 1000) of each ostree deployment and the state
    of their shadow entry. gurnard-pantheon (run 44463276563): Initial Setup
    created the account and asked accounts-daemon to set its password, and
    the greeter then showed "Account disabled". The shadow field says
    whether chpasswd ever ran. Names, uids and the class only; never a hash."""
    found = {}
    for label, etc in deployment_etcs(g):
        try:
            if not g.is_file(f'{etc}/shadow'):
                continue
            passwd = g.cat(f'{etc}/passwd')
            shadow = g.cat(f'{etc}/shadow')
        except Exception:
            continue
        uids = {}
        for line in passwd.splitlines():
            f = line.split(':')
            if len(f) >= 3 and f[2].isdigit() and 1000 <= int(f[2]) < 60000:
                uids[f[0]] = int(f[2])
        accounts = {}
        for line in shadow.splitlines():
            f = line.split(':')
            if len(f) >= 8 and f[0] in uids:
                accounts[f[0]] = {'uid': uids[f[0]], 'password': password_state(f[1]),
                                  'expire': f[7]}
        found[label] = accounts
    return found


LIGHTDM_LOG_BYTES = 64 * 1024


def lightdm_logs(g, out_dir):
    """Tails of LightDM's own logs. Pantheon's Initial Setup runs as the greeter
    session, so its warnings (e.g. "SetPassword call failed") land in
    /var/log/lightdm/seat0-greeter.log, never in the journal."""
    written = []
    for var in var_dirs(g):
        logdir = f'{var}/log/lightdm'
        try:
            names = g.ls(logdir)
        except Exception:
            continue
        for name in sorted(names):
            if not name.endswith('.log'):
                continue
            try:
                data = g.read_file(f'{logdir}/{name}')
            except Exception:
                continue
            target = Path(out_dir) / f'lightdm-{name}'
            target.write_bytes(data[-LIGHTDM_LOG_BYTES:])
            written.append(target.name)
    return written


def copy_journal(g, dest, jpath, clock=time.monotonic):
    deadline = clock() + INSPECTION_SECONDS
    total = 0
    pending = [(jpath, dest, True)]
    while pending:
        source, target_dir, descend = pending.pop(0)
        for name in sorted(g.ls(source)):
            d.require(clock() < deadline, 'journal_too_large')
            if name in ('.', '..'):
                continue
            path = f'{source}/{name}'
            try:
                is_dir = g.is_dir(path)
            except Exception:
                continue
            if is_dir:
                if descend and MACHINE_ID.fullmatch(name):
                    (target_dir / name).mkdir()
                    pending.append((path, target_dir / name, False))
                continue
            target = target_dir / name
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
            clock=time.monotonic, runner=None, progress=None):
    if progress is None:
        progress = {}
    progress['stage'] = 'gates'
    disk, out_dir = Path(disk).absolute(), Path(out_dir).absolute()
    if qemu_pid is not None:
        stopped(qemu_pid)
    d.regular(disk, out_dir)
    d.qcow_header(disk)
    progress['stage'] = 'guestfs'
    guestfs = (guest_factory or ensure_guestfs)()
    key = key or None
    if mode == 'luks':
        d.require(bool(key), 'luks_key_missing')
    g = guestfs.GuestFS(python_return_dict=True)
    progress['stage'] = 'launch'
    try:
        g.add_drive_opts(str(disk), readonly=1, format='qcow2')
        g.launch()
        progress['stage'] = 'mount'
        device, jpath = mount_root(g, key, progress)
        try:
            accounts = account_states(g)
        except Exception:
            accounts = {'error': 'unreadable'}
        try:
            greeter_logs = lightdm_logs(g, out_dir)
        except Exception:
            greeter_logs = []
        with tempfile.TemporaryDirectory(prefix='tunaos-strict-journal-') as tmp:
            staged = Path(tmp) / 'journal'
            staged.mkdir()
            progress['stage'] = 'copy'
            copy_journal(g, staged, jpath, clock)
            progress['stage'] = 'render'
            summary = render(staged, out_dir, runner)
            summary['device'] = device
            summary['journal_path'] = jpath
            summary['filesystems'] = progress.get('filesystems', {})
            summary['accounts'] = accounts
            summary['lightdm_logs'] = greeter_logs
            (out_dir / 'strict-accounts.json').write_text(json.dumps(accounts, indent=2) + '\n')
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
    report = {'collected': False, 'reason': 'inspection_refused',
              'kind': 'unknown', 'stage': 'start', 'mode': args.mode}
    progress = {'stage': 'start'}
    try:
        key = os.environ.get(args.luks_pass_env)
        summary = extract(args.disk, args.mode, args.out_dir, key, args.qemu_pid,
                          progress=progress)
        report = {'collected': True, 'mode': args.mode, **summary}
    except Exception as error:  # noqa: BLE001 - best-effort, kind only
        # Class name only, never the message: guest paths, appliance
        # stderr and key material must not reach the artifact. Device
        # names and fstypes are safe and name the layout on a miss.
        report['reason'] = refusal(error)
        report['kind'] = type(error).__name__
        report['stage'] = progress['stage']
        report['filesystems'] = progress.get('filesystems', {})
        report['seen'] = progress.get('seen', {})
    finally:
        key = None
    (out / 'strict-journal-extract.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f"strict_journal={'collected' if report['collected'] else 'not_collected'}"
          f" reason={report.get('reason', 'ok')}"
          f" kind={report.get('kind', 'ok')} stage={report.get('stage', 'done')}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
