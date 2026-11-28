"""The medium's daemon units, socket order, polkit rules and frontend dispatcher (tunaOS#4905).

Real evidence behind the fd-order test: with systemd's descriptor order
unspecified, fishermand (measured at 54259aab; fisherman#520, the 2fc33965 pin,
does not touch cmd/fishermand) maps the Nth inherited socket to the Nth
interface. medium-fishermand reorders by LISTEN_FDNAMES. The test uses a fake
daemon so CI needs no Go; set FISHERMAND_BIN to a built fishermand to also
check each socket answers for exactly its own interface.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEDIUM = ROOT / "installer-medium"
LIVE = MEDIUM / "live/usr"
UNITS = LIVE / "lib/systemd/system"
WRAPPER = LIVE / "libexec/medium-fishermand"
RULES = LIVE / "share/polkit-1/rules.d/50-tunaos-medium-live.rules"
POLICY = LIVE / "share/polkit-1/actions/org.tunaos.medium-installer.policy"
IFACES = {
    "sysinstall": "io.systemd.SysInstall",
    "cryptenroll": "io.systemd.CryptEnroll",
    "shutdown": "io.systemd.Shutdown",
    "fisherman": "io.tunaos.Fisherman",
}


def test_every_daemon_unit_exists_only_on_the_medium():
    for name in ["fishermand.service", *[f"fishermand-{s}.socket" for s in IFACES]]:
        text = (UNITS / name).read_text()
        assert "ConditionKernelCommandLine=tunaos.live" in text, name
        assert "ConditionPathExists=/usr/libexec/fishermand" in text, name


def test_sockets_name_their_interface_and_descriptor():
    for short, iface in IFACES.items():
        text = (UNITS / f"fishermand-{short}.socket").read_text()
        assert f"FileDescriptorName={short}" in text
        assert re.search(rf"^ListenStream=/run/\w+/{re.escape(iface)}$", text, re.M)
        assert "Service=fishermand.service" in text
        assert "WantedBy=sockets.target" in text


def test_service_inherits_all_four_sockets_in_one_process():
    text = (UNITS / "fishermand.service").read_text()
    for short in IFACES:
        assert f"fishermand-{short}.socket" in text
    assert "Accept" not in text.replace("Accept=yes would", "")
    assert "ExecStart=/usr/libexec/medium-fishermand" in text


FAKE = """#!/usr/bin/env python3
import json, os, socket
out = {}
for fd in range(3, 7):
    s = socket.socket(fileno=fd)
    out[str(fd)] = s.getsockname()
