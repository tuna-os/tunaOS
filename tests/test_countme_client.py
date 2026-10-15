"""Exercise the shipped reporter without contacting the telemetry endpoint."""
from __future__ import annotations

import datetime as dt
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("tunaos_countme_test", str(ROOT / "system_files/usr/libexec/tunaos-countme"))
spec = importlib.util.spec_from_loader(loader.name, loader)
client = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = client
loader.exec_module(client)
NOW = int(dt.datetime(2026, 9, 21, tzinfo=dt.timezone.utc).timestamp())


@pytest.fixture
def host(tmp_path):
    paths = client.Paths(tmp_path)
    for file in ("/run/ostree-booted", "/run/systemd/timesync/synchronized", "/proc/cmdline", "/etc/tunaos/countme/enabled"):
        p = paths.path(file)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    paths.metadata.parent.mkdir(parents=True, exist_ok=True)
    paths.path("/usr/share/tunaos/countme-allowlist.json").write_text((ROOT / "services/countme/src/allowlist.json").read_text())
    paths.metadata.write_text(json.dumps({"schema": 1, "variant": "bonito-rawhide", "flavor": "gnome-nvidia"}))
    with patch.object(client, "container_runtime", return_value=False), patch.object(client.platform, "machine", return_value="x86_64"):
        yield paths


def state(host):
    return json.loads((host.state / "state.json").read_text())


def test_payload_contains_only_bounded_categories_and_state_never_leaves_host(host):
    sender = Mock(return_value=True)
    assert client.run(host, NOW, sender) == "reported"
    assert sender.call_args.args == ({"schema": 1, "variant": "bonito-rawhide", "flavor": "gnome-nvidia", "arch": "x86_64", "age_bucket": 1},)
    assert state(host) == {"epoch": NOW, "last_week": client.utc_week(NOW)}
    assert client.run(host, NOW + 10, sender) == "already-attempted"
    assert sender.call_count == 1


@pytest.mark.parametrize("age,bucket", [(0, 1), (604799, 1), (604800, 2), (2419199, 2), (2419200, 3), (14515199, 3), (14515200, 4)])
def test_age_bucket_boundaries(age, bucket):
    assert client.age_bucket(NOW, NOW + age) == bucket


def test_week_rolls_at_utc_monday():
    assert client.utc_week(NOW - 1) + 1 == client.utc_week(NOW)
    assert client.utc_week(NOW) == client.utc_week(NOW + client.WEEK - 1)


@pytest.mark.parametrize("outcome", [False, OSError("offline"), ValueError("bad response")])
def test_failed_attempt_is_not_retried_in_the_same_week(host, outcome):
    sender = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
    assert client.run(host, NOW, sender) == "request-failed"
    assert client.run(host, NOW + 1, sender) == "already-attempted"
    assert sender.call_count == 1
    assert client.run(host, NOW + client.WEEK, Mock(return_value=True)) == "reported"
    assert state(host)["epoch"] == NOW


def test_attempt_file_and_directory_are_synced_before_http(host):
    events = []
    original_fsync = os.fsync
    def fsync(fd):
        events.append("sync")
        original_fsync(fd)
    def sender(payload):
        assert events == ["sync", "sync"]
        assert state(host)["last_week"] == client.utc_week(NOW)
        return True
    with patch.object(client.os, "fsync", side_effect=fsync):
        assert client.run(host, NOW, sender) == "reported"


def test_crash_after_durable_attempt_cannot_duplicate(host):
    with pytest.raises(SystemExit):
        client.run(host, NOW, Mock(side_effect=SystemExit(9)))
    sender = Mock(return_value=True)
    assert client.run(host, NOW, sender) == "already-attempted"
    sender.assert_not_called()


def test_failed_disk_sync_prevents_http(host):
    sender = Mock(return_value=True)
    with patch.object(client.os, "fsync", side_effect=OSError("disk full")):
        assert client.run(host, NOW, sender) == "invalid-state-or-metadata"
    sender.assert_not_called()


