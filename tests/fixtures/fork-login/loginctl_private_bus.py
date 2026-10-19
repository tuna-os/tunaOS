"""Real loginctl regression fixture; private D-Bus only, no host logind.

Run with the system Python supplying gi/Gio:
    /usr/bin/python3 fork-loginctl-private-proof.py path/to/fork-install-observer.py
The complete process should be bounded by an outer subprocess timeout (30 s).
No host system service, network, disk-image or credential use.
"""

import importlib.util
import json
import os
import selectors
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from gi.repository import Gio, GLib

SESSION_ID = "c1"
SESSION_PATH = "/org/freedesktop/login1/session/c1"
PROPERTIES = {
    "Id": ("s", SESSION_ID),
    "User": ("(uo)", (1000, "/org/freedesktop/login1/user/_1000")),
    "Name": ("s", "canary"),
    "Remote": ("b", False),
    "Type": ("s", "wayland"),
    "Class": ("s", "user"),
    "Active": ("b", True),
    "State": ("s", "active"),
    "Service": ("s", "gdm-password"),
    "Desktop": ("s", ""),
    "Seat": ("(so)", ("seat0", "/org/freedesktop/login1/seat/seat0")),
    "Leader": ("u", 1234),
    "LockedHint": ("b", False),
    "TimestampMonotonic": ("t", 100000),
    # Must be excluded from show-session by its real command-line filter.
    "TTY": ("s", "tty2"),
    "IdleHint": ("b", False),
    "IdleSinceHintMonotonic": ("t", 0),
}
SESSION_KEYS = tuple(
    k for k in PROPERTIES if k not in {"TTY", "IdleHint", "IdleSinceHintMonotonic"}
)
EXPECTED = {
    "Id": SESSION_ID,
    "User": "1000",
    "Name": "canary",
    "Remote": "no",
    "Type": "wayland",
    "Class": "user",
    "Active": "yes",
    "State": "active",
    "Service": "gdm-password",
    "Desktop": "",
    "Seat": "seat0",
    "Leader": "1234",
    "LockedHint": "no",
    "TimestampMonotonic": "100000",
}
MANAGER_XML = """<node><interface name="org.freedesktop.login1.Manager">
<method name="GetSession"><arg type="s" direction="in"/><arg type="o" direction="out"/></method>
<method name="ListSessions"><arg type="a(susso)" direction="out"/></method>
<method name="ListSessionsEx"><arg type="a(sussussbto)" direction="out"/></method>
</interface></node>"""
PROPERTIES_XML = """<node><interface name="org.freedesktop.DBus.Properties">
<method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method>
<method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
</interface></node>"""


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