print(json.dumps(out))
"""


def sysinstall(tmp_path):
    """A merged medium sysext: the pinned systemd-repart is there."""
    d = tmp_path / "medium-sysinstall"
    d.mkdir(exist_ok=True)
    (d / "systemd-repart").write_text("#!/bin/sh\n")
    (d / "systemd-repart").chmod(0o755)
    return d


def _fake_mount(tmp_path, ok=True):
    """A `mount` that lays the sysext tree where the wrapper mounts it."""
    fake = tmp_path / "mount"
    fake.write_text(
        "#!/bin/sh\n"
        'echo "$@" >>' + str(tmp_path / "mount-calls") + "\n"
        + ("" if ok else "exit 32\n")
        + 'for last; do :; done\n'
        'mkdir -p "$last/usr/libexec/medium-sysinstall" "$last/usr/lib64/medium-sysinstall"\n'
        'printf "#!/bin/sh\\n" >"$last/usr/libexec/medium-sysinstall/systemd-repart"\n'
        'chmod +x "$last/usr/libexec/medium-sysinstall/systemd-repart"\n'
    )
    fake.chmod(0o755)
    return fake


def _show_env(tmp_path):
    """A daemon that records the environment the wrapper hands it."""
    daemon = tmp_path / "fishermand"
    daemon.write_text(f'#!/bin/sh\necho "$PATH" >{tmp_path}/path\necho "$LD_LIBRARY_PATH" >{tmp_path}/ldpath\n')
    daemon.chmod(0o755)
    return daemon


def test_wrapper_refuses_to_start_without_the_medium_sysext(tmp_path):
    # brussels:xfce (GNOME OS base): no pinned tools and no image to take them
    # from, so the base's repart would partition and leave no TPM2 token.
    r = subprocess.run(
        [str(WRAPPER)],
        env={**os.environ, "MEDIUM_FISHERMAND_BIN": "/bin/true",
             "MEDIUM_SYSINSTALL_DIR": str(tmp_path / "absent"),
             "MEDIUM_SYSEXT_MOUNT": str(tmp_path / "mnt"),
             "MEDIUM_VAR_EXTENSIONS": str(tmp_path / "no-var"),
             "MEDIUM_SYSROOT": str(tmp_path / "no-sysroot")},
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "no medium-sysinstall.raw was found" in r.stderr


def test_wrapper_mounts_the_state_var_sysext_instead_of_merging_it(tmp_path):
    # Composefs live boot (brussels:xfce, medium 46028616755): /var is the
    # image's, the raw image is in the deployment's state var under /sysroot,
    # and a sysext merge fails with "overlayfs: maximum fs stacking depth
    # exceeded" (hosted run 46051990086). The wrapper mounts the squashfs and
    # puts its tools first on PATH, its library next to them.
    raw = tmp_path / "sysroot/state/os/default/var/lib/extensions/medium-sysinstall.raw"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"x")
    mnt = tmp_path / "mnt"
    r = subprocess.run(
        [str(WRAPPER)],
        env={**os.environ, "MEDIUM_FISHERMAND_BIN": str(_show_env(tmp_path)),
             "MEDIUM_MOUNT": str(_fake_mount(tmp_path)),
             "MEDIUM_SYSINSTALL_DIR": str(tmp_path / "absent"),
             "MEDIUM_SYSEXT_MOUNT": str(mnt),
             "MEDIUM_VAR_EXTENSIONS": str(tmp_path / "no-var"),
             "MEDIUM_SYSROOT": str(tmp_path / "sysroot")},
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "mount-calls").read_text().split() == ["-t", "squashfs", "-o", "ro,loop", str(raw), str(mnt)]
    assert (tmp_path / "path").read_text().startswith(f"{mnt}/usr/libexec/medium-sysinstall:")
    assert (tmp_path / "ldpath").read_text().strip() == f"{mnt}/usr/lib64/medium-sysinstall"


def test_wrapper_stops_when_the_sysext_cannot_be_mounted(tmp_path):
    raw = tmp_path / "var/medium-sysinstall.raw"
    raw.parent.mkdir()
    raw.write_bytes(b"x")
    r = subprocess.run(
        [str(WRAPPER)],
        env={**os.environ, "MEDIUM_FISHERMAND_BIN": "/bin/true",
             "MEDIUM_MOUNT": str(_fake_mount(tmp_path, ok=False)),
             "MEDIUM_SYSINSTALL_DIR": str(tmp_path / "absent"),
             "MEDIUM_SYSEXT_MOUNT": str(tmp_path / "mnt"),
             "MEDIUM_VAR_EXTENSIONS": str(raw.parent),
             "MEDIUM_SYSROOT": str(tmp_path / "no-sysroot")},
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "cannot mount" in r.stderr


def test_wrapper_leaves_the_environment_alone_when_the_sysext_merged(tmp_path):
    r = subprocess.run(
        [str(WRAPPER)],
        env={k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
        | {"MEDIUM_FISHERMAND_BIN": str(_show_env(tmp_path)),
           "MEDIUM_SYSINSTALL_DIR": str(sysinstall(tmp_path))},
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "medium-sysinstall-ext" not in (tmp_path / "path").read_text()
    assert (tmp_path / "ldpath").read_text().strip() == ""


def test_wrapper_orders_descriptors_by_name(tmp_path):
    fake = tmp_path / "fake-fishermand"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    names = ["fisherman", "shutdown", "sysinstall", "cryptenroll"]  # shuffled on purpose
    socks = []
    for n in names:
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(tmp_path / n))
        s.listen(1)
        socks.append(s)

    def place():
        for i, s in enumerate(socks):
            os.dup2(s.fileno(), 20 + i)
        for i in range(4):
            os.dup2(20 + i, 3 + i)
            os.close(20 + i)

    env = {
        **os.environ,
        "LISTEN_FDS": "4",
        "LISTEN_FDNAMES": ":".join(names),
        "MEDIUM_FISHERMAND_BIN": str(fake),
        "MEDIUM_SYSINSTALL_DIR": str(sysinstall(tmp_path)),
    }
    out = subprocess.run(
        [str(WRAPPER)], env=env, preexec_fn=place, capture_output=True, text=True, check=True, close_fds=False
    ).stdout
    got = json.loads(out)
    want = ["sysinstall", "cryptenroll", "shutdown", "fisherman"]
    assert [Path(got[str(3 + i)]).name for i in range(4)] == want


@pytest.mark.parametrize("names", ["a:b:c:d", "sysinstall:sysinstall:shutdown:fisherman", "sysinstall"])
def test_wrapper_rejects_bad_names(tmp_path, names):
    r = subprocess.run(
        [str(WRAPPER)],
        env={**os.environ, "LISTEN_FDS": "4", "LISTEN_FDNAMES": names, "MEDIUM_FISHERMAND_BIN": "/bin/true",
             "MEDIUM_SYSINSTALL_DIR": str(sysinstall(tmp_path))},
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0


def test_policy_registers_every_action_the_daemon_checks():
    policy = set(re.findall(r'<action id="([^"]+)"', POLICY.read_text()))
    rule = RULES.read_text()
    daemon = {
        "io.tunaos.Fisherman." + m for m in ("ConfigureTarget", "Install", "Handoff", "Cancel")
    } | {"io.systemd.SysInstall.Run", "io.systemd.CryptEnroll.Enroll", "io.systemd.CryptEnroll.MakeRecoveryKey"} | {
        "io.systemd.Shutdown." + k for k in ("PowerOff", "Reboot", "Halt", "KExec", "SoftReboot")
    }
    assert policy == daemon
    for action in daemon:
        assert f'"{action}"' in rule


NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs');
let rule = null, live = process.env.LIVE === '1';
const polkit = {
  addRule(f) { rule = f; },
  spawn() { if (!live) throw new Error('exit 1'); return ''; },
  Result: { YES: 'yes' },
};
eval(fs.readFileSync(process.argv[2], 'utf8'));
const c = JSON.parse(process.argv[3]);
const action = { id: c.action, lookup: (k) => (c.lookup || {})[k] };
const subject = { user: c.user, active: c.active, local: c.local };
console.log(String(rule(action, subject)));
"""


