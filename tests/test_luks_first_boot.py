#!/usr/bin/env python3
"""
Unit tests for scripts/luks-first-boot.py

The script drives the FIRST boot of a LUKS-installed system over the QEMU
serial socket: it watches for the cryptsetup passphrase prompt, injects the
passphrase, waits for userspace (login / multi-user target), optionally waits
for the desktop-contract marker, then powers the guest off via the monitor
socket.

The script executes its whole state machine at module level (sys.argv driven),
which is why it previously had 0% coverage. These tests load it in-process
behind fully mocked `socket` and `time` modules, proving the state machine is
unit-testable without refactoring the production script.

Run with:

    python3 -m pytest tests/test_luks_first_boot.py -v

Related issue: https://github.com/tuna-os/tunaOS/issues/1395
"""

import importlib.util
import os
import sys
from io import BytesIO
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "luks-first-boot.py"
# importlib execution needs the same library path as direct script execution.
sys.path.insert(0, str(SCRIPT.parent))


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeTimeout(Exception):
    """Stand-in for socket.timeout (raised by FakeSocket when out of data)."""


class FakeClock:
    """Deterministic monotonic clock; sleep() is instant but advances time."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeSocket:
    """Scripted UNIX socket: serves queued bytes, records sendall payloads.

    Each recv() call advances the fake clock by *advance* seconds, so the
    script's polling loop and the hardcoded 60 s enrollment window elapse
    deterministically and fast.
    """

    def __init__(self, chunks, clock, advance=10.0, fail_connect=False, fail_sendall=False):
        self._chunks = list(chunks)
        self._clock = clock
        self._advance = advance
        self.sent = b""
        self.connected = False
        self.fail_connect = fail_connect
        self.fail_sendall = fail_sendall

    def connect(self, path):
        if self.fail_connect:
            raise OSError(f"connection refused (fake): {path}")
        self.connected = True

    def settimeout(self, seconds):
        pass

    def recv(self, n):
        self._clock.now += self._advance
        if self._chunks:
            return self._chunks.pop(0)
        raise FakeTimeout("no data (fake)")

    def sendall(self, data):
        if self.fail_sendall:
            raise OSError("broken pipe (fake)")
        self.sent += data


class FakeSocketModule:
    """sys.modules['socket'] stand-in.

    Returns the serial socket until it connects successfully, then the monitor
    socket — mirroring how the script first connects to the serial socket and
    only later to the monitor socket for system_powerdown.
    """

    timeout = FakeTimeout
    AF_UNIX = 1
    SOCK_STREAM = 2

    def __init__(self, serial, monitor):
        self.serial = serial
        self.monitor = monitor

    def socket(self, family, socktype):
        if self.serial.connected:
            return self.monitor
        return self.serial


class FakeTimeModule:
    """sys.modules['time'] stand-in backed by a FakeClock."""

    def __init__(self, clock):
        self._clock = clock

    def time(self):
        return self._clock.time()

    def sleep(self, seconds):
        return self._clock.sleep(seconds)


class FakeExit(Exception):
    """Raised in place of sys.exit() to capture the requested exit code."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class FakeStdout:
    """sys.stdout stand-in: buffers both write() (print) and buffer.write()."""

    def __init__(self):
        self.buffer = BytesIO()

    def write(self, s):
        self.buffer.write(s.encode("utf-8", "replace"))

    def flush(self):
        pass


# ── Harness ──────────────────────────────────────────────────────────────────

