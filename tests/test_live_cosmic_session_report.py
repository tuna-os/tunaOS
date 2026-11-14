"""The COSMIC live session reports itself on the serial console.

sailfin-cosmic stayed black in two strict runs (43356224963, 43568760716) with a green
desktop contract and nothing from the compositor in the serial log (tunaOS#4538).
greetd captures nothing, so the adapter copies greetd's state and the
`tunaos-live-session` journal to ttyS0 on a timer, as the XFCE adapter does.

Falsification: drop the report script or its timer enable from desktop-cosmic.sh and
this test fails; remove the `-t tunaos-live-session` section and the second test fails.
"""

from pathlib import Path

ADAPTER = (Path(__file__).parents[1] / "live-iso/common/src/desktop-cosmic.sh").read_text()


def test_report_is_installed_and_timer_enabled():
    assert "/usr/libexec/tunaos/cosmic-live-session-report" in ADAPTER
    assert "tunaos-cosmic-live-session-report.timer" in ADAPTER
    assert "systemctl enable tunaos-cosmic-live-session-report.timer" in ADAPTER


def test_report_carries_the_compositor_journal_and_greetd_state():
    assert "journalctl -b --no-pager -n 80 -t tunaos-live-session" in ADAPTER
    assert "systemctl status greetd.service" in ADAPTER
    assert "/dev/ttyS0" in ADAPTER
