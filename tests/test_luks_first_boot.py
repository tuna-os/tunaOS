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
import sys
from io import BytesIO
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "luks-first-boot.py"


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
    argv = ["luks-first-boot.py", "/tmp/serial.sock", "/tmp/monitor.sock", passphrase, timeout]
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