@pytest.mark.parametrize("raw", ["{", "[]", '{"epoch":0,"last_week":null}', '{"epoch":true,"last_week":null}', '{"epoch":9999999999,"last_week":null}'])
def test_corrupt_or_future_state_fails_closed(host, raw):
    host.state.mkdir(parents=True)
    (host.state / "state.json").write_text(raw)
    sender = Mock(return_value=True)
    assert client.run(host, NOW, sender).startswith("invalid-state")
    sender.assert_not_called()
    assert (host.state / "state.json").read_text() == raw


def test_clock_rollback_does_not_reset_week_or_epoch(host):
    assert client.run(host, NOW, Mock(return_value=True)) == "reported"
    previous = state(host)
    sender = Mock(return_value=True)
    assert client.run(host, NOW - client.WEEK, sender) == "invalid-state"
    assert state(host) == previous
    sender.assert_not_called()


@pytest.mark.parametrize("marker", ["/run/tunaos-live", "/etc/tunaos/live-session", "/run/tunaos-countme-disabled", "/run/initramfs/live", "/run/live/medium", "/etc/tunaos/countme/disabled"])
def test_excluded_runtime_and_optout_markers_prevent_state_and_http(host, marker):
    file = host.path(marker)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.touch()
    sender = Mock(return_value=True)
    assert client.run(host, NOW, sender) == "ineligible"
    sender.assert_not_called()
    assert not host.state.exists()


@pytest.mark.parametrize("cmdline", ["rd.live.image", "rd.live.image=1", "boot=live", "tunaos.countme=0", "tunaos.countme=off"])
def test_live_and_ci_kernel_controls_prevent_reporting(host, cmdline):
    host.path("/proc/cmdline").write_text(f"quiet {cmdline}")
    sender = Mock(return_value=True)
    assert client.run(host, NOW, sender) == "ineligible"
    sender.assert_not_called()


def test_container_unsynchronized_and_uninstalled_hosts_are_ineligible(host):
    sender = Mock(return_value=True)
    with patch.object(client, "container_runtime", return_value=True):
        assert client.run(host, NOW, sender) == "ineligible"
    with patch.object(client, "clock_synchronized", return_value=False):
        assert client.run(host, NOW, sender) == "ineligible"
    host.path("/run/ostree-booted").unlink()
    assert client.run(host, NOW, sender) == "ineligible"
    sender.assert_not_called()


def test_controls_persist_optout_without_erasing_week_state(host):
    assert client.run(host, NOW, Mock(return_value=True)) == "reported"
    previous = state(host)
    with patch.object(client.os, "geteuid", return_value=0), patch.object(client.subprocess, "run") as systemctl:
        client.control("disable", host)
        assert not client.enabled(host)
        assert (host.control / "disabled").exists()
        client.control("enable", host)
        assert client.enabled(host)
        assert not (host.control / "disabled").exists()
    assert state(host) == previous
    assert systemctl.call_args_list[0].args[0][1:3] == ["mask", "--now"]
    assert client.run(host, NOW, Mock(return_value=True)) == "already-attempted"


def test_fresh_installed_system_is_enabled_by_default(host):
    (host.control / "enabled").unlink()
    assert client.run(host, NOW, Mock(return_value=True)) == "reported"


@pytest.mark.parametrize("metadata", [{"schema": 1, "variant": "host.example", "flavor": "gnome"}, {"schema": 1, "variant": "yellowfin", "flavor": "gnome", "hostname": "secret"}, {"schema": True, "variant": "yellowfin", "flavor": "gnome"}])
def test_invalid_metadata_never_sends(host, metadata):
    host.metadata.write_text(json.dumps(metadata))
    sender = Mock(return_value=True)
    assert client.run(host, NOW, sender) == "invalid-state-or-metadata"
    sender.assert_not_called()


