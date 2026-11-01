"""Inert byte-stream RFB replays; no socket connections or guest execution."""

import importlib.util
import os
import stat
import struct
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "vnc_observer", ROOT / "scripts/observe-installed-boot.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def init(width=2, height=1, name=b"fixture", length=None):
    return (
        struct.pack("!HH", width, height)
        + b"\0" * 16
        + struct.pack("!I", len(name) if length is None else length)
        + name
    )


def rectangle(x=0, y=0, width=2, height=1, encoding=0, pixels=None):
    if pixels is None:
        pixels = b"\x01\x02\x03\0" * (width * height)
    return struct.pack("!HHHHi", x, y, width, height, encoding) + pixels


def wire(server_init=None, rectangles=None, count=None, kind=0):
    rectangles = [rectangle()] if rectangles is None else rectangles
    return (
        b"RFB 003.008\n\x01\x01"
        + b"\0" * 4
        + (init() if server_init is None else server_init)
        + struct.pack("!BBH", kind, 0, len(rectangles) if count is None else count)
        + b"".join(rectangles)
    )


def fake_transport(monkeypatch, payload, uid=None):
    class FakeSocket:
        def __init__(self):
            self.payload = payload
            self.sent = []
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def settimeout(self, value):
            assert 0 < value <= 5

        def connect(self, value):
            assert value == "/tmp/owned-vnc.sock"

        def recv(self, limit):
            # Fragment all responses, exercising the reused exact-read helper.
            result, self.payload = (
                self.payload[: min(limit, 3)],
                self.payload[min(limit, 3) :],
            )
            return result

        def sendall(self, data):
            self.sent.append(data)

    fake = FakeSocket()
    original = Path.lstat

    def lstat(path):
        if str(path) == "/tmp/owned-vnc.sock":
            return type(
                "Info",
                (),
                {
                    "st_mode": stat.S_IFSOCK,
                    "st_uid": os.getuid() if uid is None else uid,
                },
            )()
        return original(path)

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(m.socket, "socket", lambda *a: fake)
    return fake


def test_exact_readonly_protocol_and_pixels(tmp_path, monkeypatch):
    fake = fake_transport(monkeypatch, wire())
    path = tmp_path / "frame.ppm"
    m.vnc_capture("/tmp/owned-vnc.sock", path, time.monotonic() + 5)
    assert path.read_bytes() == b"P6\n2 1\n255\n" + b"\x03\x02\x01" * 2
    assert fake.closed
    assert fake.sent[:3] == [b"RFB 003.008\n", b"\x01", b"\x01"]
    pixel_format = struct.pack("!BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
    assert fake.sent[3:] == [
        b"\0" * 4 + pixel_format,
        struct.pack("!BBHi", 2, 0, 1, 0),
        struct.pack("!BBHHHH", 3, 0, 0, 0, 2, 1),
    ]
    # Exact whitelist excludes KeyEvent(4), PointerEvent(5), ClientCutText(6).
    assert [item[0] for item in fake.sent[3:]] == [0, 2, 3]


@pytest.mark.parametrize(
    "payload,category",
    [
        (b"RFB 003.007\n", "vnc_protocol"),
        (b"RFB 003.008\n\x01\x02", "vnc_auth"),
        (b"RFB 003.008\n\x00", "vnc_auth"),
        (b"RFB 003.008\n\x11", "vnc_auth"),
        (b"RFB 003.008\n\x01\x01\0\0\0\x01", "vnc_auth"),
        (wire(server_init=init(width=1921)), "vnc_geometry"),
        (wire(server_init=init(height=1081)), "vnc_geometry"),
        (wire(server_init=init(width=0)), "vnc_geometry"),
        (wire(server_init=init(length=4097)), "vnc_name_limit"),
        (wire(kind=2), "vnc_update"),
        (wire(count=0), "vnc_update"),
        (wire(count=4097), "vnc_update"),
        (wire(rectangles=[rectangle(encoding=1)]), "vnc_rectangle"),
        (wire(rectangles=[rectangle(encoding=-223)]), "vnc_rectangle"),
        (wire(rectangles=[rectangle(x=1)]), "vnc_rectangle"),
        (wire(rectangles=[rectangle(width=0)]), "vnc_rectangle"),
        (wire(rectangles=[rectangle(width=1)]), "vnc_incomplete"),
        (wire(rectangles=[rectangle(), rectangle(width=1)]), "vnc_overlap"),
        (wire()[:-1], "vnc_transport_failed"),
    ],
)
def test_invalid_protocol_never_writes_frame(tmp_path, monkeypatch, payload, category):
    fake = fake_transport(monkeypatch, payload)
    path = tmp_path / "frame.ppm"
    with pytest.raises(m.ObservationError, match=category):
        m.vnc_capture("/tmp/owned-vnc.sock", path, time.monotonic() + 5)
    assert fake.closed and not path.exists()


def test_tiled_complete_frame_is_accepted(tmp_path, monkeypatch):
    fake_transport(
        monkeypatch, wire(rectangles=[rectangle(width=1), rectangle(x=1, width=1)])
    )
    path = tmp_path / "frame.ppm"
    m.vnc_capture("/tmp/owned-vnc.sock", path, time.monotonic() + 5)
    assert m.frame_digest(path)


def test_byte_budget_includes_rectangle_headers(tmp_path, monkeypatch):
    fake_transport(monkeypatch, wire())
    monkeypatch.setattr(
        m, "MAX_FRAME_BYTES", 23
    )  # 4 update + 12 rectangle + 8 pixels = 24
    with pytest.raises(m.ObservationError, match="vnc_byte_limit"):
        m.vnc_capture(
            "/tmp/owned-vnc.sock", tmp_path / "frame.ppm", time.monotonic() + 5
        )


def test_owned_socket_required(tmp_path, monkeypatch):
    fake = fake_transport(monkeypatch, wire(), uid=os.getuid() + 1)
    with pytest.raises(m.ObservationError, match="not_owned_vnc_socket"):
        m.vnc_capture(
            "/tmp/owned-vnc.sock", tmp_path / "frame.ppm", time.monotonic() + 5
        )
    assert fake.sent == []


def test_transaction_deadline_is_not_reset_by_reads(tmp_path, monkeypatch):
    fake = fake_transport(monkeypatch, wire())
    now = [0.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: now[0])
    original = fake.recv

    def recv(limit):
        result = original(limit)
        now[0] += 0.4
        return result

    fake.recv = recv
    with pytest.raises(m.ObservationError, match="vnc_transport_failed"):
        m.vnc_capture("/tmp/owned-vnc.sock", tmp_path / "frame.ppm", 5)
    assert not (tmp_path / "frame.ppm").exists()


def test_cli_termination_has_no_traceback(monkeypatch, capsys):
    monkeypatch.setattr(
        m.argparse.ArgumentParser,
        "parse_args",
        lambda _: type(
            "Args", (), {"vnc": "/tmp/vnc.sock", "output": "/tmp/out", "timeout": 1}
        )(),
    )
    handlers = []
    monkeypatch.setattr(m.signal, "signal", lambda sig, fn: handlers.append(fn))

    def observe(*args, **kwargs):
        handlers[0](m.signal.SIGTERM, None)

    monkeypatch.setattr(m, "observe", observe)
    assert m.main() == 130
    output = capsys.readouterr()
    assert "cancelled" in output.out and "Traceback" not in output.err
