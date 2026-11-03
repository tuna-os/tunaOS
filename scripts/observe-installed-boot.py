#!/usr/bin/env python3
"""Observe installed boot pixels; never send guest input or qualify a boot.

Only shared, read-only RFB framebuffer requests are sent. OCR text is
classified in memory and discarded. Complete bounded frames are written by
this host process; neither HMP nor guest input commands are used.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import selectors
import shutil
import signal
import socket
import stat
import struct
import subprocess
import time
from pathlib import Path

MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_OCR_BYTES = 8192
MAX_RECTANGLES = 4096
MAX_FRAMES = 6

# Reuse only the audited deadline-bound RFB transport primitives. No input
# helpers are called. The standalone workspace links this existing module;
# repository integration uses its normal scripts/lib location.
_driver_spec = importlib.util.spec_from_file_location(
    "observer_rfb_transport", Path(__file__).parent / "lib/gnome_installer_driver.py"
)
_driver = importlib.util.module_from_spec(_driver_spec)
_driver_spec.loader.exec_module(_driver)
ERROR_CATEGORIES = frozenset(
    {
        "vnc_protocol",
        "vnc_auth",
        "vnc_geometry",
        "vnc_name_limit",
        "vnc_update",
        "vnc_rectangle",
        "vnc_overlap",
        "vnc_incomplete",
        "vnc_byte_limit",
        "vnc_io_error",
        "vnc_transport_failed",
        "not_owned_vnc_socket",
        "vnc_timeout",
        "frame_already_exists",
        "invalid_frame_size_or_type",
        "invalid_frame_header",
        "frame_dimensions_limit",
        "invalid_frame_payload",
        "ocr_unavailable",
        "ocr_timeout",
        "ocr_output_limit",
        "ocr_failed",
        "ocr_io_error",
        "unsafe_path",
        "symlink_path",
    }
)


class ObservationError(Exception):
    """Only fixed, non-secret category strings may be supplied."""


def safe_path(value):
    """Keep local artifact paths simple; reject traversal and symbolic links."""
    value = str(value)
    if (
        not re.fullmatch(r"/[A-Za-z0-9_./-]+", value)
        or ".." in value.split("/")
        or len(value) > 200
    ):
        raise ObservationError("unsafe_path")
    path = Path(value)
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ObservationError("symlink_path")
    return path


def classify(text):
    """Conservative evidence labels, not unlock/desktop success judgments."""
    lines = [" ".join(line.lower().split()) for line in text.splitlines()]
    if any("emergency mode" in line or "emergency shell" in line for line in lines):
        return "emergency"
    if any("gnu grub" in line or "advanced options for" in line for line in lines):
        return "grub"
    if any(
        re.fullmatch(r"(?:please )?enter passphrase for disk [^\r\n:]{1,160}:?", line)
        or re.fullmatch(r"(?:please )?unlock disk [^\r\n:]{1,160}:?", line)
        for line in lines
    ):
        return "disk_passphrase_prompt"
    if any(re.fullmatch(r"(?:[a-z0-9_.-]+ )?login:", line) for line in lines):
        return "login"
    if any("tdx not supported by the host platform" in line for line in lines):
        return "tdx_warning"
    return "unknown"


def vnc_capture(vnc, frame, deadline):
    """Shared RFB 3.8 raw capture; no pointer, keyboard, clipboard or HMP."""
    vnc, frame = safe_path(vnc), safe_path(frame)
    if frame.exists():
        raise ObservationError("frame_already_exists")
    info = vnc.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise ObservationError("not_owned_vnc_socket")
    deadline = min(deadline, time.monotonic() + 5)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ObservationError("vnc_timeout")
            sock.settimeout(remaining)
            sock.connect(str(vnc))

            def read(size):
                return _driver._read(sock, size, deadline)

            def send(data):
                _driver._send(sock, data, deadline)

            if read(12) != b"RFB 003.008\n":
                raise ObservationError("vnc_protocol")
            send(b"RFB 003.008\n")
            count = read(1)[0]
            if not 0 < count <= 16 or 1 not in read(count):
                raise ObservationError("vnc_auth")
            send(b"\x01")
            if read(4) != b"\0\0\0\0":
                raise ObservationError("vnc_auth")
            send(b"\x01")  # ClientInit shared=1: do not evict other clients.
            init = read(24)
            width, height = struct.unpack("!HH", init[:4])
            name_length = struct.unpack("!I", init[20:24])[0]
            if not (1 <= width <= 1920 and 1 <= height <= 1080):
                raise ObservationError("vnc_geometry")
            if name_length > 4096:
                raise ObservationError("vnc_name_limit")
            read(name_length)  # Never persist the server-supplied name.
            # 32bpp little-endian true-colour RGB888 => wire B,G,R,padding.
            pixel_format = struct.pack(
                "!BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0
            )
            send(b"\x00\0\0\0" + pixel_format)  # SetPixelFormat
            send(struct.pack("!BBHi", 2, 0, 1, 0))  # SetEncodings: raw only
            send(struct.pack("!BBHHHH", 3, 0, 0, 0, width, height))
            kind, _, count = struct.unpack("!BBH", read(4))
            if kind != 0 or not 1 <= count <= MAX_RECTANGLES:
                raise ObservationError("vnc_update")
            rgb = bytearray(width * height * 3)
            coverage = bytearray(width * height)
            covered = 0
            wire_bytes = 4
            for _ in range(count):
                x, y, w, h, encoding = struct.unpack("!HHHHi", read(12))
                if encoding != 0 or not (
                    w > 0 and h > 0 and x + w <= width and y + h <= height
                ):
                    raise ObservationError("vnc_rectangle")
                wire_bytes += 12 + w * h * 4
                if wire_bytes > MAX_FRAME_BYTES:
                    raise ObservationError("vnc_byte_limit")
                raw = read(w * h * 4)
                for row in range(h):
                    if time.monotonic() >= deadline:
                        raise ObservationError("vnc_timeout")
                    start = (y + row) * width + x
                    if any(coverage[start : start + w]):
                        raise ObservationError("vnc_overlap")
                    coverage[start : start + w] = b"\1" * w
                    source = raw[row * w * 4 : (row + 1) * w * 4]
                    target = start * 3
                    rgb[target : target + w * 3 : 3] = source[2::4]
                    rgb[target + 1 : target + w * 3 : 3] = source[1::4]
                    rgb[target + 2 : target + w * 3 : 3] = source[0::4]
                    covered += w
            if covered != width * height:
                raise ObservationError("vnc_incomplete")
        header = f"P6\n{width} {height}\n255\n".encode("ascii")
        if len(header) + len(rgb) > MAX_FRAME_BYTES:
            raise ObservationError("vnc_byte_limit")
        if time.monotonic() >= deadline:
            raise ObservationError("vnc_timeout")
        with frame.open("xb") as stream:
            stream.write(header)
            stream.write(rgb)
    except _driver.Unverified:
        raise ObservationError("vnc_transport_failed") from None
    except (OSError, TimeoutError):
        raise ObservationError("vnc_io_error") from None


def frame_digest(path):
    """Accept only one bounded regular QEMU P6 frame, not arbitrary OCR input."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FRAME_BYTES:
        raise ObservationError("invalid_frame_size_or_type")
    with path.open("rb") as stream:
        data = stream.read(MAX_FRAME_BYTES + 1)
    if len(data) > MAX_FRAME_BYTES:
        raise ObservationError("invalid_frame_size_or_type")
    header = re.match(rb"P6\n([0-9]{1,4}) ([0-9]{1,4})\n255\n", data[:64])
    if not header:
        raise ObservationError("invalid_frame_header")
    width, height = map(int, header.groups())
    if not (1 <= width <= 1920 and 1 <= height <= 1080):
        raise ObservationError("frame_dimensions_limit")
    if len(data) != header.end() + width * height * 3:
        raise ObservationError("invalid_frame_payload")
    return hashlib.sha256(data).hexdigest()