def decide(tmp_path, *, action, user="liveuser", active=True, local=True, live=True, lookup=None):
    h = tmp_path / "h.js"
    h.write_text(HARNESS)
    # No skip: the rules file is JavaScript, and a suite that passes without
    # node did not read it. GitHub-hosted runners carry node.
    assert NODE, "node is required to evaluate the polkit rules"
    r = subprocess.run(
        [NODE, str(h), str(RULES), json.dumps(dict(action=action, user=user, active=active, local=local, lookup=lookup))],
        capture_output=True,
        text=True,
        env={**os.environ, "LIVE": "1" if live else "0"},
        check=True,
    )
    return r.stdout.strip()


class TestPolkitRules:
    def test_live_user_may_run_the_install(self, tmp_path):
        for a in ("io.tunaos.Fisherman.Install", "io.systemd.SysInstall.Run", "io.systemd.CryptEnroll.Enroll"):
            assert decide(tmp_path, action=a) == "yes"

    def test_nothing_else_passes(self, tmp_path):
        for a in ("org.freedesktop.systemd1.manage-units", "org.freedesktop.login1.power-off", "org.tunaos.Other"):
            assert decide(tmp_path, action=a) == "undefined"

    @pytest.mark.parametrize(
        "kw", [dict(user="alice"), dict(active=False), dict(local=False), dict(live=False)]
    )
    def test_other_callers_and_installed_systems_fall_through(self, tmp_path, kw):
        assert decide(tmp_path, action="io.tunaos.Fisherman.Install", **kw) == "undefined"

    def test_only_the_post_install_unit_may_start(self, tmp_path):
        ok = dict(verb="start", unit="medium-install-post@dev-vdb.service")
        assert decide(tmp_path, action="org.freedesktop.systemd1.manage-units", lookup=ok) == "yes"
        for bad in (
            dict(verb="stop", unit="medium-install-post@dev-vdb.service"),
            dict(verb="start", unit="sshd.service"),
            dict(verb="start", unit="medium-install-post@a/b.service"),
        ):
            assert decide(tmp_path, action="org.freedesktop.systemd1.manage-units", lookup=bad) == "undefined"


# --- frontend dispatcher ----------------------------------------------------

DISPATCH = MEDIUM / "frontends/install-frontend.sh"


