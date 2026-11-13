"""The EL10 live XFCE session reports its own output on the serial console.

yellowfin-xfce (iso-builder run 43429679278) showed 30 black frames and the
serial log held nothing from the compositor: greetd captures no output and the
strict harness runs nothing in the guest.
"""
import subprocess
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1] / "live-iso" / "common" / "src" / "desktop-xfce.sh"


def _report_script():
    text = ADAPTER.read_text()
    start = text.index("<<'REPORTEOF'\n") + len("<<'REPORTEOF'\n")
    return text[start:text.index("\nREPORTEOF", start)]


def test_the_report_reads_the_compositor_journal_tag_and_greetd():
    """Falsification: dropping `-t tunaos-live-session` leaves the compositor's
    own output, the only evidence of why it died, out of the serial log."""
    script = _report_script()
    assert "-t tunaos-live-session" in script
    assert "-u greetd.service" in script
    assert "/dev/ttyS0" in script


def test_the_report_is_silent_without_a_serial_console(tmp_path):
    """Falsification: without the console=ttyS guard a real machine's
    first-boot console fills with diagnostics."""
    script = tmp_path / "report"
    script.write_text(_report_script())
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert result.stdout == "" and result.stderr == ""


def test_the_report_is_wired_to_a_timer_in_the_wayland_branch():
    text = ADAPTER.read_text()
    assert "systemctl enable tunaos-xfce-live-session-report.timer" in text
    assert text.index("REPORTEOF") < text.index("# ── X11 fallback")
