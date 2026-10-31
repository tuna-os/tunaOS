"""Inert frame/OCR primitives of the installed-boot screen reader.

The polling loop that used these lives in scripts/lib/luks_screen.py now and
is tested in tests/test_luks_screen_gate.py; this file never connects to QEMU.
"""

import importlib.util
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


def test_expired_ocr_budget_cannot_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(m.shutil, "which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(
        m.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn")
    )
    with pytest.raises(m.ObservationError, match="ocr_timeout"):
        m.ocr_frame(tmp_path / "frame.ppm", 0)


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
