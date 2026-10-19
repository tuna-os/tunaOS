"""Executed-check evidence is partial and never permission to remove packages."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build_scripts/lib/contract-package-owners.py"
HOOK = SCRIPT.with_suffix(".sh")
CHECK = ROOT / "build_scripts/checks/verify-desktop-experience.sh"
spec = importlib.util.spec_from_file_location("contract_package_owners", SCRIPT)
owners = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owners)


def answer(stdout="", stderr="", rc=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=rc)


def event(kind="command", selector="gnome-shell", paths=None):
    return {"kind": kind, "selector": selector, "source_line": 42,
            "selected_paths": [] if paths is None else paths}


def test_dpkg_preserves_multiple_owners_and_architectures(monkeypatch):
    commands = []

    def query(command):
        commands.append(command)
        if "--search" in command:
            return answer("shell-common:amd64, shell-common:i386: /usr/bin/test\n")
        arch = command[-1].split(":")[1]
        return answer(f"shell-common\t2:50.0-1\t{arch}\tinstalled\n")

    monkeypatch.setattr(owners, "query", query)
    result = owners.native_owners("apt", "/usr/bin/test")
    assert result["ownership_status"] == "owned"
    assert {r["architecture"] for r in result["owners"]} == {"amd64", "i386"}
    assert all(r["name"] == "shell-common" and r["version"] == "2:50.0-1" for r in result["owners"])
    assert commands[0] == ["dpkg-query", "--search", "--", "/usr/bin/test"]
    assert commands[1][-2:] == ["--", "shell-common:amd64"]


@pytest.mark.parametrize("bad", [
    answer("valid: /usr/bin/test\n", "database failed", 2),
    answer("diversion by other from: /usr/bin/test\n"),
    answer("valid: /usr/bin/different\n"),
    answer("valid*: /usr/bin/test\n"),
    answer(""),
])
def test_dpkg_failed_or_ambiguous_search_is_never_an_owner(monkeypatch, bad):
    monkeypatch.setattr(owners, "query", lambda _: bad)
    with pytest.raises(owners.EvidenceError):
        owners.native_owners("apt", "/usr/bin/test")


@pytest.mark.parametrize("installed", [
    answer("valid\t1\tamd64\tconfig-files\n"),
    answer("other\t1\tamd64\tinstalled\n"),
    answer("valid\t1\ti386\tinstalled\n"),
    answer("valid\t1\tamd64\tinstalled\n", "database failed", 2),
])
def test_dpkg_owner_must_be_installed_with_exact_identity(monkeypatch, installed):
    monkeypatch.setattr(owners, "query", lambda command:
                        answer("valid:amd64: /usr/bin/test\n") if "--search" in command else installed)
    with pytest.raises(owners.EvidenceError):
        owners.native_owners("apt", "/usr/bin/test")


@pytest.mark.parametrize("manager,result", [
    ("apt", answer(stderr="dpkg-query: no path found matching pattern /usr/bin/test\n", rc=1)),
    ("dnf", answer("file /usr/bin/test is not owned by any package\n", rc=1)),
])
def test_native_unowned_is_explicit(monkeypatch, manager, result):
    monkeypatch.setattr(owners, "query", lambda _: result)
    assert owners.native_owners(manager, "/usr/bin/test") == {"ownership_status": "unowned", "owners": []}


def test_rpm_preserves_version_arch_and_discards_partial_failure(monkeypatch):
    monkeypatch.setattr(owners, "query", lambda _: answer("gnome-shell\t0:50.0-3.el10\tx86_64\n"))
    result = owners.native_owners("dnf", "/usr/bin/gnome-shell")
    assert result["owners"] == [{"name": "gnome-shell", "version": "0:50.0-3.el10", "architecture": "x86_64"}]
    monkeypatch.setattr(owners, "query", lambda _: answer("gnome-shell\t0:50.0-3.el10\tx86_64\n", rc=1))
    with pytest.raises(owners.EvidenceError, match="exited 1"):
        owners.native_owners("dnf", "/usr/bin/gnome-shell")


@pytest.mark.parametrize("path", ["gnome-shell", "bash", "/a/*", "/a/[x]", "/a/?", "/a/\\name", "/a/\nname"])
def test_ambiguous_or_nonabsolute_paths_are_not_queried(monkeypatch, path):
    monkeypatch.setattr(owners, "query", lambda _: pytest.fail("must not query ambiguous path"))
    assert owners.observe_path("apt", path)["ownership_status"] == "unresolved"


def test_unknown_directory_and_query_failure_are_explicit(tmp_path, monkeypatch):
    assert owners.observe_path("apt", str(tmp_path / "missing"))["ownership_status"] == "unresolved"
    assert "directories are not expanded" in owners.observe_path("apt", str(tmp_path))["reason"]
    file = tmp_path / "present"
    file.write_text("data")
    monkeypatch.setattr(owners, "query", lambda _: answer("pretend valid output", "database failed", 2))
    result = owners.observe_path("apt", str(file))
    assert result["ownership_status"] == "query_failed" and not result["owners"]
    assert "exited 2" in result["reason"]


def test_symlink_and_target_ownership_are_both_observed(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.write_text("data")
    link = tmp_path / "link"
    link.symlink_to(target)
    queried = []

    def native(manager, path):
        queried.append(path)
        return {"ownership_status": "owned", "owners": [{"name": Path(path).name, "version": "1", "architecture": "amd64"}]}

    monkeypatch.setattr(owners, "native_owners", native)
    report = owners.report([event(paths=[str(link)])], "apt", "gnome", 0, True, 0, CHECK)
    assert queried == [str(link), str(target)]
    assert {p["name"] for p in report["observed_owner_packages"]} == {"link", "target"}
    assert report["authorizes_removal"] is False
    assert report["coverage"]["complete"] is False
    assert "GNOME schema and version checks" in report["coverage"]["excludes"]


def test_unit_paths_use_systemd_order_and_resolve_aliases(tmp_path, monkeypatch):
    high, low = tmp_path / "high", tmp_path / "low"
    high.mkdir()
    low.mkdir()
    (low / "gdm.service").write_text("lower")
    (high / "real.service").write_text("higher")
    (high / "gdm.service").symlink_to("real.service")
    commands = []

    def query(command):
        commands.append(command)
        return answer(f"{high}\n{low}\n")

    monkeypatch.setattr(owners, "query", query)
    assert owners.unit_paths("unit", "gdm") == [str(high / "gdm.service")]
    assert commands == [["systemd-analyze", "--system", "unit-paths"]]
    assert owners.unit_paths("user_unit", "gdm") == [str(high / "gdm.service")]
    assert commands[-1][1] == "--user"


def test_unit_listing_without_fragment_is_an_unresolved_observation(monkeypatch):
    monkeypatch.setattr(owners, "query", lambda _: answer("", "unavailable", 1))
    report = owners.report([event("unit", "gdm")], "apt", "gnome", 0, True, 0, CHECK)
    assert report["contract"]["status"] == "passed"
    assert "resolution_error" in report["observations"][0]
    assert report["observed_owner_packages"] == []


@pytest.mark.parametrize("exit_code,completed,waived,status", [
    (0, True, 0, "passed"), (1, False, 0, "failed"),
    (0, True, 2, "waived"), (0, False, 0, "incomplete"),
    (2, False, 1, "failed"),
])
def test_contract_failure_waiver_and_incompletion_never_become_pass(exit_code, completed, waived, status):
    report = owners.report([event("waiver", "require_command")], "apt", "xfce", exit_code, completed, waived, CHECK)
    assert report["contract"]["status"] == status
    assert report["contract"]["waived_requirements"] == waived
    assert report["observations"][0]["check_status"] == "waived"
    assert report["observed_owner_packages"] == []


@pytest.mark.parametrize("raw", [b"", b"command\0missing", b"bad\0x\01\00\0", b"command\0x\0line\00\0", b"command\0x\01\02\0one\0"])
def test_malformed_event_stream_is_rejected(tmp_path, raw):
    stream = tmp_path / "events"
    stream.write_bytes(raw)
    with pytest.raises(owners.EvidenceError):
        owners.read_events(stream)


def run_hook(tmp_path, body, extra_env=None):
    output = tmp_path / "evidence.json"
    env = {**os.environ, "TUNAOS_CONTRACT_OWNER_EVIDENCE": str(output), "TUNAOS_CONTRACT_OWNER_MANAGER": "apt", **(extra_env or {})}
    script = f'''set -euo pipefail
source '{HOOK}'
desktop=gnome
mode=build
contract_owner_evidence_init '{CHECK}'
{body}
'''
    result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
    return result, output


def test_shell_hook_records_actual_glob_winners_and_waivers(tmp_path):
    match = tmp_path / "asset.desktop"
    match.write_text("payload")
    result, output = run_hook(tmp_path, f'''
contract_owner_record glob '{tmp_path}/*.desktop'
contract_owner_record waiver require_command
TUNAOS_CONTRACT_WAIVED=1
TUNAOS_OWNER_COMPLETED=1
contract_owner_evidence_finish 0
''')
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["contract"]["status"] == "waived"
    assert report["observations"][0]["paths"][0]["path"] == str(match)
    assert report["observations"][0]["paths"][0]["ownership_status"] == "unowned"
    assert report["observations"][1]["check_status"] == "waived"


def test_existing_or_symlink_output_is_refused_before_contract_work(tmp_path):
    output = tmp_path / "evidence.json"
    output.write_text("keep me")
    result, _ = run_hook(tmp_path, "echo contract-ran")
    assert result.returncode != 0 and "contract-ran" not in result.stdout
    assert output.read_text() == "keep me"
    output.unlink()
    target = tmp_path / "target"
    target.write_text("also keep me")
    output.symlink_to(target)
    result, _ = run_hook(tmp_path, "echo contract-ran")
    assert result.returncode != 0 and "contract-ran" not in result.stdout
    assert target.read_text() == "also keep me"


def test_query_timeout_is_explicit(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 15)

    monkeypatch.setattr(owners.subprocess, "run", timeout)
    with pytest.raises(owners.EvidenceError, match="unavailable"):
        owners.query(["dpkg-query", "--search", "--", "/usr/bin/test"])


def run_contract_helpers(tmp_path, body, enabled=True):
    """Execute the real checker preamble/helpers/trap, without image writes."""
    import shutil

    checks = tmp_path / "build_scripts/checks"
    library = tmp_path / "build_scripts/lib"
    checks.mkdir(parents=True)
    library.mkdir()
    shutil.copy2(SCRIPT, library / SCRIPT.name)
    shutil.copy2(HOOK, library / HOOK.name)
    prefix = CHECK.read_text().split('\ncase "$desktop" in\n', 1)[0]
    runner = checks / CHECK.name
    runner.write_text(prefix + "\n" + body + "\n")
    output = tmp_path / "owners.json"
    env = {**os.environ, "TUNAOS_CONTRACT_OWNER_MANAGER": "apt"}
    env.pop("TUNAOS_CONTRACT_OWNER_EVIDENCE", None)
    if enabled:
        env["TUNAOS_CONTRACT_OWNER_EVIDENCE"] = str(output)
    result = subprocess.run(["bash", str(runner), "gnome"], env=env, text=True, capture_output=True)
    return result, output


def test_real_check_helpers_capture_only_selected_successes(tmp_path):
    asset = tmp_path / "session.desktop"
    asset.write_text("fixture")
    result, output = run_contract_helpers(tmp_path, f'''
systemctl() {{
    local arg
    for arg in "$@"; do
        if [[ "$arg" == known.service ]]; then
            printf 'known.service enabled\n'
            return 0
        fi
    done
    return 1
}}
require_command /bin/sh
require_glob '{asset}'
require_any_glob '{tmp_path}/missing*' '{asset}'
require_unit known
require_any_unit missing known
require_user_unit known
require_any_user_unit missing known
TUNAOS_OWNER_COMPLETED=1
''')
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert report["contract"] == {"status": "passed", "exit_code": 0, "completed": True, "waived_requirements": 0}
    assert [r["kind"] for r in report["observations"]] == ["command", "glob", "glob", "unit", "unit", "user_unit", "user_unit"]
    assert all(r["check_status"] == "passed" and r["source_line"] > 0 for r in report["observations"])
    assert "missing" not in json.dumps(report["observations"])
    assert report["observations"][2]["selector"] == str(asset)


def test_real_early_failure_keeps_explicit_failed_partial_report(tmp_path):
    asset = tmp_path / "session.desktop"
    asset.write_text("fixture")
    result, output = run_contract_helpers(tmp_path, f'''
require_glob '{asset}'
require_command /__tuna_contract_owner_missing_command__
TUNAOS_OWNER_COMPLETED=1
''')
    assert result.returncode == 1
    report = json.loads(output.read_text())
    assert report["contract"]["status"] == "failed"
    assert report["contract"]["completed"] is False
    assert len(report["observations"]) == 1


def test_real_waiver_is_recorded_without_positive_evidence(tmp_path):
    result, output = run_contract_helpers(tmp_path, '''
IS_HUMMINGBIRD=true
require_command /__tuna_contract_owner_missing_command__
TUNAOS_OWNER_COMPLETED=1
''')
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["contract"]["status"] == "waived"
    assert report["contract"]["waived_requirements"] == 1
    assert report["observations"] == [{"kind": "waiver", "selector": "require_command", "source_line": report["observations"][0]["source_line"], "check_status": "waived", "paths": []}]
    assert report["observed_owner_packages"] == []


def test_stock_helpers_do_not_load_collector_or_make_native_queries(tmp_path):
    result, output = run_contract_helpers(tmp_path, '''
python3() { echo unexpected-python >&2; return 1; }
dpkg-query() { echo unexpected-owner-query >&2; return 1; }
require_command /bin/sh
[[ "$_TUNAOS_OWNER_ENABLED" == 0 ]]
if declare -F contract_owner_record >/dev/null; then exit 7; fi
''', enabled=False)
    assert result.returncode == 0, result.stderr
    assert "unexpected-" not in result.stderr
    assert not output.exists()


def test_opt_in_rejects_runtime_and_unsupported_scope(tmp_path):
    for mode, desktop, manager in [("--runtime", "gnome", "apt"), ("build", "kde", "apt"), ("build", "gnome", "pacman")]:
        env = {**os.environ, "TUNAOS_CONTRACT_OWNER_MANAGER": manager, "TUNAOS_CONTRACT_OWNER_EVIDENCE": str(tmp_path / "no-report.json")}
        result = subprocess.run(["bash", "-c", f"set -euo pipefail; source '{HOOK}'; mode='{mode}'; desktop='{desktop}'; contract_owner_evidence_init '{CHECK}'"], env=env, text=True, capture_output=True)
        assert result.returncode != 0
        assert not (tmp_path / "no-report.json").exists()


def test_query_budget_exhaustion_never_calls_native_tool(monkeypatch):
    monkeypatch.setattr(owners, "QUERY_DEADLINE", 0)
    monkeypatch.setattr(owners.subprocess, "run", lambda *args, **kwargs: pytest.fail("budget exhausted"))
    with pytest.raises(owners.EvidenceError, match="budget exhausted"):
        owners.query(["rpm", "-qf", "/usr/bin/test"])


@pytest.mark.parametrize("raw", [
    b"x" * (owners.MAX_BYTES + 1),
    b"command\0x\x001\x00513\0",
    b"waiver\0require_command\x001\x000\0" * (owners.MAX_CHECKS + 1),
])
def test_event_stream_limits_fail_explicitly(tmp_path, raw):
    stream = tmp_path / "oversized"
    stream.write_bytes(raw)
    with pytest.raises(owners.EvidenceError):
        owners.read_events(stream)


def test_completed_contract_without_events_is_not_a_successful_report(tmp_path):
    result, output = run_hook(tmp_path, "TUNAOS_OWNER_COMPLETED=1; contract_owner_evidence_finish 0")
    assert result.returncode != 0
    assert "emitted no check evidence" in result.stderr
    assert not output.exists()


def test_existing_output_created_during_run_is_not_overwritten(tmp_path):
    result, output = run_hook(tmp_path, '''
contract_owner_record waiver require_command
printf 'preserve' > "$TUNAOS_CONTRACT_OWNER_EVIDENCE"
contract_owner_evidence_finish 1
''')
    assert result.returncode != 0
    assert output.read_text() == "preserve"