def fake_gnome_payload(tmp_path):
    p = tmp_path / "payload/gnome-setup"
    for rel in (
        "usr/bin/gnome-setup",
        "usr/lib/systemd/user/gnome-setup.service",
        "usr/share/applications/org.gnome.Setup.desktop",
        "usr/share/polkit-1/rules.d/20-gnome-setup.rules",
        "usr/lib/gnome-setup/pages.conf",
    ):
        (p / rel).parent.mkdir(parents=True, exist_ok=True)
        (p / rel).write_text("")
    (p / "usr/bin/gnome-setup").chmod(0o755)
    return tmp_path / "payload"


@pytest.mark.parametrize("desktop", ["gnome", "tuna", "pantheon"])
def test_dispatcher_installs_gnome_setup_and_autostart(tmp_path, desktop):
    root = tmp_path / "root"
    root.mkdir()
    subprocess.run(
        [str(DISPATCH), desktop, str(root)],
        env={**os.environ, "MEDIUM_PAYLOAD": str(fake_gnome_payload(tmp_path))},
        check=True,
        capture_output=True,
    )
    entry = (root / "etc/xdg/autostart/org.tunaos.installer-live.desktop").read_text()
    assert "--stamp org.gnome.Setup:SetupWindow:bus-name" in entry
    assert entry.count("\nExec=/usr/libexec/medium-live-installer ") == 1
    assert (root / "usr/libexec/medium-live-installer").stat().st_mode & 0o111
    assert (root / "usr/share/medium-live/stamp.d" / desktop).read_text().strip() == "launcher"
    # What the medium must not carry: session units, the app-grid entry, gnome-setup's own polkit rule.
    assert not (root / "usr/lib/systemd/user/gnome-setup.service").exists()
    assert not (root / "usr/share/applications/org.gnome.Setup.desktop").exists()
    assert not (root / "usr/share/polkit-1/rules.d/20-gnome-setup.rules").exists()
    pages = (root / "usr/lib/gnome-setup/pages.conf").read_text()
    assert "post-install-unit=medium-install-post@.service" in pages
    # The group selects the session language, so Next sets it in localed.
    assert "\n[page:language]\n" in pages
    lst = (root / f"usr/share/medium-live/payload.d/{desktop}.list").read_text().split()
    assert "/etc/xdg/autostart/org.tunaos.installer-live.desktop" in lst
    assert "/usr/bin/gnome-setup" in lst
    # Every launcher starts gnome-setup with the live language (tunaOS#5064).
    wrapper = root / "usr/libexec/medium-live-gnome-setup"
    assert wrapper.stat().st_mode & 0o111
    assert "/usr/libexec/medium-live-gnome-setup" in lst
    launcher = root / f"usr/libexec/medium-live-installer-{'pantheon' if desktop == 'pantheon' else 'gnome'}"
    assert launcher.read_text().rstrip().endswith('exec /usr/libexec/medium-live-gnome-setup "$@"')
    assert len(lst) == len(set(lst))
    if desktop == "pantheon":
        assert (root / "usr/lib/medium-live/live-setup.d/50-pantheon-autologin").stat().st_mode & 0o111
        # The installed login starts the X11 session: lightdm's own default is
        # pantheon-wayland, which ends at once without a GPU (run 46120510316).
        dropin = root / "etc/lightdm/lightdm.conf.d/60-tunaos-pantheon-x11.conf"
        assert "\n[Seat:*]\nuser-session=pantheon\n" in dropin.read_text()
        assert "/etc/lightdm/lightdm.conf.d/60-tunaos-pantheon-x11.conf" in lst
        # The launcher keeps the machine awake and unlocked mid-install.
        launcher = root / "usr/libexec/medium-live-installer-pantheon"
        assert launcher.stat().st_mode & 0o111
        assert "idle-delay 0" in launcher.read_text() and "sleep-inactive-ac-type nothing" in launcher.read_text()
        assert "-- /usr/libexec/medium-live-installer-pantheon\n" in entry
    else:
        # Tuna Desktop runs gnome-shell: it gets the GNOME files under its own name.
        assert "/usr/libexec/medium-live-installer-gnome" in lst
        assert (root / "usr/lib/medium-live/desktop").read_text().strip() == desktop
        assert not (root / "usr/share/medium-live/payload.d/gnome.list").exists() or desktop == "gnome"
    unit = root / "usr/lib/systemd/user/medium-live-installer-tuna.service"
    if desktop == "tuna":
        # tuna-session runs no XDG autostart: a user unit starts the launcher,
        # and both start paths use --once.
        assert "Exec=/usr/libexec/medium-live-installer --once --stamp " in entry
        text = unit.read_text()
        assert "ExecStart=/usr/libexec/medium-live-installer --once --stamp org.gnome.Setup:SetupWindow:bus-name" in text
        assert "ConditionKernelCommandLine=tunaos.live" in text
        drop = root / "usr/lib/systemd/user/tuna-session.target.d/50-medium-live-installer.conf"
        assert "Wants=medium-live-installer-tuna.service" in drop.read_text()
        assert "/usr/lib/systemd/user/medium-live-installer-tuna.service" in lst
        assert "/usr/lib/systemd/user/tuna-session.target.d/50-medium-live-installer.conf" in lst
    else:
        assert not unit.exists()
        assert "--once" not in entry


