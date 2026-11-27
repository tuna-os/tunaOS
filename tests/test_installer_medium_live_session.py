"""GDM starts the session of the cell's desktop on the live medium (tunaOS#4905).

Falsification: the Brussels ISO asked GDM for `xfwl4`; the image's session is
`xfce-wayland`, and GDM fell back to GNOME. The helper must take the name
from the image and must refuse an image where it finds none.
"""

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "installer-medium/live/usr/libexec/medium-live-gdm-session"
loader = importlib.machinery.SourceFileLoader("medium_live_gdm_session", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


def image(tmp_path, desktop, wayland=(), x11=()):
    (tmp_path / "usr/lib/medium-live").mkdir(parents=True)
    (tmp_path / "usr/lib/medium-live/desktop").write_text(desktop + "\n")
    for directory, names in (("wayland-sessions", wayland), ("xsessions", x11)):
        (tmp_path / "usr/share" / directory).mkdir(parents=True)
        for name in names:
            (tmp_path / "usr/share" / directory / f"{name}.desktop").write_text("[Desktop Entry]\n")
    return tmp_path


def record(root):
    return (root / "var/lib/AccountsService/users/liveuser").read_text()


def test_brussels_gets_its_xfce_session_not_gnome(tmp_path):
    root = image(tmp_path, "xfce", wayland=("gnome", "xfce-wayland"), x11=("xfce",))
    assert helper.main(["liveuser", "--root", str(root)]) == 0
    assert "Session=xfce-wayland\n" in record(root)


def test_brussels_xfwl4_session_when_the_image_drops_xfce_wayland(tmp_path):
    # ghcr.io/tuna-os/brussels a2668a1c: xfce4-session.bst removes
    # xfce-wayland.desktop; the session is xfwl4.desktop next to GNOME's
    # (brussels:xfce run 45905755933 booted GNOME).
    root = image(tmp_path, "xfce", wayland=("gnome", "gnome-classic", "xfwl4"))
    assert helper.main(["liveuser", "--root", str(root)]) == 0
    assert "Session=xfwl4\n" in record(root)


def test_gnome_takes_the_plain_session_before_classic(tmp_path):
    root = image(tmp_path, "gnome", wayland=("gnome-classic", "gnome"), x11=("gnome-xorg",))
    assert helper.main(["liveuser", "--root", str(root)]) == 0
    assert "Session=gnome\n" in record(root)


def test_one_session_needs_no_record(tmp_path):
    root = image(tmp_path, "tuna", wayland=("shell",))
    assert helper.main(["liveuser", "--root", str(root)]) == 0
    assert not (root / "var/lib/AccountsService").exists()


def test_no_session_for_the_desktop_is_an_error_not_a_default(tmp_path):
    root = image(tmp_path, "xfce", wayland=("gnome", "plasma"))
    with pytest.raises(SystemExit, match="no session for desktop 'xfce'"):
        helper.main(["liveuser", "--root", str(root)])


def test_an_unknown_desktop_is_an_error(tmp_path):
    root = image(tmp_path, "mate", wayland=("mate",))
    with pytest.raises(SystemExit, match="unknown desktop"):
        helper.main(["liveuser", "--root", str(root)])


def test_the_live_setup_calls_the_helper_and_the_image_ships_it():
    setup = (ROOT / "installer-medium/live/usr/libexec/medium-live-setup").read_text()
    assert '/usr/libexec/medium-live-gdm-session "${user}"' in setup
    # Reached, not only invoked: the call comes before the hook loop and no
    # `exit` comes before it.
    head = setup[: setup.index("medium-live-gdm-session")]
    assert "\nexit" not in head
    assert "/usr/libexec/medium-live-gdm-session" in (ROOT / "installer-medium/Containerfile.live").read_text()


def test_the_live_image_rebuilds_the_initramfs_after_it_copies_the_dracut_files():
    """The initrd units did nothing: no step built the initramfs again
    (runs 45563432848 and 45568622066 booted with no live root overlay)."""
    text = (ROOT / "installer-medium/Containerfile.live").read_text()
    copy = text.index("COPY live/usr/ /usr/")
    rebuild = text.index("dracut --force --no-hostonly")
    assert copy < rebuild, "the initramfs build must come after the dracut files are in the image"
    # The build proves the effect, not only the call.
    assert "grep -q 'medium-live-root.service' /tmp/medium-initrd.list" in text[rebuild:]
    # No pipe into grep -q: with pipefail a match ends lsinitrd with SIGPIPE
    # and fails the build (measured on albacore:gnome, exit 141).
    assert "lsinitrd \"${img}\" |" not in text
    conf = (ROOT / "installer-medium/live/usr/lib/dracut/dracut.conf.d/60-medium-live.conf").read_text()
    assert "medium-live-root.service" in conf and "systemd-volatile-root" in conf


def test_the_live_root_overlay_reports_the_room_of_its_upper_layer():
    """A tmpfs that fills right after switch-root left albacore:kde (run 45938957311) with no
    sshd and nothing but ENOSPC on the console: the sizes go to the console first."""
    unit = (ROOT / "installer-medium/live/usr/lib/systemd/system/medium-live-root.service").read_text()
    reports = [l for l in unit.splitlines() if l.startswith("ExecStartPost=-") and "stat -f" in l]
    assert len(reports) == 1
    assert unit.index("ExecStart=/usr/lib/systemd/systemd-volatile-root") < unit.index(reports[0])
    assert "/sysroot" in reports[0] and "MemTotal" in reports[0]
    # systemd expands %S, %b, %f, %c and %d in an Exec line (run 45986427250 printed
    # /var/lib and a boot id for them): a statfs format needs %%.
    assert "%%S" in reports[0] and "%S" not in reports[0].replace("%%S", "")


def test_the_composefs_image_stays_out_of_the_ram_overlay():
    """albacore:kde run 45938957311: PID 1 relabels / and the overlay copies /.ostree.cfs up into a
    tmpfs capped at 25% of RAM: ENOSPC, then nothing starts. The image is whited out once the root
    is assembled."""
    root = ROOT / "installer-medium/live/usr/lib"
    unit = (root / "systemd/system/medium-live-cfs.service").read_text()
    assert "ExecStart=-/bin/rm -f /sysroot/.ostree.cfs" in unit
    assert "After=ostree-prepare-root.service bootc-root-setup.service" in unit
    assert "Before=initrd-root-fs.target" in unit
    assert "ConditionKernelCommandLine=tunaos.live" in unit and "ConditionPathExists=/etc/initrd-release" in unit
    # Reports before and after on the console; % in an Exec line is doubled.
    assert "medium-live-cfs: before" in unit and "medium-live-cfs: after" in unit
    assert "%S" not in unit.replace("%%S", "")
    # Pulled in by both root setups, built into the initrd, with the tools it runs.
    for drop in ("ostree-prepare-root", "bootc-root-setup"):
        conf = (root / f"systemd/system/{drop}.service.d/10-medium-live.conf").read_text()
        assert "medium-live-cfs.service" in conf
    assert "medium-live-cfs.service" in (root / "dracut/dracut.conf.d/60-medium-live.conf").read_text()
    assert "rm ls stat" in (root / "dracut/modules.d/90medium-sr0/module-setup.sh").read_text()


def run_autologin_block(root):
    """Run the Python block of medium-live-setup on a fixture root."""
    import os
    import re
    import subprocess
    import sys

    setup = (ROOT / "installer-medium/live/usr/libexec/medium-live-setup").read_text()
    block = re.search(r"python3 - <<'PY'\n(.*?)\nPY\n", setup, flags=re.S).group(1)
    return subprocess.run(
        [sys.executable, "-c", block],
        env={**os.environ, "MEDIUM_LIVE_ROOT": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_plasma_login_manager_gets_autologin_with_the_session_of_the_image(tmp_path):
    """bonito:kde starts plasmalogin, not SDDM: its first live boot stopped
    at the greeter (run 45594868276). Layout as measured on that image."""
    (tmp_path / "etc/plasmalogin.conf.d").mkdir(parents=True)
    (tmp_path / "etc/plasmalogin.conf").write_text("[Autologin]\n")
    (tmp_path / "etc/sddm.conf.d").mkdir(parents=True)
    (tmp_path / "usr/share/wayland-sessions").mkdir(parents=True)
    (tmp_path / "usr/share/wayland-sessions/plasma.desktop").write_text("[Desktop Entry]\n")
    done = run_autologin_block(tmp_path)
    assert done.returncode == 0, done.stderr
    want = "[Autologin]\nUser=liveuser\nSession=plasma\n"
    assert (tmp_path / "etc/plasmalogin.conf.d/medium-live.conf").read_text() == want
    assert (tmp_path / "etc/sddm.conf.d/medium-live.conf").read_text() == want
    assert not (tmp_path / "etc/gdm").exists()
    # No lock screen over the installer (run 45601458778 showed one).
    assert (tmp_path / "etc/xdg/kscreenlockerrc").read_text().count("Autolock=false") == 1
    assert "AutoSuspendAction=0" in (tmp_path / "etc/xdg/powerdevilrc").read_text()


def test_a_plasma_display_manager_with_no_plasma_session_is_an_error(tmp_path):
    (tmp_path / "etc/plasmalogin.conf.d").mkdir(parents=True)
    done = run_autologin_block(tmp_path)
    assert done.returncode != 0
    assert "no plasma session file" in done.stderr


def test_gdm_autologin_is_written_only_where_gdm_is(tmp_path):
    (tmp_path / "etc/gdm").mkdir(parents=True)
    assert run_autologin_block(tmp_path).returncode == 0
    assert "AutomaticLogin = liveuser" in (tmp_path / "etc/gdm/custom.conf").read_text()
    assert not (tmp_path / "etc/plasmalogin.conf.d").exists()


@pytest.mark.parametrize(("groups", "want"), [(("wheel",), "wheel"), (("sudo",), "sudo")])
def test_the_live_account_joins_the_admin_group_the_base_has(tmp_path, groups, want):
    """Ubuntu and Debian have no wheel group: `useradd --groups wheel` stopped
    medium-live-setup, and gurnard:pantheon booted with no live account
    (run 45819002208)."""
    import subprocess

    setup = (ROOT / "installer-medium/live/usr/libexec/medium-live-setup").read_text()
    head = setup[: setup.index("passwd --delete")]
    stubs = tmp_path / "bin"
    stubs.mkdir()
    log = tmp_path / "useradd.args"
    for name, body in (
        ("id", "exit 1"),
        ("getent", 'case " ' + " ".join(groups) + ' " in *" $2 "*) exit 0 ;; esac; exit 2'),
        ("useradd", f'printf "%s\\n" "$@" >"{log}"'),
    ):
        stub = stubs / name
        stub.write_text(f"#!/bin/bash\n{body}\n")
        stub.chmod(0o755)
    subprocess.run(["bash", "-c", head], check=True, env={"PATH": f"{stubs}:/usr/bin:/bin"})
    args = log.read_text().split("\n")
    assert args[args.index("--groups") + 1] == want


def test_sshd_starts_on_systemd_255_only_with_the_harness_credential():
    """systemd 255 (Ubuntu 24.04) ignores systemd.unit-dropin.* credentials,
    so the harness credential started no sshd on gurnard (run 45819002208)."""
    unit = (ROOT / "installer-medium/live/usr/lib/systemd/system/medium-e2e-ssh.service").read_text()
    assert "ConditionCredential=ssh.ephemeral-authorized_keys-all" in unit
    assert "start sshd.service" in unit and "start ssh.service" in unit
    assert "WantedBy=multi-user.target" in unit
    containerfile = (ROOT / "installer-medium/Containerfile.live").read_text()
    assert "medium-e2e-ssh.service" in containerfile[containerfile.index("systemctl enable"):]
    harness = (ROOT / "scripts/installer-e2e/run_e2e.py").read_text()
    assert '("ssh.ephemeral-authorized_keys-all", key' in harness


def test_the_target_disk_is_no_volume_of_the_live_desktop(tmp_path):
    """XFCE put a "luks-root" icon on the desktop (run 45681331980,
    usb-4-unlock.png): the LUKS partition that systemd-repart had just made.
    Falsification: without the block there is no rule at all."""
    assert run_autologin_block(tmp_path).returncode == 0
    rules = (tmp_path / "run/udev/rules.d/99-medium-live-target.rules").read_text().splitlines()
    assert len(rules) == 2
    assert all(r.startswith('SUBSYSTEM=="block", ') and r.endswith('ENV{UDISKS_IGNORE}="1"') for r in rules)
    # repart's label prefix, and fishermand's mapper names.
    assert 'ENV{ID_FS_LABEL}=="luks-*"' in rules[0] and 'ENV{ID_FS_TYPE}=="crypto_LUKS"' in rules[0]
    assert 'ENV{DM_NAME}=="fishermand-*"' in rules[1]
    # Any other LUKS disk of the person stays in view: no rule without a match
    # on what the installer makes.
    setup = (ROOT / "installer-medium/live/usr/libexec/medium-live-setup").read_text()
    assert setup.index("99-medium-live-target.rules") < setup.index("udevadm control --reload")


@pytest.mark.parametrize(
    ("cmdline", "existing", "want"),
    [
        ("BOOT_IMAGE=/x ro tunaos.live locale.LANG=en_US.UTF-8 quiet", None, "LANG=en_US.UTF-8\n"),
        ("ro tunaos.live locale.LANG=de_DE.UTF-8", "LANG=fr_FR.UTF-8\n", "LANG=fr_FR.UTF-8\n"),
        ("ro tunaos.live quiet", None, None),
    ],
)
def test_the_live_language_is_in_locale_conf(tmp_path, cmdline, existing, want):
    """localed writes no file when the chosen language equals its environment
    (the locale.LANG kernel argument), so systemd-firstboot --copy-locale had
    nothing to carry (albacore:gnome run 45897637330, tunaOS#5064)."""
    import subprocess

    setup = (ROOT / "installer-medium/live/usr/libexec/medium-live-setup").read_text()
    start = setup.index("locale_conf=")
    block = setup[start : setup.index("\nfi\n", start) + 4]
    (tmp_path / "etc").mkdir()
    conf = tmp_path / "etc/locale.conf"
    if existing is not None:
        conf.write_text(existing)
    (tmp_path / "cmdline").write_text(cmdline + "\n")
    env = {
        "MEDIUM_LIVE_ROOT": str(tmp_path),
        "MEDIUM_LIVE_CMDLINE": str(tmp_path / "cmdline"),
        "PATH": "/usr/bin:/bin",
    }
    subprocess.run(["bash", "-euo", "pipefail", "-c", block], check=True, env=env)
    assert (conf.read_text() if conf.exists() else None) == want


def test_accounts_daemon_is_restarted_so_it_reads_the_record_on_a_real_boot(tmp_path, monkeypatch):
    # Brussels, run 45915937930: the record was written after accounts-daemon
    # had cached the live user, and GDM started GNOME.
    calls = []
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, check: calls.append((cmd, check)))
    root = image(tmp_path, "xfce", wayland=("gnome", "xfwl4"))
    assert helper.main(["liveuser", "--root", str(root)]) == 0
    assert calls == [], "a test root must never restart the host's accounts-daemon"
    helper.refresh_accounts_daemon(Path("/"))
    assert calls == [(["systemctl", "try-restart", "accounts-daemon.service"], False)]


def test_the_live_layer_skips_fsck_so_a_read_only_esp_does_not_fail_boot_mount():
    dropin = ROOT / "installer-medium/live/usr/lib/systemd/system/systemd-fsck@.service.d/50-medium-live.conf"
    lines = [l for l in dropin.read_text().splitlines() if l and not l.startswith("#")]
    assert lines == ["[Unit]", "ConditionKernelCommandLine=!tunaos.live"]
