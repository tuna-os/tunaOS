#!/usr/bin/env python3
"""Diagnostics-only read of the live session over the harness-owned UART.

Published ISOs ship no sshd, and the strict walkthrough executes nothing in
the guest, so a live session that never paints (niri's installer window
absent, Pantheon's "Display output is not active.") leaves only screenshots.
This logs in on the serial getty as liveuser (published media delete its
password) and appends read-only probes to a text file, so the journal and
`flatpak ps` land in the diagnostic artifact.

NEVER qualification evidence: iso-e2e.sh starts it only when
TUNAOS_LIVE_SERIAL_DIAG=1, which only diag branches set. Every probe is a
read; nothing here changes the guest.
"""
import argparse
import re
import socket
import sys
import time

PROBES = (
    ('identity', 'id; uptime; cat /proc/cmdline'),
    ('failed-units', 'systemctl --failed --no-pager --plain'),
    ('gpu-modules', 'lsmod | grep -Ei "virtio|drm|simpledrm|bochs" ; ls -l /dev/dri 2>&1'),
    ('kernel-drm', 'S=$(sudo -n true 2>/dev/null && echo "sudo -n"); $S dmesg 2>&1 | grep -Ei "drm|virtio|gpu|simpledrm" | tail -n 40'),
    ('processes', 'ps -eo pid,etimes,stat,args --sort=start_time 2>&1 | grep -Ei '
                  '"niri|flatpak|lightdm|gala|Xorg|Xwayland|greeter|installer|waybar|wingpanel|plank|bootc|session" '
                  '| grep -v grep | cut -c1-200 | tail -n 60'),
    ('flatpak-ps', 'XDG_RUNTIME_DIR=/run/user/$(id -u) flatpak ps --columns=application,pid,instance 2>&1'),
    ('installer-manual', 'U=/run/user/$(id -u); if [ ! -f /tmp/inst.pid ]; then WAYLAND_DISPLAY=wayland-1 XDG_RUNTIME_DIR=$U '
                         'DBUS_SESSION_BUS_ADDRESS=unix:path=$U/bus setsid nohup flatpak run org.tunaos.InstallerNiri '
                         '>/tmp/inst.log 2>&1 & echo $! >/tmp/inst.pid; sleep 5; fi; echo "pid $(cat /tmp/inst.pid)"; '
                         'ls -l /proc/$(cat /tmp/inst.pid)/exe 2>&1; tail -n 80 /tmp/inst.log | cut -c1-240'),
    ('installer-info', 'flatpak info -m org.tunaos.InstallerNiri 2>&1 | head -n 40; ls -la ~/.var/app/org.tunaos.InstallerNiri 2>&1 | head'),
    ('crash-evidence', 'S=$(sudo -n true 2>/dev/null && echo "sudo -n"); $S journalctl -b --no-pager -g "segfault|oom-kill|Out of memory|coredump|InstallerNiri|quickshell|bwrap" 2>&1 | cut -c1-240 | tail -n 30; '
                       '$S dmesg 2>&1 | grep -Ei "segfault|oom|killed process" | tail -n 10; free -m'),
    ('flatpak-list', 'flatpak list --system --columns=application,version 2>&1 | head -n 20'),
    ('runtime-dir', 'ls -la /run/user/$(id -u) 2>&1 | head -n 30'),
    ('niri-config', 'ls -la ~/.config/niri 2>&1; grep -n "spawn" ~/.config/niri/config.kdl /etc/niri/config.kdl '
                    '/usr/share/niri/config.kdl 2>&1 | cut -c1-200 | head -n 30'),
    ('lightdm-logs', 'S=$(sudo -n true 2>/dev/null && echo "sudo -n"); $S ls -l /var/log/lightdm 2>&1; $S tail -n 60 /var/log/lightdm/lightdm.log /var/log/lightdm/seat0-greeter.log '
                     '/var/log/lightdm/x-0.log 2>&1 | cut -c1-220'),
    ('system-journal', 'S=$(sudo -n true 2>/dev/null && echo "sudo -n"); $S journalctl -b --no-pager -o short-monotonic -n 300 2>&1 | cut -c1-260'),
    ('user-journal', 'journalctl --user -b --no-pager -o short-monotonic -n 250 2>&1 | cut -c1-260'),
    ('seat-session', 'loginctl list-sessions --no-pager 2>&1; loginctl seat-status seat0 --no-pager 2>&1 | head -n 40'),
)
PROMPT = rb'[$#] ?$'


class Port:
    def __init__(self, path, deadline):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(1)
        while True:
            try:
                self.sock.connect(path)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(2)

    def read_until(self, pattern, seconds, resend=None):
        end = time.monotonic() + seconds
        data = b''
        nudge = time.monotonic() + 20
        while time.monotonic() < end:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                chunk = b''
            if chunk:
                data += re.sub(rb'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]', b'', chunk)
                if re.search(pattern, data):
                    return data
            elif resend and time.monotonic() > nudge:
                self.sock.sendall(resend)
                nudge = time.monotonic() + 20
        return None

    def send(self, text):
        self.sock.sendall(text.encode() + b'\r')


def login(port, seconds):
    port.sock.sendall(b'\r')
    got = port.read_until(rb'login:\s*$', seconds, resend=b'\r')
    if got is None:
        raise SystemExit('no serial login prompt')
    port.send('liveuser')
    # Published media delete liveuser's password, so the getty usually goes
    # straight to the motd; Ubuntu's prompt is then followed by terminal
    # queries, so a prompt pattern anchored at the end never matches. Answer a
    # Password: prompt if one comes, otherwise let the shell settle. Every
    # probe is delimited by its own markers and does not need the prompt.
    got = port.read_until(rb'Password:\s*$', 8)
    if got is not None:
        port.send('')
    time.sleep(4)
    port.send('')


def probe(port, out, label, command, token):
    begin, end = f'BEGIN_{token}', f'END_{token}'
    # The markers are assembled by the shell so the terminal echo of the
    # command line cannot be mistaken for the output.
    port.send(f"echo BEGIN_{token[:4]}''{token[4:]}; {{ {command} ; }} 2>&1 | head -c 60000; echo END_{token[:4]}''{token[4:]}")
    got = port.read_until(re.escape(end.encode()) + rb'\r?\n', 120)
    out.write(f'\n===== {label} =====\n')
    if got is None:
        out.write('(timed out)\n')
    else:
        text = got.decode('utf-8', 'replace').replace('\r', '')
        match = re.findall(re.escape(begin) + r'\n(.*?)\n' + re.escape(end), text, re.S)
        out.write((match[-1] if match else text[-4000:]) + '\n')
    out.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--console', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--first', type=int, default=30, help='seconds after launch before the first probe round')
    ap.add_argument('--interval', type=int, default=60)
    ap.add_argument('--rounds', type=int, default=8)
    args = ap.parse_args()
    started = time.monotonic()
    port = Port(args.console, started + 300)
    with open(args.out, 'a', encoding='utf-8') as out:
        login(port, 900)
        for round_no in range(args.rounds):
            wait = started + args.first + round_no * args.interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            out.write(f'\n######## round {round_no} at +{int(time.monotonic() - started)}s ########\n')
            for index, (label, command) in enumerate(PROBES):
                probe(port, out, label, command, f'DIAG{round_no:02d}{index:02d}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
