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
        env={**os.environ, "LISTEN_FDS": "4", "LISTEN_FDNAMES": names, "MEDIUM_FISHERMAND_BIN": "/bin/true"},
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0


@pytest.mark.skipif(not os.environ.get("FISHERMAND_BIN"), reason="FISHERMAND_BIN not set")
def test_real_fishermand_serves_one_interface_per_socket(tmp_path):
    names = ["fisherman", "shutdown", "sysinstall", "cryptenroll"]
    socks = []
    for n in names:
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(tmp_path / n))
        s.listen(8)
        socks.append(s)
    pid = os.fork()
    if pid == 0:
        for i, s in enumerate(socks):
            os.dup2(s.fileno(), 20 + i)
        for i in range(4):
            os.dup2(20 + i, 3 + i)
            os.close(20 + i)
        env = {
            **os.environ,
            "LISTEN_PID": str(os.getpid()),
            "LISTEN_FDS": "4",
            "LISTEN_FDNAMES": ":".join(names),
            "MEDIUM_FISHERMAND_BIN": os.environ["FISHERMAND_BIN"],
        }
        os.execve(str(WRAPPER), [str(WRAPPER)], env)
    try:
        time.sleep(1.0)
        for n in names:
            c = socket.socket(socket.AF_UNIX)
            c.connect(str(tmp_path / n))
            c.sendall(json.dumps({"method": "org.varlink.service.GetInfo"}).encode() + b"\0")
            buf = b""
            while not buf.endswith(b"\0"):
                buf += c.recv(65536)
            got = json.loads(buf[:-1])["parameters"]["interfaces"]
            assert got == [IFACES[n], "org.varlink.service"]
    finally:
        os.kill(pid, 9)
        os.waitpid(pid, 0)


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
    r = subprocess.run(
        [NODE, str(h), str(RULES), json.dumps(dict(action=action, user=user, active=active, local=local, lookup=lookup))],
        capture_output=True,
        text=True,
        env={**os.environ, "LIVE": "1" if live else "0"},
        check=True,
    )
    return r.stdout.strip()


@pytest.mark.skipif(NODE is None, reason="node not installed")
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
    assert "Exec=/usr/libexec/medium-live-installer --stamp org.gnome.Setup:SetupWindow:bus-name" in entry
    assert (root / "usr/libexec/medium-live-installer").stat().st_mode & 0o111
    assert (root / "usr/share/medium-live/stamp.d" / desktop).read_text().strip() == "launcher"
    # What the medium must not carry: session units, the app-grid entry, gnome-setup's own polkit rule.
    assert not (root / "usr/lib/systemd/user/gnome-setup.service").exists()
    assert not (root / "usr/share/applications/org.gnome.Setup.desktop").exists()
    assert not (root / "usr/share/polkit-1/rules.d/20-gnome-setup.rules").exists()
    pages = (root / "usr/lib/gnome-setup/pages.conf").read_text()
    assert "post-install-unit=medium-install-post@.service" in pages
    lst = (root / f"usr/share/medium-live/payload.d/{desktop}.list").read_text().split()
    assert "/etc/xdg/autostart/org.tunaos.installer-live.desktop" in lst
    assert "/usr/bin/gnome-setup" in lst
    assert len(lst) == len(set(lst))
    if desktop == "pantheon":
        assert (root / "usr/lib/medium-live/live-setup.d/50-pantheon-autologin").stat().st_mode & 0o111
    else:
        # Tuna Desktop runs gnome-shell: it gets the GNOME files under its own name.
        assert "/usr/libexec/medium-live-installer-gnome" in lst
        assert (root / "usr/lib/medium-live/desktop").read_text().strip() == desktop
        assert not (root / "usr/share/medium-live/payload.d/gnome.list").exists() or desktop == "gnome"


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
