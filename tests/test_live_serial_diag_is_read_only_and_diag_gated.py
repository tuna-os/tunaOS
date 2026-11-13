"""The live-session serial diagnostic reads the guest and never qualifies one.

Published ISOs ship no sshd and the strict walkthrough runs nothing in the
guest, so a live session that never paints left screenshots as the only
evidence (marlin-niri run 43367881313, gurnard-pantheon run 43384739294).
scripts/live-serial-diag.py logs in on the harness-owned UART and writes
read-only probes to live-diag-<mode>.txt. Two properties matter: the output
carries the probe results, and iso-e2e.sh starts it only under
TUNAOS_LIVE_SERIAL_DIAG=1 so a qualification run never executes anything.

Falsification: behavioural. Make `run_strict_gui_install` start the script
unconditionally, or drop a probe from PROBES, and the matching assertion
below fails.
"""
import importlib.util
import re
import socket
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('live_serial_diag', ROOT / 'scripts/live-serial-diag.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

WRITE_VERBS = re.compile(r'\b(rm|mv|cp|tee|chmod|chown|systemctl\s+(start|stop|restart|enable|disable)|kill|pkill|dd)\b|[^|>]>[^&]')


def fake_getty(path, ready):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    ready.set()
    conn, _ = srv.accept()
    buf = b''
    state = 'login'
    while True:
        data = conn.recv(4096)
        if not data:
            return
        buf += data
        while b'\r' in buf:
            line, buf = buf.split(b'\r', 1)
            if state == 'login':
                if line:
                    conn.sendall(b'Password: ')
                    state = 'password'
                else:
                    conn.sendall(b'host login: ')
            elif state == 'password':
                conn.sendall(b'$ ')
                state = 'shell'
            else:
                token = re.search(rb"echo BEGIN_(\w+)''(\w+);", line)
                reply = b''
                if token:
                    name = (token[1] + token[2]).decode()
                    reply = f'BEGIN_{name}\r\nprobe-output\r\nEND_{name}\r\n$ '.encode()
                conn.sendall(reply)


def test_the_diag_logs_in_with_an_empty_password_and_keeps_every_probe(tmp_path):
    sock = tmp_path / 'c.sock'
    ready = threading.Event()
    threading.Thread(target=fake_getty, args=(sock, ready), daemon=True).start()
    assert ready.wait(5)
    out = tmp_path / 'live-diag.txt'
    import sys
    argv = sys.argv
    sys.argv = ['x', '--console', str(sock), '--out', str(out), '--first', '0', '--rounds', '1']
    try:
        assert diag.main() == 0
    finally:
        sys.argv = argv
    text = out.read_text()
    for label, _ in diag.PROBES:
        assert f'===== {label} =====' in text
    assert text.count('probe-output') == len(diag.PROBES)
    assert 'timed out' not in text


def test_every_probe_is_a_read():
    for label, command in diag.PROBES:
        assert not WRITE_VERBS.search(command), (label, command)
    labels = {label for label, _ in diag.PROBES}
    assert {'system-journal', 'user-journal', 'flatpak-ps', 'processes'} <= labels


def test_only_a_diag_run_starts_it():
    script = (ROOT / 'scripts/iso-e2e.sh').read_text()
    launch = '${SCRIPT_DIR}/live-serial-diag.py'
    assert script.count(launch) == 1
    start = script.index(launch)
    guard = script.rfind('TUNAOS_LIVE_SERIAL_DIAG', 0, start)
    assert guard != -1 and start - guard < 200
