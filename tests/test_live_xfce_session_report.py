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


def test_the_report_probes_fisherman_as_the_installer_does():
    """yellowfin-xfce on a GPU runner (iso-builder run 43528211405): XFCE
    painted and the installer opened, but its source page had no "(this system)"
    row, which means fisherman's probe failed or said "not live". The installer
    keeps no log the harness can read.

    Falsification: without the probe section, and the avc/fisherman journal
    filter, the next run again shows only the missing row.
    """
    script = _report_script()
    assert "probe --json" in script
    assert "runuser -u liveuser" in script
    assert "avc:  denied" in script


def test_the_report_replays_the_installers_flatpak_staging_on_the_session_bus(tmp_path):
    """The host-side probe passes on yellowfin-xfce (iso-builder run
    43560384928: is_live true, live_image set), yet the installer inside its
    Flatpak shows no "(this system)" row (run 43528211405). The difference is
    the Flatpak path: staging into the app cache and `flatpak-spawn --host` on
    the live session's D-Bus.

    Falsification: without the replay the report cannot tell a staging
    failure from a probe failure and the next run again shows only the
    missing row.
    """
    script = _report_script()
    assert "flatpak run --command=python3 org.tunaos.InstallerXfce" in script
    assert "DBUS_SESSION_BUS_ADDRESS" in script
    assert "core.staged_fisherman()" in script
    assert "core.probe()" in script
    path = tmp_path / "report"
    path.write_text(script)
    assert subprocess.run(["bash", "-n", str(path)], capture_output=True).returncode == 0


def test_the_greetd_session_command_sets_a_path():
    """yellowfin-xfce on a GPU runner (iso-builder run 43569256977): the
    installer's Flatpak runs fisherman through `flatpak-spawn --host`, and the
    probe died with `lsblk: exec: "lsblk": executable file not found in $PATH`
    while the same probe passed from a shell. `source_profile = false` leaves
    the greetd session no PATH, and the session bus helper inherits none.

    Falsification: drop `env PATH=` from the command and the installer's probe
    fails again, so its source page has no "(this system)" row.
    """
    text = ADAPTER.read_text()
    assert text.count("systemd-cat -t tunaos-live-session env PATH=${_xfce_session_path}${_xfce_env} dbus-run-session") == 2
    assert '_xfce_session_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"' in text
    # The e2e check reads the first word of the command as the session binary.
    assert 'command = "systemd-cat ' in text


def test_the_report_names_what_a_stalled_install_waits_on(tmp_path):
    """yellowfin-xfce on a GPU runner (iso-builder run 43597245663): the
    installer sat at "Installing bootloader via bootupd" (64%) for over an hour
    on both legs and the serial log held nothing from the install.

    Falsification: without the process, wchan and stack section, and timer
    firings after the install has started (900 s and later), a hung bootupd
    again leaves only an unchanging progress page.
    """
    script = _report_script()
    assert "/proc/${_pid}/stack" in script
    assert "bootupd|bootupctl|efibootmgr" in script
    timer = ADAPTER.read_text()
    for fire in ("OnBootSec=900s", "OnBootSec=1500s", "OnBootSec=2400s"):
        assert fire in timer
    path = tmp_path / "report"
    path.write_text(script)
    assert subprocess.run(["bash", "-n", str(path)], capture_output=True).returncode == 0


def test_the_report_prints_the_display_state_when_the_frame_freezes(tmp_path):
    """yellowfin-xfce on a GPU runner (iso-builder run 43615332319): the install
    finished by 692 s (target unmounted, no bootupd process at 900 s) but the
    frame stayed on "Installing bootloader via bootupd", and the kernel logged
    `kworker commit_work` blocked in `drm_atomic_helper_wait_for_fences`.

    Falsification: without the connector, D-state and compositor-thread
    sections, a frozen display and a stalled install look the same.
    """
    script = _report_script()
    assert "/sys/class/drm/card*-*" in script
    assert "dpms=" in script
    assert "xfwl4 thread" in script
    assert "awk '$2 ~ /D/'" in script
    path = tmp_path / "report"
    path.write_text(script)
    assert subprocess.run(["bash", "-n", str(path)], capture_output=True).returncode == 0


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


def test_xfwl4_live_session_uses_smithay_legacy_kms():
    """yellowfin-xfce runs 44430413946 and 44468617918 froze at the bootloader step with a
    kworker in dma_fence_default_wait, while KWin and GNOME Shell passed on the same GPU runner.
    Falsification: without SMITHAY_USE_LEGACY=1 in both greetd commands xfwl4 keeps the atomic path."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "live-iso/common/src/desktop-xfce.sh").read_text()
    assert '_xfce_env=" SMITHAY_USE_LEGACY=1"' in src
    assert src.count("${_xfce_session_path}${_xfce_env} dbus-run-session") == 2