def test_http_transport_is_post_bounded_fixed_identity_and_refuses_redirects():
    response = Mock(status=204)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    with patch.object(client.urllib.request, "build_opener", return_value=opener) as build:
        assert client.send({"schema": 1})
    request = opener.open.call_args.args[0]
    assert request.method == "POST"
    assert request.full_url == client.ENDPOINT
    assert request.get_header("User-agent") == "tunaos-countme/1"
    assert opener.open.call_args.kwargs["timeout"] == 15
    assert build.call_args.args[0].proxies == {}
    assert isinstance(build.call_args.args[1], client.NoRedirect)
    assert client.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example") is None


def test_concurrent_processes_share_one_durable_attempt(host):
    # Fork real processes so flock is exercised between independent descriptors.
    script = '''import importlib.machinery, importlib.util, sys, time
loader=importlib.machinery.SourceFileLoader("countme",sys.argv[1]); spec=importlib.util.spec_from_loader(loader.name,loader); c=importlib.util.module_from_spec(spec); sys.modules[loader.name]=c; loader.exec_module(c)
c.container_runtime=lambda:False; c.platform.machine=lambda:"x86_64"
p=c.Paths(c.Path(sys.argv[2]))
def sender(payload):
    with p.path("/attempts").open("a") as f: f.write("sent\\n")
    time.sleep(.1)
    return True
print(c.run(p,int(sys.argv[3]),sender))
'''
    args = [sys.executable, "-c", script, str(ROOT / "system_files/usr/libexec/tunaos-countme"), str(host.root), str(NOW)]
    processes = [subprocess.Popen(args, stdout=subprocess.PIPE, text=True) for _ in range(4)]
    results = [p.communicate(timeout=10)[0].strip() for p in processes]
    assert sorted(results) == ["already-attempted"] * 3 + ["reported"]
    assert host.path("/attempts").read_text() == "sent\n"


def test_optout_arriving_while_waiting_for_lock_prevents_request(host):
    sender = Mock(return_value=True)
    original = client.fcntl.flock
    def acquire(fd, operation):
        original(fd, operation)
        (host.control / "disabled").touch()
    with patch.object(client.fcntl, "flock", side_effect=acquire):
        assert client.run(host, NOW, sender) == "disabled"
    sender.assert_not_called()
    assert not (host.state / "state.json").exists()


@pytest.mark.parametrize("now", [0, 1704067199, True, "2026-09-21"])
def test_invalid_clock_prevents_request_and_state(host, now):
    sender = Mock(return_value=True)
    assert client.run(host, now, sender) == "invalid-clock"
    sender.assert_not_called()
    assert not host.state.exists()


def test_unknown_architecture_is_not_automatically_relabelled(host):
    sender = Mock(return_value=True)
    with patch.object(client.platform, "machine", return_value="secret-host-description"):
        assert client.run(host, NOW, sender) == "unknown-architecture"
    sender.assert_not_called()
    assert not host.state.exists()


@pytest.mark.parametrize("product,expected", [("tunaos-countme-disabled\n", "ineligible"), ("Standard PC (Q35 + ICH9, 2009)\n", "reported")])
def test_explicit_ci_dmi_marker_excludes_guests_without_excluding_normal_vms(host, product, expected):
    path = host.path("/sys/class/dmi/id/product_name")
    path.parent.mkdir(parents=True)
    path.write_text(product)
    sender = Mock(return_value=True)
    assert client.run(host, NOW, sender) == expected
    assert sender.call_count == (expected == "reported")


@pytest.mark.parametrize("variant,flavor,arch", [("my-custom-image", "gnome", "x86_64"), ("bonito-rawhide", "gnome-nvidia-hwe", "x86_64"), ("bonito-rawhide", "gnome-nvidia", "aarch64")])
def test_unknown_official_category_or_unsupported_tuple_never_contacts_collector(host, variant, flavor, arch):
    host.metadata.write_text(json.dumps({"schema": 1, "variant": variant, "flavor": flavor}))
    sender = Mock(return_value=True)
    with patch.object(client.platform, "machine", return_value=arch):
        result = client.run(host, NOW, sender)
    assert result not in {"reported", "request-failed"}
    sender.assert_not_called()
    assert not host.state.exists()