@contextmanager
def private_login1(*, legacy_list=False):
    """Expose fake login1 on a fresh bus and tear down all owned resources."""
    with tempfile.TemporaryDirectory(prefix="fork-loginctl-") as tmp:
        process = subprocess.Popen(
            [
                "dbus-daemon",
                "--session",
                "--nofork",
                "--print-address=1",
                "--address=unix:path=" + tmp + "/bus",
            ],
            env={**os.environ, "XDG_RUNTIME_DIR": tmp},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        connection = None
        loop = None
        thread = None
        registrations = []
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=5):
                    raise RuntimeError(
                        "Private dbus-daemon did not report an address within 5 seconds"
                    )
                address = process.stdout.readline().strip()
            if not address:
                stop_process(process)
                error = process.stderr.read(4096)
                if (
                    "Failed to bind socket" in error or "Failed to open socket" in error
                ) and "Operation not permitted" in error:
                    raise SystemExit(77)  # Local sandbox: no private Unix sockets.
                raise RuntimeError("Private dbus-daemon failed: " + error)
            assert address.startswith("unix:path=" + tmp + "/bus")
            connection = Gio.DBusConnection.new_for_address_sync(
                address,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None,
                None,
            )
            connection.set_exit_on_close(False)
            result = connection.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "RequestName",
                GLib.Variant("(su)", ("org.freedesktop.login1", 0)),
                GLib.VariantType.new("(u)"),
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
            assert result.unpack() == (1,), result.unpack()

            def manager(_connection, _sender, _path, _interface, method, args, invocation):
                if method == "GetSession":
                    if args.unpack() != (SESSION_ID,):
                        invocation.return_dbus_error(
                            "org.freedesktop.login1.NoSuchSession", "Unknown fixture session"
                        )
                    else:
                        invocation.return_value(GLib.Variant("(o)", (SESSION_PATH,)))
                elif method == "ListSessionsEx":
                    if legacy_list:
                        invocation.return_dbus_error(
                            "org.freedesktop.DBus.Error.UnknownMethod", "Exercise old logind"
                        )
                    else:
                        invocation.return_value(
                            GLib.Variant(
                                "(a(sussussbto))",
                                (
                                    [
                                        (
                                            SESSION_ID,
                                            1000,
                                            "canary",
                                            "seat0",
                                            1234,
                                            "user",
                                            "tty2",
                                            False,
                                            0,
                                            SESSION_PATH,
                                        )
                                    ],
                                ),
                            )
                        )
                elif method == "ListSessions":
                    invocation.return_value(
                        GLib.Variant(
                            "(a(susso))", ([(SESSION_ID, 1000, "canary", "seat0", SESSION_PATH)],)
                        )
                    )
                else:
                    invocation.return_dbus_error(
                        "org.freedesktop.DBus.Error.UnknownMethod", "Unknown fixture method"
                    )

            def properties(_connection, _sender, _path, _interface, method, args, invocation):
                unpacked = args.unpack()
                if unpacked[0] not in {"", "org.freedesktop.login1.Session"}:
                    invocation.return_dbus_error(
                        "org.freedesktop.DBus.Error.UnknownInterface", "Unknown fixture interface"
                    )
                elif method == "GetAll":
                    invocation.return_value(
                        GLib.Variant(
                            "(a{sv})",
                            (
                                {
                                    name: GLib.Variant(signature, value)
                                    for name, (signature, value) in PROPERTIES.items()
                                },
                            ),
                        )
                    )
                elif method == "Get" and unpacked[1] in PROPERTIES:
                    signature, value = PROPERTIES[unpacked[1]]
                    invocation.return_value(GLib.Variant("(v)", (GLib.Variant(signature, value),)))
                else:
                    invocation.return_dbus_error(
                        "org.freedesktop.DBus.Error.UnknownProperty", "Unknown fixture property"
                    )

            manager_info = Gio.DBusNodeInfo.new_for_xml(MANAGER_XML)
            property_info = Gio.DBusNodeInfo.new_for_xml(PROPERTIES_XML)
            registrations.append(
                connection.register_object(
                    "/org/freedesktop/login1", manager_info.interfaces[0], manager, None, None
                )
            )
            registrations.append(
                connection.register_object(
                    SESSION_PATH, property_info.interfaces[0], properties, None, None
                )
            )
            assert all(registrations)
            loop = GLib.MainLoop()
            thread = threading.Thread(target=loop.run, daemon=True)
            thread.start()
            yield address
        finally:
            if loop:
                loop.quit()
            if thread:
                thread.join(timeout=3)
            if connection:
                for registration in registrations:
                    connection.unregister_object(registration)
                connection.close_sync(None)
            stop_process(process)
            process.stdout.close()
            process.stderr.close()


def main(observer_path):
    assert shutil.which("loginctl") and shutil.which("dbus-daemon")
    spec = importlib.util.spec_from_file_location("fork_observer_private_login_test", observer_path)
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)
    assert tuple(observer.SESSION_KEYS) == SESSION_KEYS
    version = subprocess.run(
        ["loginctl", "--version"], capture_output=True, text=True, timeout=5, check=True
    ).stdout.splitlines()[0]
    reports = []
    for legacy_list in (False, True):
        with private_login1(legacy_list=legacy_list) as address:
            env = {**observer.ENV, "DBUS_SYSTEM_BUS_ADDRESS": address}

            def real(*args, env=env):
                return subprocess.run(
                    ["loginctl", *args],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )

            listed = real("list-sessions", "--no-legend", "--no-pager")
            assert [line.split()[0] for line in listed.stdout.splitlines() if line.strip()] == [
                SESSION_ID
            ], listed.stdout
            comma = real(
                "show-session", SESSION_ID, "--no-pager", "--property=" + ",".join(SESSION_KEYS)
            )
            assert comma.stdout == "", repr(comma.stdout)
            repeated = real(
                "show-session",
                SESSION_ID,
                "--no-pager",
                *("--property=" + key for key in SESSION_KEYS),
            )
            rows = repeated.stdout.splitlines()
            actual = dict(row.split("=", 1) for row in rows)
            assert len(rows) == len(EXPECTED) and actual == EXPECTED, actual
            original_env = observer.ENV
            try:
                observer.ENV = env
                sessions, status = observer.sessions(time.monotonic() + 10)
            finally:
                observer.ENV = original_env
            reports.append(
                {
                    "legacy_list": legacy_list,
                    "listed": listed.stdout,
                    "comma_stdout": comma.stdout,
                    "repeated_properties": actual,
                    "observer_status": status,
                    "observer_sessions": sessions,
                }
            )
            print(json.dumps({"loginctl_version": version, **reports[-1]}), flush=True)
            assert (sessions, status) == ([EXPECTED], "ok"), (sessions, status)
    print(
        "PASS: real loginctl comma negative control, repeated filters, empty Desktop, extra-property exclusion, both list APIs and observer integration"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: fork-loginctl-private-proof.py path/to/fork-install-observer.py")
    main(Path(sys.argv[1]).resolve())
