"""Inert frame/monitor/OCR replays; never connects to QEMU or a network."""

import importlib.util
import json
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "observer", ROOT / "scripts/observe-installed-boot.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.mark.parametrize(
    "text,label",
    [
        ("Please enter passphrase for disk root:", "disk_passphrase_prompt"),
        ("Unlock disk encrypted-root:", "disk_passphrase_prompt"),
        ("host login:", "login"),
        ("GNU GRUB", "grub"),
        ("[0.1] virt/tdx: TDX not supported by the host platform", "tdx_warning"),
        ("Entering emergency mode", "emergency"),
        ("", "unknown"),
        ("Password:", "unknown"),
        ("My login passphrase is hidden", "unknown"),
        (
            "Please enter passphrase for disk root:\nEntering emergency mode",
            "emergency",
        ),
    ],
)
def test_classifier(text, label):
    assert m.classify(text) == label


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/a;quit",
        "/tmp/a\nquit",
        "/tmp/a b",
        "/tmp/../etc/a",
        "relative",
        '/tmp/"a"',
        "/tmp/a\\b",
    ],
)
def test_path_injection_refused(path):
    with pytest.raises(m.ObservationError):
        m.safe_path(path)


def test_symlink_path_refused(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(m.ObservationError, match="symlink"):
        m.safe_path(link / "frame")


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def replay(tmp_path, texts, changing=True, **kwargs):
    clock = Clock()
    calls = []

    def capture(monitor, path, deadline):
        calls.append((monitor, path, deadline))
        path.write_bytes(
            b"P6\n1 1\n255\n" + bytes([len(calls) if changing else 0, 0, 0])
        )

    def ocr(path, deadline):
        return texts[min(len(calls) - 1, len(texts) - 1)]

    result = m.observe(
        "/tmp/inert-monitor.sock",
        tmp_path / "out",
        capture=capture,
        ocr=ocr,
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )
    assert json.loads((tmp_path / "out/observations.json").read_text()) == result
    return result, calls


def test_prompt_observation_is_never_qualification(tmp_path):
    result, calls = replay(
        tmp_path,
        [
            "TDX not supported by the host platform",
            "Please enter passphrase for disk root:",
        ],
    )
    assert result["status"] == "disk_passphrase_prompt_observed"
    assert result["qualified"] is False and len(calls) == 2


def test_credentials_and_ocr_text_are_never_logged(tmp_path, capsys):
    result, _ = replay(tmp_path, ["SECRET_SENTINEL unknown output"], max_frames=1)
    assert "SECRET_SENTINEL" not in json.dumps(result)
    assert "SECRET_SENTINEL" not in capsys.readouterr().out


def test_unknown_frame_stops_at_count_bound(tmp_path):
    result, calls = replay(tmp_path, ["unrecognized"], max_frames=3)
    assert result["status"] == "frame_limit_reached" and len(calls) == 3
    assert result["qualified"] is False


def test_identical_frames_hit_idle_bound(tmp_path):
    result, calls = replay(
        tmp_path, ["black"], changing=False, idle_timeout=10, interval=5
    )
    assert result["status"] == "unchanged_frame_timeout" and len(calls) == 2


def test_total_deadline_spans_all_frames(tmp_path):
    result, calls = replay(tmp_path, ["black"], timeout=10, idle_timeout=10, interval=5)
    assert result["status"] == "deadline_expired" and len(calls) == 2


def test_capture_failure_is_durable(tmp_path):
    def capture(*args):
        raise m.ObservationError("vnc_timeout")

    result = m.observe("/tmp/inert.sock", tmp_path / "out", capture=capture)
    assert result["status"] == "observation_failed"
    assert result["error_category"] == "vnc_timeout"
    assert json.loads((tmp_path / "out/observations.json").read_text()) == result


def test_oversized_frame_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MAX_FRAME_BYTES", 8)

    def capture(monitor, path, deadline):
        path.write_bytes(b"x" * 9)

    result = m.observe("/tmp/inert.sock", tmp_path / "out", capture=capture)
    assert result["status"] == "observation_failed"
    assert not list((tmp_path / "out").glob("*.ppm"))


def test_cancel_is_durable(tmp_path):
    def capture(*args):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        m.observe("/tmp/inert.sock", tmp_path / "out", capture=capture)
    assert (
        json.loads((tmp_path / "out/observations.json").read_text())["status"]
        == "cancelled"
    )


def test_expired_ocr_budget_cannot_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(m.shutil, "which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(
        m.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn")
    )
    with pytest.raises(m.ObservationError, match="ocr_timeout"):
        m.ocr_frame(tmp_path / "frame.ppm", 0)


def test_invalid_image_refused_before_ocr(tmp_path):
    def capture(monitor, path, deadline):
        path.write_bytes(b"not a PPM")

    def ocr(*args):
        pytest.fail("must not OCR malformed data")

    result = m.observe("/tmp/inert.sock", tmp_path / "out", capture=capture, ocr=ocr)
    assert result["error_category"] == "invalid_frame_header"


@pytest.mark.parametrize(
    "error", [RuntimeError("SECRET_SENTINEL"), m.ObservationError("SECRET_SENTINEL")]
)
def test_unknown_errors_are_secret_safe(tmp_path, error):
    def capture(*args):
        raise error

    result = m.observe("/tmp/inert.sock", tmp_path / "out", capture=capture)
    assert result["status"] == "observation_failed"
    assert result["error_category"] == "observer_internal_error"
    assert "SECRET_SENTINEL" not in json.dumps(result)


def test_ocr_timeout_after_capture_is_terminal(tmp_path):
    def capture(monitor, path, deadline):
        path.write_bytes(b"P6\n1 1\n255\n\0\0\0")

    def ocr(*args):
        raise m.ObservationError("ocr_timeout")

    result = m.observe("/tmp/inert.sock", tmp_path / "out", capture=capture, ocr=ocr)
    assert (
        result["status"] == "observation_failed"
        and result["error_category"] == "ocr_timeout"
    )


@pytest.mark.parametrize(
    "program,category",
    [
        ("import time;time.sleep(10)", "ocr_timeout"),
        ('import sys;sys.stdout.write("x"*9000)', "ocr_output_limit"),
        ('import sys;sys.stderr.write("SECRET_SENTINEL");sys.exit(7)', "ocr_failed"),
    ],
)
def test_real_ocr_subprocess_bounds_with_inert_executable(
    tmp_path, monkeypatch, program, category
):
    fake = tmp_path / "fake-ocr"
    fake.write_text("#!/usr/bin/python3\n" + program + "\n")
    fake.chmod(0o700)
    monkeypatch.setattr(m.shutil, "which", lambda _: str(fake))
    started = time.monotonic()
    with pytest.raises(m.ObservationError, match=category) as error:
        m.ocr_frame(tmp_path / "unused.ppm", started + 0.3)
    assert time.monotonic() - started < 3
    assert "SECRET_SENTINEL" not in str(error.value)


def test_ocr_process_cancel_kills_and_reaps(monkeypatch, tmp_path):
    calls = []

    class Process:
        stdout = object()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def kill(self):
            calls.append("kill")

        def wait(self, **kwargs):
            calls.append("wait")
            return 0

    class Selector:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            pass

        def get_map(self):
            return {1: True}

        def select(self, *args):
            raise KeyboardInterrupt()

    monkeypatch.setattr(m.shutil, "which", lambda _: "/inert/ocr")
    monkeypatch.setattr(m.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(m.selectors, "DefaultSelector", Selector)
    with pytest.raises(KeyboardInterrupt):
        m.ocr_frame(tmp_path / "unused.ppm", time.monotonic() + 3)
    assert calls == ["kill", "wait"]