def _run(argv, serial_chunks=(), monitor_chunks=(), advance=10.0,
         serial_fail=False, monitor_fail=False, monitor_send_fail=False):
    """Load scripts/luks-first-boot.py with mocked socket/time and run it.

    Returns a dict with the exit code, serial-socket sendall payload, monitor
    socket sendall payload, and captured stdout.
    """
    clock = FakeClock()
    serial = FakeSocket(list(serial_chunks), clock, advance, serial_fail)
    monitor = FakeSocket(list(monitor_chunks), clock, advance, monitor_fail, monitor_send_fail)
    fake_modules = {
        "socket": FakeSocketModule(serial, monitor),
        "time": FakeTimeModule(clock),
    }
    stdout = FakeStdout()
    exit_codes = []

    from lib import luks_secret
    original_reader=luks_secret.read_passphrase
    r,w=os.pipe()
    os.write(w,argv.passphrase.encode()+b'\n');os.close(w)
    luks_secret.read_passphrase=lambda:original_reader(r)
    saved = (sys.argv, sys.exit, sys.stdout)
    orig_modules = {name: sys.modules.get(name) for name in fake_modules}
    try:
        sys.argv = list(argv)
        sys.exit = lambda code=0: (_ for _ in ()).throw(FakeExit(code))
        sys.stdout = stdout
        for name, fake in fake_modules.items():
            sys.modules[name] = fake

        spec = importlib.util.spec_from_file_location("luks_first_boot", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except FakeExit as e:
            exit_codes.append(e.code)
        except SystemExit as e:  # connect() raises SystemExit directly
            exit_codes.append(e.code if isinstance(e.code, int) else 1)
    finally:
        luks_secret.read_passphrase=original_reader
        os.close(r)
        sys.argv, sys.exit, sys.stdout = saved
        for name, fake in fake_modules.items():
            if sys.modules.get(name) is fake:
                if orig_modules[name] is not None:
                    sys.modules[name] = orig_modules[name]
                else:
                    del sys.modules[name]

    return {
        "exit_code": exit_codes[-1] if exit_codes else None,
        "serial_sent": serial.sent.decode("utf-8", "replace"),
        "monitor_sent": monitor.sent.decode("utf-8", "replace"),
        "stdout": stdout.buffer.getvalue().decode("utf-8", "replace"),
    }


def _argv(timeout="120", contract_wait=None, passphrase="testpass"):
    class ProtectedArgs(list):
        pass
    argv = ProtectedArgs(["luks-first-boot.py", "/tmp/serial.sock", "/tmp/monitor.sock", '--passphrase-stdin', timeout])
    argv.passphrase=passphrase
    if contract_wait is not None:
        argv.append(contract_wait)
    return argv


# ── Tests ────────────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_success_injects_passphrase_and_powers_down(self):
        res = _run(
            _argv(),
            serial_chunks=[
                b"GRUB loading...\n",
                b"  Passphrase for disk root (cryptroot):",
                b"tunaos login: ",
                b"TUNAOS_DESKTOP_CONTRACT_OK\n",
            ],
        )
        assert res["exit_code"] == 0
        assert "testpass\n" in res["serial_sent"]
        assert res["monitor_sent"].startswith("system_powerdown")
        assert "passphrase accepted" in res["stdout"]

    def test_success_reports_contract_ok(self):
        res = _run(
            _argv(),
            serial_chunks=[
                b"Passphrase for disk root:",
                b"login: ",
                b"TUNAOS_DESKTOP_CONTRACT_OK",
            ],
        )
        assert res["exit_code"] == 0
        assert "LUKS_FIRST_BOOT_DESKTOP_CONTRACT=ok" in res["stdout"]

    def test_success_reports_absent_when_no_contract_marker(self):
        # contract_wait=10: login elapses 60 s, marker never appears, the
        # script warns and bails with the "absent" contract status.
        res = _run(
            _argv(contract_wait="10"),
            serial_chunks=[
                b"Passphrase for disk root:",
                b"login: ",
            ],
        )
        assert res["exit_code"] == 0
        assert "no desktop contract marker" in res["stdout"]
        assert "LUKS_FIRST_BOOT_DESKTOP_CONTRACT=absent" in res["stdout"]


class TestFailurePaths:
    def test_passphrase_prompt_never_appears_exits_2(self):
        res = _run(_argv(timeout="30"), serial_chunks=[])
        assert res["exit_code"] == 2
        assert "passphrase prompt never appeared" in res["stdout"]

    def test_unlock_but_never_userspace_exits_3(self):
        res = _run(
            _argv(timeout="30"),
            serial_chunks=[b"Passphrase for disk root:"],
        )
        assert res["exit_code"] == 3
        assert "never reached userspace" in res["stdout"]

    def test_emergency_shell_harvests_diagnostics_and_exits_3(self):
        res = _run(
            _argv(timeout="120"),
            serial_chunks=[
                b"Passphrase for disk root:",
                b"[FAILED] Failed to start Switch Root.\nEntering emergency mode.",
                b"rdsosreport.txt: a dump line\n",
                b"journal: another line\n",
            ],
        )
        assert res["exit_code"] == 3
        assert "emergency shell detected" in res["stdout"]
        assert "cat /run/initramfs/rdsosreport.txt" in res["serial_sent"]
        assert "journalctl -b" in res["serial_sent"]
        # Harvested report data is streamed to stdout during the drain.
        assert "a dump line" in res["stdout"]
        assert "another line" in res["stdout"]

    def test_powerdown_send_failure_is_benign(self):
        # The monitor powerdown is best-effort: a send failure prints a note
        # and the script still exits 0 with the machine-readable contract line.
        res = _run(_argv(), monitor_send_fail=True,
                   serial_chunks=[b"Passphrase for disk root:", b"login: "])
        assert res["exit_code"] == 0
        assert "powerdown note:" in res["stdout"]
        assert "LUKS_FIRST_BOOT_DESKTOP_CONTRACT=absent" in res["stdout"]

    def test_serial_socket_unreachable_fails_fast(self):
        # connect() retries 60x then raises SystemExit directly (not sys.exit).
        res = _run(_argv(), serial_fail=True)
        assert res["exit_code"] == 1


class TestContractDetection:
    def test_contract_fail_is_reported_as_fail(self):
        res = _run(
            _argv(),
            serial_chunks=[
                b"Passphrase for disk root:",
                b"login: ",
                b"TUNAOS_DESKTOP_CONTRACT_FAIL\n",
            ],
        )
        assert res["exit_code"] == 0
        assert "LUKS_FIRST_BOOT_DESKTOP_CONTRACT=fail" in res["stdout"]

    def test_login_detected_via_multi_user_target(self):
        res = _run(
            _argv(),
            serial_chunks=[
                b"Passphrase for disk root:",
                b"Reached target Multi-User System.",
                b"TUNAOS_DESKTOP_CONTRACT_OK",
            ],
        )
        assert res["exit_code"] == 0
        assert "LUKS_FIRST_BOOT_DESKTOP_CONTRACT=ok" in res["stdout"]

    def test_contract_marker_beyond_4000_byte_window_is_still_found(self):
        # The script scans the WHOLE buffer (not just the rolling 4000-byte
        # text window) for the contract marker. Deliver the marker inside a
        # chunk whose tail pushes it outside the rolling window; it must still
        # be detected when the login-line check has already passed.
        padding = b"x" * 5000
        res = _run(
            _argv(),
            serial_chunks=[
                b"Passphrase for disk root:",
                b"login: ",
                padding,
                b"TUNAOS_DESKTOP_CONTRACT_OK" + padding,
            ],
        )
        assert res["exit_code"] == 0
        assert "LUKS_FIRST_BOOT_DESKTOP_CONTRACT=ok" in res["stdout"]


# ── Per-boot GRUB kernel arguments (strict GUI LUKS leg) ─────────────────────

GRUB_APPEND = "console=ttyS0,115200n8 rd.plymouth=0 plymouth.enable=0"
GRUB_MENU = (
    b"\x1b[02;42HGRUB version 2.12\r\n\x1b[04;02H"
    b"      Press enter to boot the selected OS, `e' to edit the commands "
    b"before booting or `c' for \r\n\x1b[05;03H*Skipjack (ostree:0)"
)
BLS_EDITOR = (
    b"\x1b[02;03Hload_video\x1b[03;03Hset gfxpayload=keep\x1b[04;03Hinsmod gzio"
    b"\x1b[05;03Hlinux ($root)/ostree/default-x/vmlinuz root=UUID=1 rw rhgb quiet"
    b" rd.luks.name=abc=root\x1b[06;03Hinitrd ($root)/ostree/default-x/initramfs.img"
    b"\x1b[20;03HMinimum Emacs-like screen editing is supported. Press Ctrl-x or F10 to boot"
)


class TestGrubAppend:
    def test_appends_to_the_linux_line_then_unlocks(self, monkeypatch):
        monkeypatch.setenv("TUNAOS_LUKS_GRUB_APPEND", GRUB_APPEND)
        res = _run(
            _argv(),
            serial_chunks=[
                GRUB_MENU,
                BLS_EDITOR,
                b"Please enter passphrase for disk root:",
                b"skipjack login: ",
            ],
        )
        assert res["exit_code"] == 0
        # e, Ctrl-N past the three blscfg preamble lines, Ctrl-E, the kargs,
        # Ctrl-X, then the passphrase at the prompt that now reaches serial.
        assert res["serial_sent"] == (
            "e" + "\x0e" * 3 + "\x05" + " " + GRUB_APPEND + "\x18" + "testpass\n"
        )

    def test_unknown_entry_layout_exits_5_without_typing(self, monkeypatch):
        monkeypatch.setenv("TUNAOS_LUKS_GRUB_APPEND", GRUB_APPEND)
        editor = b"\x1b[02;03Hsetparams 'Skipjack'" + BLS_EDITOR
        res = _run(_argv(), serial_chunks=[GRUB_MENU, editor])
        assert res["exit_code"] == 5
        assert res["serial_sent"] == "e"
        assert "not the blscfg layout" in res["stdout"]

    def test_editor_that_never_opens_exits_5(self, monkeypatch):
        monkeypatch.setenv("TUNAOS_LUKS_GRUB_APPEND", GRUB_APPEND)
        res = _run(_argv(), serial_chunks=[GRUB_MENU])
        assert res["exit_code"] == 5
        assert res["serial_sent"] == "e"
        assert "did not open with a linux line" in res["stdout"]

    def test_unset_leaves_grub_alone(self, monkeypatch):
        monkeypatch.delenv("TUNAOS_LUKS_GRUB_APPEND", raising=False)
        res = _run(
            _argv(),
            serial_chunks=[GRUB_MENU, b"Passphrase for disk root:", b"login: "],
        )
        assert res["exit_code"] == 0
        assert res["serial_sent"] == "testpass\n"


@pytest.mark.parametrize('preamble', [
    b'\nload_video\nset gfxpayload=keep\ninsmod gzio\n',
    b'\x1b[02;03H\nload_video\nset gfxpayload=keep\ninsmod gzio\n',
    b'load_video\nset gfxpayload=keep\ninsmod gzio\nsearch --fs-uuid --set=root deadbeef\n',
    b'search --fs-uuid --set=root deadbeef\nload_video\nset gfxpayload=keep\ninsmod gzio\n',
    b'load_video\ninsmod gzio\nset gfxpayload=keep\n',
    b'load_video; reboot\nset gfxpayload=keep\ninsmod gzio\n',
    b'load_video\nset gfxpayload=keep\n\ninsmod gzio\n',
    b'load_video\nset gfxpayload=keep\ninsmod gzio\n\n',
])
def test_grub_refuses_nonexact_preamble_before_cursor_or_argument_input(monkeypatch, preamble):
    monkeypatch.setenv('TUNAOS_LUKS_GRUB_APPEND', GRUB_APPEND)
    editor = preamble + b'linux /vmlinuz root=UUID=1\ninitrd /initramfs.img\n'
    result = _run(_argv(), serial_chunks=[GRUB_MENU, editor])
    assert result['exit_code'] == 5
    assert result['serial_sent'] == 'e'


def test_manual_fixture_invocation_reaches_real_driver_with_stdin_secret():
    """Execute its real shell command and Python entry point, with zero boot wait."""
    import socket
    import subprocess
    import tempfile

    root = SCRIPT.parents[1]
    manual = (root / 'tests/manual/luks-first-boot-contract.sh').read_text()
    invocation = next(line.strip() for line in manual.splitlines() if line.strip().startswith('out=$('))
    # Only the observation duration changes. Parsing, pipe, argv and stdin are real.
    invocation = invocation.replace('180 20', '0 0')
    with tempfile.TemporaryDirectory(prefix='luks-contract-', dir='/tmp') as directory:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as serial:
            serial.bind(directory + '/ser.sock')
            serial.listen(1)
            result = subprocess.run(
                ['bash', '-c', invocation + '\nrc=$?; printf "%s" "$out"; exit "$rc"'],
                cwd=root, env={**os.environ, 'd': directory}, capture_output=True,
                text=True, timeout=5,
            )
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'passphrase prompt never appeared' in result.stdout
    assert 'testpass' not in result.stdout + result.stderr