def ocr_frame(path, deadline):
    """Bound OCR process time and output, never forward its stdout/stderr."""
    executable = shutil.which("tesseract")
    if executable is None:
        raise ObservationError("ocr_unavailable")
    deadline = min(deadline, time.monotonic() + 10)
    if time.monotonic() >= deadline:
        raise ObservationError("ocr_timeout")
    data = bytearray()
    try:
        with subprocess.Popen(
            [executable, str(path), "stdout", "--psm", "6"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "C.UTF-8", "OMP_THREAD_LIMIT": "1"},
        ) as process:
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    idle = time.monotonic() + 5
                    while selector.get_map():
                        remaining = min(deadline, idle) - time.monotonic()
                        if remaining <= 0:
                            raise ObservationError("ocr_timeout")
                        for key, _ in selector.select(min(remaining, 0.2)):
                            chunk = os.read(key.fd, 4096)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            data.extend(chunk)
                            idle = time.monotonic() + 5
                            if len(data) > MAX_OCR_BYTES:
                                raise ObservationError("ocr_output_limit")
                if process.wait(timeout=max(0.001, deadline - time.monotonic())):
                    raise ObservationError("ocr_failed")
            except BaseException:
                process.kill()
                process.wait()
                raise
    except subprocess.TimeoutExpired:
        raise ObservationError("ocr_timeout") from None
    except OSError:
        raise ObservationError("ocr_io_error") from None
    return data.decode("utf-8", "replace")


