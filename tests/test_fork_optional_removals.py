"""Reviewed optional-removal safety boundaries, with explicit native-test limits."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "build_scripts/lib/fork-optional-removals.py"
SPEC = importlib.util.spec_from_file_location("optional_removals", PATH)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def manifest(manager="apt", variant="grouper", flavor="gnome", remove=None):
    return {"schema_version": 1, "variant": variant, "flavor": flavor,
            "platform": "linux/amd64", "package_manager": manager,
            "image": {"registry": "localhost", "namespace": "fork-preview"},
            "sources": {"sha256": "a" * 64}, "assets": {},
            "intent": {"branding": {}, "packages": {"add": [], "optional": [],
                       "repositories": [], "remove": ["fastfetch"] if remove is None else remove}}}


def package(name, version="1", architecture="all"):
    return {"name": name, "version": version, "architecture": architecture}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    config, baseline, receipt = [tmp_path / name for name in ("manifest.json", "baseline.json", "receipt.json")]
    config.write_text(json.dumps(manifest()))
    (tmp_path / "usr/lib").mkdir(parents=True)
    (tmp_path / "usr/lib/os-release").write_text('ID=ubuntu\nVARIANT_ID="grouper"\n')
    current = [package("fastfetch"), package("stock")]
    monkeypatch.setattr(MOD.INVENTORY, "snapshot", lambda manager: copy.deepcopy(current))
    calls = []

    def command(args):
        calls.append(args)
        if args[:2] == ["dpkg-query", "--control-list"]:
            return "list\nmd5sums\n", ""
        if args[:2] == ["bash", "-c"]:
            current[:] = [record for record in current if record["name"] != "fastfetch"]
        return "", ""

    monkeypatch.setattr(MOD, "command", command)
    monkeypatch.setattr(MOD, "strict_contract", lambda *args: {"status": "passed", "desktop": "gnome",
                        "checker_sha256": hashlib.sha256(MOD.CHECKER.read_bytes()).hexdigest(),
                        "marker_sha256": "b" * 64})
    baseline_hash = MOD.capture(config, baseline, tmp_path)
    calls.clear()

    def apply(**kwargs):
        args = dict(manifest=config, baseline=baseline, baseline_sha256=baseline_hash,
                    receipt=receipt, context=ROOT, root=tmp_path, desktop="gnome")
        args.update(kwargs)
        return MOD.apply(**args)

    apply.current = current
    apply.calls = calls
    apply.config = config
    apply.baseline = baseline
    apply.receipt = receipt
    apply.hash = baseline_hash
    apply.command = command
    return apply


def test_policy_validation_never_invokes_native(monkeypatch):
    monkeypatch.setattr(MOD, "command", lambda args: pytest.fail("native access during policy validation"))
    for manager, variant in (("apt", "grouper"), ("dnf", "yellowfin")):
        value = manifest(manager, variant)
        assert MOD.validate_intent(value["intent"]["packages"], manager, variant, "gnome")["policy_sha256"]
    assert MOD.validate_intent(manifest(remove=[])["intent"]["packages"], "pacman", "marlin", "kde")


@pytest.mark.parametrize("manager,variant,flavor,names", [
    ("apt", "grouper", "gnome", ["systemd"]), ("apt", "grouper", "gnome", ["fastfetch", "bash"]),
    ("apt", "grouper", "gnome", ["fastfetch", "fastfetch"]), ("apt", "grouper", "gnome", ["fastfetch:amd64"]),
    ("dnf", "yellowfin", "gnome", ["fastfetch.x86_64"]), ("dnf", "grouper", "gnome", ["fastfetch"]),
    ("apt", "yellowfin", "gnome", ["fastfetch"]), ("apt", "flounder", "gnome", ["fastfetch"]),
    ("dnf", "yellowfin", "kde", ["fastfetch"]), ("emerge", "guppy", "gnome", ["fastfetch"]),
])
def test_unknown_routes_protected_packages_and_selectors_fail(manager, variant, flavor, names):
    with pytest.raises(ValueError):
        MOD.validate_intent(manifest(remove=names)["intent"]["packages"], manager, variant, flavor)


@pytest.mark.parametrize("change", ["field", "duplicate-route", "package", "flavor", "schema", "scripts"])
def test_policy_is_closed(tmp_path, monkeypatch, change):
    policy = json.loads(MOD.POLICY.read_text())
    if change == "field":
        policy["override"] = True
    elif change == "duplicate-route":
        policy["routes"][1] = policy["routes"][0]
    elif change == "package":
        policy["routes"][0]["packages"] += ["systemd"]
    elif change == "flavor":
        policy["flavors"] += ["xfce"]
    elif change == "schema":
        policy["schema_version"] = True
    else:
        policy["target_removal_scripts"] = "allow"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(MOD, "POLICY", path)
    with pytest.raises(ValueError):
        MOD.policy()


def test_no_policy_override_cli(tmp_path):
    result = subprocess.run(["python3", str(PATH), "validate", "--manifest", str(tmp_path / "absent"),
                             "--policy", str(MOD.POLICY)], capture_output=True, text=True)
    assert result.returncode != 0 and "unrecognized arguments" in result.stderr


def test_exact_complete_receipt_allows_stock_version_upgrades(fixture):
    fixture.current[1]["version"] = "2"
    fixture.current.append(package("user-added"))
    result = fixture()
    assert result["after"] == [package("stock", "2"), package("user-added")]
    assert result["removed"] == ["fastfetch"] and result["status"] == "complete"
    assert result["source_sha256"] == "a" * 64 and result["stock_baseline_sha256"] == fixture.hash
    assert len(result["manifest_sha256"]) == len(result["policy_sha256"]) == 64
    assert "image_digest" not in result
    assert result["contracts"]["before"]["status"] == result["contracts"]["after"]["status"] == "passed"
    assert json.loads(fixture.receipt.read_text()) == result
    native = [args for args in fixture.calls if args[:2] == ["bash", "-c"]]
    assert len(native) == 1 and native[0][-2:] == ["apt", "fastfetch"]
    assert "QUALIFICATION" not in " ".join(native[0])


@pytest.mark.parametrize("change", ["source", "manifest", "policy", "stage", "empty", "new-field", "package", "arch"])
def test_tampered_baseline_fails_before_native(fixture, change):
    value = json.loads(fixture.baseline.read_text())
    if change in {"source", "manifest", "policy"}:
        value[change + "_sha256"] = "0" * 64
    elif change == "stage":
        value["stage"] = "desktop"
    elif change == "empty":
        value["packages"] = []
    elif change == "new-field":
        value["allow_missing"] = True
    elif change == "package":
        value["packages"].pop()
    else:
        value["packages"][0]["architecture"] = "amd64"
    fixture.baseline.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        fixture()
    assert not fixture.calls and not fixture.receipt.exists()


@pytest.mark.parametrize("change", ["missing-stock", "changed-arch", "missing-target"])
def test_additions_may_not_implicitly_remove_baseline(fixture, change):
    if change == "missing-stock":
        fixture.current.pop(1)
    elif change == "missing-target":
        fixture.current.pop(0)
    else:
        fixture.current[1]["architecture"] = "amd64"
    with pytest.raises(ValueError, match="disappeared"):
        fixture()
    assert not fixture.calls and not fixture.receipt.exists()


@pytest.mark.parametrize("phase", ["health-before", "native", "health-after", "contract-before", "contract-after"])
def test_every_failure_propagates_without_receipt(fixture, monkeypatch, phase):
    health_calls = 0
    contract_calls = 0

    def command(args):
        nonlocal health_calls
        if args == ["dpkg", "--audit"]:
            health_calls += 1
            if (phase == "health-before" and health_calls == 1) or (phase == "health-after" and health_calls == 2):
                raise subprocess.CalledProcessError(41, args)
        if phase == "native" and args[:2] == ["bash", "-c"]:
            raise subprocess.CalledProcessError(42, args)
        return fixture.command(args)

    def contract(*args):
        nonlocal contract_calls
        contract_calls += 1
        if (phase == "contract-before" and contract_calls == 1) or (phase == "contract-after" and contract_calls == 2):
            raise MOD.ProtectionError("contract failed")
        return {"status": "passed"}

    monkeypatch.setattr(MOD, "command", command)
    monkeypatch.setattr(MOD, "strict_contract", contract)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        fixture()
    assert not fixture.receipt.exists()
    if phase in {"health-before", "contract-before"}:
        assert not any(args[:2] == ["bash", "-c"] for args in fixture.calls)


@pytest.mark.parametrize("change", ["collateral", "added", "version", "no-removal"])
def test_complete_after_inventory_must_match_exact_delta(fixture, monkeypatch, change):
    def command(args):
        if args[:2] != ["bash", "-c"]:
            return fixture.command(args)
        if change != "no-removal":
            fixture.current.pop(0)
        if change == "collateral":
            fixture.current.clear()
        elif change == "added":
            fixture.current.append(package("unexpected"))
        elif change == "version":
            fixture.current[0]["version"] = "2"
        return "", ""
    monkeypatch.setattr(MOD, "command", command)
    with pytest.raises(ValueError, match="unexpected package delta"):
        fixture()
    assert not fixture.receipt.exists()


@pytest.mark.parametrize("script", ["prerm", "postrm", "triggers"])
def test_dpkg_target_scripts_are_not_qualified(fixture, monkeypatch, script):
    monkeypatch.setattr(MOD, "command", lambda args: ("list\n" + script + "\n", "")
                       if args[:2] == ["dpkg-query", "--control-list"] else fixture.command(args))
    with pytest.raises(ValueError, match="not qualified"):
        fixture()
    assert not any(args[:2] == ["bash", "-c"] for args in fixture.calls)
    assert not fixture.receipt.exists()


def test_rpm_health_and_target_script_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(MOD, "command", lambda args: (calls.append(args) or "", ""))
    MOD.health("dnf")
    MOD.reject_target_scripts("dnf")
    assert calls == [["rpm", "--verifydb"], ["dnf", "-q", "check"],
                     ["rpm", "-q", "--scripts", "--", "fastfetch"],
                     ["rpm", "-q", "--triggers", "--", "fastfetch"],
                     ["rpm", "-q", "--filetriggers", "--", "fastfetch"]]
    monkeypatch.setattr(MOD, "command", lambda args: ("postun scriptlet", ""))
    with pytest.raises(ValueError, match="not qualified"):
        MOD.reject_target_scripts("dnf")


@pytest.mark.parametrize("manager", ["apt", "dnf"])
def test_native_health_diagnostics_are_failure_even_exit_zero(monkeypatch, manager):
    monkeypatch.setattr(MOD, "command", lambda args: ("unhealthy", ""))
    with pytest.raises(ValueError, match="not clean"):
        MOD.health(manager)


def test_strict_contract_freshness_and_checker_identity(tmp_path, monkeypatch):
    marker = tmp_path / "usr/share/tunaos/experience-contracts/gnome"
    marker.parent.mkdir(parents=True)
    clean = "desktop=gnome\nexperience=projectbluefin/bluefin-lts\nvalidated_at_build=true\n"
    output = "desktop experience contract passed: gnome (projectbluefin/bluefin-lts)\n"
    marker.write_text(clean)
    monkeypatch.setattr(MOD, "command", lambda args: (output, ""))
    with pytest.raises(ValueError, match="regular file"):
        MOD.strict_contract(ROOT, tmp_path, "gnome")
    assert not marker.exists()  # A stale success cannot survive a no-op checker.

    def command(args):
        assert args == ["bash", str(ROOT / "build_scripts/checks/verify-desktop-experience.sh"), "gnome"]
        marker.write_text(clean)
        return output, ""
    monkeypatch.setattr(MOD, "command", command)
    result = MOD.strict_contract(ROOT, tmp_path, "gnome")
    assert result["status"] == "passed" and len(result["checker_sha256"]) == 64
    fake = tmp_path / "context/build_scripts/checks/verify-desktop-experience.sh"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nexit 0\n")
    with pytest.raises(ValueError, match="differs from the committed"):
        MOD.strict_contract(fake.parents[2], tmp_path, "gnome")


@pytest.mark.parametrize("kind", ["waived", "wrong-desktop", "wrong-experience", "duplicate", "missing-log", "failure-log"])
def test_strict_contract_rejects_false_success(tmp_path, monkeypatch, kind):
    marker = tmp_path / "usr/share/tunaos/experience-contracts/gnome"
    marker.parent.mkdir(parents=True)
    content = "desktop=gnome\nexperience=projectbluefin/bluefin-lts\nvalidated_at_build=true\n"
    output = "desktop experience contract passed: gnome (projectbluefin/bluefin-lts)\n"
    if kind == "waived":
        content += "waived_requirements=1\n"
    elif kind == "wrong-desktop":
        content = content.replace("desktop=gnome", "desktop=kde")
    elif kind == "wrong-experience":
        content = content.replace("projectbluefin/bluefin-lts", "fake")
    elif kind == "duplicate":
        content += "validated_at_build=true\n"
    elif kind == "missing-log":
        output = ""
    else:
        output += "TUNAOS_DESKTOP_CONTRACT_FAIL desktop=gnome\n"
    def command(args):
        marker.write_text(content)
        return output, ""
    monkeypatch.setattr(MOD, "command", command)
    with pytest.raises(ValueError):
        MOD.strict_contract(ROOT, tmp_path, "gnome")


def test_failed_subprocess_stdout_is_not_success(monkeypatch):
    def fail(*args, **kwargs):
        assert kwargs["check"] is True
        raise subprocess.CalledProcessError(41, args[0], output="valid-looking output")
    monkeypatch.setattr(MOD.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        MOD.command(["dpkg-query", "--control-list", "fastfetch"])


def test_symlink_baseline_and_existing_receipt_fail(fixture, tmp_path):
    real = tmp_path / "real.json"
    fixture.baseline.rename(real)
    fixture.baseline.symlink_to(real)
    with pytest.raises(ValueError, match="symlinks"):
        fixture()
    fixture.baseline.unlink()
    real.rename(fixture.baseline)
    fixture.receipt.write_text("{}")
    with pytest.raises(ValueError, match="output must be new"):
        fixture()
    assert not fixture.calls


@pytest.mark.parametrize("dependent", [False, True])
def test_native_dpkg_fixture_exact_optional_stock_removal(tmp_path, monkeypatch, dependent):
    """Native dependency/database proof only; fixture fastfetch is NOT real fastfetch."""
    commands = {name: shutil.which(name, path="/usr/bin:/bin") for name in ("dpkg", "dpkg-query", "dpkg-deb", "apt-get")}
    if not all(commands.values()):
        pytest.skip("native dpkg and apt toolchain unavailable")
    root = tmp_path / "root"
    root.mkdir()
    (root / "usr/lib").mkdir(parents=True)
    (root / "usr/lib/os-release").write_text('ID=ubuntu\nVARIANT_ID="grouper"\n')
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("dpkg", "dpkg-query", "apt-get"):
        if name == "dpkg":
            flags = f'--root="{root}" --force-not-root'
        elif name == "dpkg-query":
            flags = f'--admindir="{root}/var/lib/dpkg"'
        else:
            flags = f'-o Dir="{root}" -o Dir::State::status="{root}/var/lib/dpkg/status" -o Debug::NoLocking=1'
        path = bindir / name
        path.write_text(f'#!/bin/sh\nexec "{commands[name]}" {flags} "$@"\n')
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:/usr/sbin:/usr/bin:/sbin:/bin")
    monkeypatch.delenv("TUNAOS_FORK_REMOVAL_QUALIFICATION", raising=False)
    # Contract execution is stubbed because the fixture contains no desktop.
    # This pass is not GNOME, real-fastfetch, full-image, boot or install proof.
    monkeypatch.setattr(MOD, "strict_contract", lambda *args: {"status": "fixture-stub-only"})

    def install(name, depends=""):
        control = tmp_path / name / "DEBIAN"
        control.mkdir(parents=True)
        (control / "control").write_text(
            f"Package: {name}\nVersion: 1\nArchitecture: all\nMaintainer: Fixture <fixture@example.invalid>\n"
            + (f"Depends: {depends}\n" if depends else "") + "Description: private native fixture\n")
        payload = control.parent / "usr/share/fixture" / name
        payload.parent.mkdir(parents=True)
        payload.write_text(name + "\n")
        archive = tmp_path / f"{name}.deb"
        subprocess.run([commands["dpkg-deb"], "--build", str(control.parent), str(archive)], check=True, capture_output=True)
        subprocess.run(["dpkg", "--install", str(archive)], check=True, capture_output=True)

    install("stock")
    install("fastfetch")
    config, baseline, receipt = [tmp_path / name for name in ("manifest.json", "baseline.json", "receipt.json")]
    config.write_text(json.dumps(manifest()))
    baseline_hash = MOD.capture(config, baseline, root)
    install("added", "fastfetch" if dependent else "")
    before = MOD.INVENTORY.snapshot("apt")
    if dependent:
        with pytest.raises(subprocess.CalledProcessError):
            MOD.apply(config, baseline, baseline_hash, receipt, ROOT, root, "gnome")
        assert MOD.INVENTORY.snapshot("apt") == before
        assert not receipt.exists()
        assert (root / "usr/share/fixture/fastfetch").read_text() == "fastfetch\n"
        return
    result = MOD.apply(config, baseline, baseline_hash, receipt, ROOT, root, "gnome")
    assert result["before"] == before
    assert result["after"] == [r for r in before if r["name"] != "fastfetch"]
    assert not (root / "usr/share/fixture/fastfetch").exists()
    for name in ("stock", "added"):
        assert (root / "usr/share/fixture" / name).read_text() == name + "\n"
    assert json.loads(receipt.read_text())["source_sha256"] == "a" * 64


@pytest.mark.parametrize("contents", ["ID=debian\nVARIANT_ID=grouper\n", "ID=ubuntu\nVARIANT_ID=yellowfin\n",
                                    "ID=ubuntu\nID=ubuntu\nVARIANT_ID=grouper\n", "ID=ubuntu\n"])
def test_runtime_os_identity_refuses_wrong_family_and_ambiguous_fields(fixture, tmp_path, contents):
    (tmp_path / "usr/lib/os-release").write_text(contents)
    with pytest.raises(ValueError):
        fixture()
    assert not fixture.calls and not fixture.receipt.exists()


def test_runtime_architecture_mismatch_prevents_mutation(fixture, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(MOD.os, "uname", lambda: SimpleNamespace(machine="aarch64"))
    with pytest.raises(ValueError, match="architecture"):
        fixture()
    assert not fixture.calls



def test_repeat_complete_verifies_without_native_removal(fixture, tmp_path):
    original = fixture()
    fixture.calls.clear()
    before_bytes = fixture.receipt.read_bytes()
    result = MOD.verify_complete(fixture.config, fixture.baseline, fixture.receipt, ROOT, tmp_path, "gnome")
    assert result == original and fixture.receipt.read_bytes() == before_bytes
    assert fixture.calls == [["dpkg", "--audit"], ["apt-get", "check"]]


@pytest.mark.parametrize("change", ["pending", "field", "source", "baseline", "removed", "delta",
                                    "contract", "checker", "missing-stock", "reinstalled", "upgraded"])
def test_repeat_complete_fails_closed(fixture, tmp_path, change):
    fixture()
    fixture.calls.clear()
    value = json.loads(fixture.receipt.read_text())
    if change == "pending":
        value["status"] = "pending-removal"
    elif change == "field":
        value["allow_missing"] = True
    elif change == "source":
        value["source_sha256"] = "0" * 64
    elif change == "baseline":
        value["stock_baseline_sha256"] = "0" * 64
    elif change == "removed":
        value["removed"] += ["stock"]
    elif change == "delta":
        value["after"] = []
    elif change == "contract":
        value["contracts"]["before"]["status"] = "waived"
    elif change == "checker":
        value["contracts"]["after"]["checker_sha256"] = "0" * 64
    elif change == "missing-stock":
        fixture.current.clear()
    elif change == "reinstalled":
        fixture.current.insert(0, package("fastfetch"))
    else:
        fixture.current[0]["version"] = "2"
    fixture.receipt.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        MOD.verify_complete(fixture.config, fixture.baseline, fixture.receipt, ROOT, tmp_path, "gnome")
    assert not fixture.calls


def test_repeat_complete_needs_fresh_strict_contract(fixture, monkeypatch, tmp_path):
    fixture()
    fixture.calls.clear()
    monkeypatch.setattr(MOD, "strict_contract", lambda *args: {"status": "waived"})
    with pytest.raises(ValueError, match="fresh desktop contract"):
        MOD.verify_complete(fixture.config, fixture.baseline, fixture.receipt, ROOT, tmp_path, "gnome")
    assert not any(args[:2] == ["bash", "-c"] for args in fixture.calls)
