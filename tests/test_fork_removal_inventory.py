"""Protected baseline contract; native command mocks are not solver evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

PATH = Path(__file__).resolve().parents[1] / "build_scripts/lib/fork-removal-inventory.py"
SPEC = importlib.util.spec_from_file_location("inventory", PATH)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
SOURCE = "a" * 64
IMAGE = "sha256:" + "b" * 64


def record(name, version="1"):
    return {"name": name, "version": version, "architecture": "all"}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("TUNAOS_FORK_REMOVAL_QUALIFICATION", "1")
    base, desktop, receipt = [tmp_path / name for name in ("base.json", "desktop.json", "receipt.json")]
    monkeypatch.setattr(MOD, "snapshot", lambda manager: [record("base")])
    MOD.capture("apt", "base", SOURCE, IMAGE, base)
    monkeypatch.setattr(MOD, "snapshot", lambda manager: [record("base", "2"), record("desktop")])
    MOD.capture("apt", "desktop", SOURCE, IMAGE, desktop)
    current = [record("base", "2"), record("desktop"), record("spare")]
    monkeypatch.setattr(MOD, "snapshot", lambda manager: current.copy())
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        current.remove(record("spare"))
    monkeypatch.setattr(MOD.subprocess, "run", run)

    def qualify(names=None):
        return MOD.qualify("apt", SOURCE, IMAGE, base, desktop, ["spare"] if names is None else names, receipt)
    return qualify, current, calls, base, desktop, receipt


def test_exact_delta_and_baseline_upgrade(fixture):
    qualify, current, calls, base, desktop, receipt = fixture
    result = qualify()
    assert result["after"] == [record("base", "2"), record("desktop")]
    assert result["status"] == "qualified-fixture-only"
    assert json.loads(receipt.read_text()) == result
    assert len(calls) == 1
    with pytest.raises(MOD.ProtectionError, match="output must be new"):
        qualify()


@pytest.mark.parametrize("names", [["base"], ["desktop"], ["base", "spare"], [], ["spare", "spare"], ["-foo"], [1], ["missing"]])
def test_reject_before_native_mutation(fixture, names):
    qualify, _, calls, _, _, receipt = fixture
    with pytest.raises(MOD.ProtectionError):
        qualify(names)
    assert calls == []
    assert not receipt.exists()


@pytest.mark.parametrize("change", ["version", "missing", "provenance", "schema", "empty", "duplicate", "stage"])
def test_baseline_failure_prevents_mutation(fixture, change):
    qualify, current, calls, base, _, receipt = fixture
    value = json.loads(base.read_text())
    if change == "version":
        current[0]["version"] = "unexpected"
    elif change == "missing":
        current.pop(0)
    elif change == "provenance":
        value["source_sha256"] = "c" * 64
    elif change == "schema":
        value["schema_version"] = True
    elif change == "empty":
        value["packages"] = []
    elif change == "duplicate":
        value["packages"] *= 2
    else:
        value["stage"] = "desktop"
    base.write_text(json.dumps(value))
    with pytest.raises(MOD.ProtectionError):
        qualify()
    assert not calls and not receipt.exists()


def test_gate_failure(fixture, monkeypatch):
    qualify, _, calls, *_ = fixture
    monkeypatch.delenv("TUNAOS_FORK_REMOVAL_QUALIFICATION")
    with pytest.raises(MOD.ProtectionError, match="explicit"):
        qualify()
    assert not calls


def test_native_failure_propagates_without_receipt(fixture, monkeypatch):
    qualify, _, _, _, _, receipt = fixture
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "native")
    monkeypatch.setattr(MOD.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        qualify()
    assert not receipt.exists()


def test_unexpected_delta_rejected(fixture, monkeypatch):
    qualify, current, _, _, _, receipt = fixture
    monkeypatch.setattr(MOD.subprocess, "run", lambda *args, **kwargs: current.clear())
    with pytest.raises(MOD.ProtectionError, match="unexpected package delta"):
        qualify()
    assert not receipt.exists()


@pytest.mark.parametrize("manager,output", [("apt", "pkg\t1\tall\tinstalled\n"), ("dnf", "pkg\t1\tall\n"), ("zypper", "pkg\t1\tall\n"), ("pacman", "pkg 1\n")])
def test_native_inventory_parsers(monkeypatch, manager, output):
    monkeypatch.setattr(MOD, "invoke", lambda command: output)
    result = MOD.snapshot(manager)
    assert result == [{"name": "pkg", "version": "1", "architecture": None if manager == "pacman" else "all"}]


@pytest.mark.parametrize("manager", ["dnf", "zypper"])
def test_rpm_public_key_records_keep_native_missing_architecture(monkeypatch, manager):
    output = "gpg-pubkey\t0:93e8909b-66d42b2c\t(none)\ngpg-pubkey\t0:957f5868-5e5499b8\t(none)\n"
    monkeypatch.setattr(MOD, "invoke", lambda command: output)
    assert MOD.snapshot(manager) == [
        {"name": "gpg-pubkey", "version": version, "architecture": "(none)"}
        for version in ("0:93e8909b-66d42b2c", "0:957f5868-5e5499b8")
    ]


@pytest.mark.parametrize("manager,name,arch", [
    ("apt", "gpg-pubkey", "(none)"), ("dnf", "ordinary", "(none)"),
    ("dnf", "gpg-pubkey", "(unknown)"), ("dnf", "gpg-pubkey", None),
    ("zypper", "gpg-pubkey", ""), ("pacman", "gpg-pubkey", "(none)"),
])
def test_missing_architecture_exception_is_rpm_public_key_only(manager, name, arch):
    with pytest.raises(MOD.ProtectionError, match="architecture"):
        MOD.validate_records([{"name": name, "version": "1", "architecture": arch}], manager)


@pytest.mark.parametrize("drop_key", [False, True])
def test_rpm_key_record_is_protected_in_exact_delta(tmp_path, monkeypatch, drop_key):
    monkeypatch.setenv("TUNAOS_FORK_REMOVAL_QUALIFICATION", "1")
    key = {"name": "gpg-pubkey", "version": "0:93e8909b-66d42b2c", "architecture": "(none)"}
    current = [key]
    monkeypatch.setattr(MOD, "snapshot", lambda manager: current.copy())
    base, desktop, receipt = [tmp_path / name for name in ("base.json", "desktop.json", "receipt.json")]
    MOD.capture("dnf", "base", SOURCE, IMAGE, base)
    MOD.capture("dnf", "desktop", SOURCE, IMAGE, desktop)
    current.append(record("spare"))

    def remove(*args, **kwargs):
        current.remove(record("spare"))
        if drop_key:
            current.remove(key)

    monkeypatch.setattr(MOD.subprocess, "run", remove)
    if drop_key:
        with pytest.raises(MOD.ProtectionError, match="unexpected package delta"):
            MOD.qualify("dnf", SOURCE, IMAGE, base, desktop, ["spare"], receipt)
        assert not receipt.exists()
    else:
        result = MOD.qualify("dnf", SOURCE, IMAGE, base, desktop, ["spare"], receipt)
        assert result["after"] == [key]


@pytest.mark.parametrize("output", ["pkg\t1\tall\tunpacked\n", "pkg\t1\n", "pkg\t1\tall\tinstalled\npkg\t1\tall\tinstalled\n"])
def test_incomplete_or_invalid_native_inventory(monkeypatch, output):
    monkeypatch.setattr(MOD, "invoke", lambda command: output)
    with pytest.raises(MOD.ProtectionError):
        MOD.snapshot("apt")


def test_symlink_and_duplicate_json_rejected(fixture, tmp_path):
    qualify, _, calls, base, _, _ = fixture
    real = tmp_path / "real.json"
    base.rename(real)
    base.symlink_to(real)
    with pytest.raises(MOD.ProtectionError, match="symlinks"):
        qualify()
    base.unlink()
    base.write_text('{"stage":"base","stage":"desktop"}')
    with pytest.raises(MOD.ProtectionError, match="duplicate baseline key"):
        qualify()
    assert not calls


def test_native_dpkg_protected_inventory(tmp_path, monkeypatch):
    """Real dpkg inventory and removal in a private root, never host packages."""
    import shutil
    commands = {name: shutil.which(name) for name in ("dpkg", "dpkg-query", "dpkg-deb")}
    if not all(commands.values()):
        pytest.skip("native dpkg toolchain unavailable")
    root = tmp_path / "root"
    root.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("dpkg", "dpkg-query"):
        flags = f'--root="{root}" --force-not-root' if name == "dpkg" else f'--admindir="{root}/var/lib/dpkg"'
        path = bindir / name
        path.write_text(f'#!/bin/sh\nexec "{commands[name]}" {flags} "$@"\n')
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:/usr/sbin:/usr/bin:/sbin:/bin")
    monkeypatch.setenv("TUNAOS_FORK_REMOVAL_QUALIFICATION", "1")

    def install(name):
        control = tmp_path / name / "DEBIAN"
        control.mkdir(parents=True)
        (control / "control").write_text(
            f"Package: {name}\nVersion: 1\nArchitecture: all\nMaintainer: Fixture <fixture@example.invalid>\n"
            "Description: Empty private-root fixture\n")
        archive = tmp_path / f"{name}.deb"
        subprocess.run([commands["dpkg-deb"], "--build", str(control.parent), str(archive)], check=True, capture_output=True)
        subprocess.run(["dpkg", "--install", str(archive)], check=True, capture_output=True)

    base, desktop, receipt = [tmp_path / name for name in ("base.json", "desktop.json", "receipt.json")]
    install("fixture-baseline")
    MOD.capture("apt", "base", SOURCE, IMAGE, base)
    install("fixture-desktop")
    MOD.capture("apt", "desktop", SOURCE, IMAGE, desktop)
    install("fixture-spare")
    before = MOD.snapshot("apt")
    for name in ("fixture-baseline", "fixture-desktop"):
        with pytest.raises(MOD.ProtectionError, match="protected base/desktop"):
            MOD.qualify("apt", SOURCE, IMAGE, base, desktop, [name], receipt)
        assert MOD.snapshot("apt") == before
        assert not receipt.exists()
    result = MOD.qualify("apt", SOURCE, IMAGE, base, desktop, ["fixture-spare"], receipt)
    assert result["before"] == before
    assert MOD.snapshot("apt") == [r for r in before if r["name"] != "fixture-spare"]
    assert json.loads(receipt.read_text())["after"] == MOD.snapshot("apt")


def test_base_name_absent_from_desktop_remains_protected(fixture):
    qualify, current, calls, _, desktop, _ = fixture
    value = json.loads(desktop.read_text())
    value["packages"] = [record("desktop")]
    desktop.write_text(json.dumps(value))
    current[0]["version"] = "1"
    with pytest.raises(MOD.ProtectionError, match="protected base/desktop"):
        qualify(["base"])
    assert not calls
    assert qualify()["after"] == [record("base"), record("desktop")]


@pytest.mark.parametrize("bad", [None, "", "x y", "x\x00y", "x\x7fy"])
def test_invalid_versions(bad):
    with pytest.raises(MOD.ProtectionError):
        MOD.validate_records([record("pkg", bad)], "apt")


@pytest.mark.parametrize("manager,source,image", [("emerge", SOURCE, IMAGE), ("apt", None, IMAGE), ("apt", SOURCE, None), ("apt", SOURCE.upper(), IMAGE), ("apt", SOURCE, "mutable:latest")])
def test_invalid_provenance(manager, source, image):
    with pytest.raises(MOD.ProtectionError):
        MOD.provenance(manager, source, image)