def write_report(directory, report):
    temporary = directory / "observations.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(directory / "observations.json")
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def observe(
    vnc,
    output,
    timeout=120,
    idle_timeout=30,
    interval=20,
    max_frames=MAX_FRAMES,
    capture=vnc_capture,
    ocr=ocr_frame,
    clock=time.monotonic,
    sleep=time.sleep,
):
    """Run bounded read-only observation; every result remains unqualified."""
    if (
        not 1 <= timeout <= 120
        or not 1 <= idle_timeout <= timeout
        or not 1 <= interval <= 30
        or not 1 <= max_frames <= MAX_FRAMES
    ):
        raise ObservationError("invalid_budget")
    output = safe_path(output)
    vnc = safe_path(vnc)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    report = {
        "kind": "installed_boot_observation",
        "qualified": False,
        "status": "observing",
        "frames": [],
    }
    started = clock()
    deadline = started + timeout
    last_change = started
    previous = None
    frame = None
    write_report(output, report)
    try:
        for index in range(max_frames):
            if clock() >= deadline:
                report["status"] = "deadline_expired"
                break
            if clock() >= last_change + idle_timeout:
                report["status"] = "unchanged_frame_timeout"
                break
            frame = output / f"frame-{index:03}.ppm"
            operation_deadline = min(deadline, last_change + idle_timeout)
            capture(vnc, frame, min(operation_deadline, clock() + 5))
            digest = frame_digest(frame)
            if digest != previous:
                last_change = clock()
                previous = digest
            label = classify(ocr(frame, min(deadline, last_change + idle_timeout)))
            if clock() >= deadline:
                report["status"] = "deadline_expired"
                break
            report["frames"].append(
                {
                    "file": frame.name,
                    "sha256": digest,
                    "elapsed_seconds": round(clock() - started, 3),
                    "classification": label,
                }
            )
            write_report(output, report)
            if label in ("disk_passphrase_prompt", "emergency"):
                report["status"] = label + "_observed"
                break
            if index == max_frames - 1:
                report["status"] = "frame_limit_reached"
                break
            sleep(
                min(
                    interval,
                    max(0, min(deadline, last_change + idle_timeout) - clock()),
                )
            )
    except ObservationError as error:
        report["status"] = "observation_failed"
        category = str(error)
        report["error_category"] = (
            category if category in ERROR_CATEGORIES else "observer_internal_error"
        )
        if (
            frame is not None
            and frame.exists()
            and frame.stat().st_size > MAX_FRAME_BYTES
        ):
            frame.unlink()
    except (OSError, ValueError):
        report["status"] = "observation_failed"
        report["error_category"] = "local_io_error"
    except Exception:  # noqa: BLE001 - boundary: persist only a fixed label, never secret-bearing errors
        report["status"] = "observation_failed"
        report["error_category"] = "observer_internal_error"
    except BaseException:
        report["status"] = "cancelled"
        write_report(output, report)
        raise
    write_report(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vnc", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    def cancelled(signum, frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, cancelled)
    try:
        result = observe(
            args.vnc, args.output, args.timeout, idle_timeout=min(30, args.timeout)
        )
    except KeyboardInterrupt:
        print(json.dumps({"status": "cancelled", "qualified": False}))
        return 130
    except (ObservationError, OSError):
        print("observer_setup_failed")
        return 2
    print(json.dumps({"status": result["status"], "qualified": False}))
    return 2 if result["status"] in ("observation_failed", "cancelled") else 0


if __name__ == "__main__":
    raise SystemExit(main())