@pytest.mark.parametrize("bad", ["", "plasma", "GNOME", "base", "../x"])
def test_dispatcher_rejects_unknown_desktops(tmp_path, bad):
    r = subprocess.run([str(DISPATCH), bad or "x", str(tmp_path)] if bad else [str(DISPATCH), "x", str(tmp_path)], capture_output=True, text=True)
    r2 = subprocess.run([str(DISPATCH), bad, str(tmp_path)], capture_output=True, text=True) if bad else r
    assert r.returncode != 0 and r2.returncode != 0
    assert "unknown desktop" in r.stderr


def test_dispatcher_refuses_a_root_that_is_the_host(tmp_path):
    r = subprocess.run([str(DISPATCH), "gnome", "/"], capture_output=True, text=True)
    assert r.returncode != 0 and "staging path" in r.stderr
    r = subprocess.run([str(DISPATCH), "gnome", "relative"], capture_output=True, text=True)
    assert r.returncode != 0


def test_dispatcher_fails_a_frontend_that_breaks_the_contract(tmp_path):
    fe = tmp_path / "fe"
    (fe / "kde").mkdir(parents=True)
    shutil.copy(MEDIUM / "frontends/lib.sh", fe / "lib.sh")
    script = fe / "kde/install.sh"
    # Installs a file but never an autostart entry.
    script.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nsource "${MEDIUM_FRONTENDS}/lib.sh"\nfe_init "$1" kde\n'
        "echo x | fe_write 0644 /usr/bin/kde-installer\nfe_stamp native\n"
    )
    script.chmod(0o755)
    root = tmp_path / "root"
    root.mkdir()
    r = subprocess.run(
        [str(DISPATCH), "kde", str(root)],
        env={**os.environ, "MEDIUM_FRONTENDS_DIR": str(fe)},
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "contract violation" in r.stderr and "autostart" in r.stderr


def test_launcher_does_nothing_outside_a_live_boot(tmp_path):
    cmdline = tmp_path / "cmdline"
    cmdline.write_text("root=/dev/vda3 ro\n")
    marker = tmp_path / "ran"
    r = subprocess.run(
        [str(MEDIUM / "frontends/medium-live-installer"), "--", "touch", str(marker)],
        env={**os.environ, "MEDIUM_CMDLINE": str(cmdline)},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and not marker.exists()


def test_launcher_sets_the_daemon_backend_on_a_live_boot(tmp_path):
    cmdline = tmp_path / "cmdline"
    cmdline.write_text("root=/dev/vda3 ro tunaos.live\n")
    r = subprocess.run(
        [str(MEDIUM / "frontends/medium-live-installer"), "--", "sh", "-c", "echo $TUNA_INSTALLER_BACKEND"],
        env={k: v for k, v in {**os.environ, "MEDIUM_CMDLINE": str(cmdline)}.items() if k != "TUNA_INSTALLER_BACKEND"},
        capture_output=True,
        text=True,
    )
    assert r.stdout.strip() == "daemon"


def test_launcher_writes_the_stamp_without_a_bus_name(tmp_path):
    cmdline = tmp_path / "cmdline"
    cmdline.write_text("tunaos.live\n")
    run = tmp_path / "run"
    run.mkdir()
    subprocess.run(
        [str(MEDIUM / "frontends/medium-live-installer"), "--stamp", "org.x.App:Win:gtk-map", "--", "sleep", "0.5"],
        env={**os.environ, "MEDIUM_CMDLINE": str(cmdline), "XDG_RUNTIME_DIR": str(run)},
        check=True,
    )
    time.sleep(0.2)
    stamp = dict(l.split("=", 1) for l in (run / "tuna-installer-ready").read_text().splitlines())
    assert stamp["app_id"] == "org.x.App" and stamp["window"] == "Win" and stamp["signal"] == "gtk-map"
    assert stamp["page"] == "unknown"
