"""Protected native-package removal (RFC 017, #4352), dnf and apt first.

Removal stays rejected for every cell without admission evidence; these tests
cover the parser rules, the base-contract items the protection is projected
from, and the transaction protocol against stubbed native tools. Real dnf/apt
transactions in disposable roots are the per-cell evidence (PR-8), not run here.
"""
from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package_removal_config_under_test", ROOT / "scripts/lib/tunaos_config.py")
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
MANAGERS = {"yellowfin": "dnf", "grouper": "apt", "guppy": "emerge", "marlin": "pacman", "sailfin": "zypper"}
LIB = ROOT / "build_scripts/lib/package-removal.sh"
CONTRACT = ROOT / "build_scripts/checks/verify-base-contract.sh"


def fork(variant="yellowfin", defaults=None, **packages):
    source = copy.deepcopy(config.load())
    source["variants"][variant]["packages"] = packages
    if defaults:
        source["defaults"]["packages"] = defaults
    return source


# ── parser and resolver ──────────────────────────────────────────────────────

def test_defaults_removal_stays_rejected_even_for_an_admitted_variant(monkeypatch):
    monkeypatch.setitem(config.REMOVAL_ADMISSION, "yellowfin", "evidence-1")
    with pytest.raises(config.ConfigError, match="schema: removals are not supported in .defaults.packages"):
        config.validate(fork(defaults={"remove": ["nano"]}))


def test_variant_removal_is_rejected_until_the_cell_is_admitted():
    with pytest.raises(config.ConfigError, match="unsupported-family: package removals are not supported"):
        config.validate(fork(remove=["nano"]))


def test_an_admitted_dnf_cell_compiles_a_remove_row(monkeypatch):
    monkeypatch.setitem(config.REMOVAL_ADMISSION, "yellowfin", "evidence-1")
    source = fork(add=["htop"], remove=["nano"])
    rows = [r for r in config.render_image_packages(source, MANAGERS | {"x": "dnf"}).splitlines() if not r.startswith("#")]
    assert rows == ["yellowfin\tdnf\tadd\thtop", "yellowfin\tdnf\tremove\tnano"]


@pytest.mark.parametrize("variant", ["guppy", "marlin", "sailfin"])
def test_families_without_an_adapter_fail_before_any_manager_runs(monkeypatch, variant):
    monkeypatch.setitem(config.REMOVAL_ADMISSION, variant, "evidence-1")
    name = "app-editors/nano" if variant == "guppy" else "nano"
    source = fork(variant, remove=[name]) if variant != "guppy" else fork(variant, remove=["nano"])
    with pytest.raises(config.ConfigError, match="unsupported-family|schema"):
        config.image_packages(source, MANAGERS | {n: "dnf" for n in source["variants"] if n not in MANAGERS})


def test_the_same_name_added_and_removed_is_a_conflict(monkeypatch):
    monkeypatch.setitem(config.REMOVAL_ADMISSION, "yellowfin", "evidence-1")
    with pytest.raises(config.ConfigError, match="conflict"):
        config.validate(fork(add=["nano"], remove=["nano"]))


@pytest.mark.parametrize("name", ["-y", "--nodeps", "a b", "a\nb", "nano*", "nano.x86_64", "nano/x", "nano.rpm", "pkg:amd64"])
def test_option_like_glob_and_selector_names_are_schema_errors(monkeypatch, name):
    monkeypatch.setitem(config.REMOVAL_ADMISSION, "yellowfin", "evidence-1")
    with pytest.raises(config.ConfigError):
        config.validate(fork(remove=[name]))


# ── base contract items ──────────────────────────────────────────────────────

def make_tree(tmp_path, drop=()):
    files = ["usr/lib/modules/6.1/vmlinuz", "usr/lib/modules/6.1/modules.dep", "usr/lib/modules/6.1/initramfs.img",
             "usr/bin/dracut", "usr/bin/bootupctl", "usr/bin/rpm", "usr/bin/dnf",
             "usr/lib/systemd/system/NetworkManager.service", "usr/bin/ostree", "usr/bin/bootc",
             "usr/lib/systemd/systemd", "usr/bin/dbus-broker"]
    for name in files:
        if name not in drop:
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
    return tmp_path


def contract(tmp_path, *args, drop=()):
    env = {"PATH": "/usr/bin:/bin", "TUNAOS_CONTRACT_ROOT": str(make_tree(tmp_path, drop))}
    return subprocess.run(["bash", str(CONTRACT), *args], capture_output=True, text=True, env=env)


def test_the_base_contract_names_every_protected_capability_class(tmp_path):
    result = contract(tmp_path, "--list-contract")
    assert result.returncode == 0, result.stderr
    classes = {line.split("\t")[0] for line in result.stdout.splitlines()}
    assert {"kernel", "kernel-modules", "initramfs", "initramfs-generator", "boot-loader-tool", "package-manager",
            "network-unit", "image-store-tool", "update-tool", "init", "system-bus"} <= classes
    assert contract(tmp_path).returncode == 0


@pytest.mark.parametrize("drop,item", [
    ("usr/lib/modules/6.1/vmlinuz", "kernel"), ("usr/lib/modules/6.1/initramfs.img", "initramfs"),
    ("usr/bin/bootupctl", "boot-loader-tool"), ("usr/bin/rpm", "package-manager"),
    ("usr/lib/systemd/system/NetworkManager.service", "network-unit"), ("usr/bin/ostree", "image-store-tool"),
])
def test_a_missing_contract_item_fails_the_build_check(tmp_path, drop, item):
    result = contract(tmp_path, drop=(drop,))
    assert result.returncode == 1 and f"contract-items-missing items={item}" in result.stderr


# ── transaction protocol with stubbed native tools ───────────────────────────

STUB_RPM = r'''#!/usr/bin/env bash
S="$STATE"
inv() { cat "$S/inv"; }
case "$1" in
-qa) n=$(($(cat "$S/qa" 2>/dev/null || echo 0)+1)); echo $n >"$S/qa"
     inv | while read -r p; do echo "$p-0:1-1.x86_64"; done
     [[ -f "$S/drift" && $n -ge 3 ]] && echo "drifted-0:1-1.x86_64"; exit 0 ;;
-q) shift 4; grep -qx -- "$1" "$S/inv" && echo "$1" || { echo "package $1 is not installed"; exit 1; } ;;
-qf) shift 4; awk -F'\t' -v p="$1" '$1==p {print $2; f=1} END {exit !f}' "$S/owners" || { echo "file $1 is not owned by any package"; exit 1; } ;;
-e) shift 3; for p in "$@"; do grep -qx -- "$p" "$S/needed" && exit 1; done; exit 0 ;;
esac
'''
STUB_DNF = r'''#!/usr/bin/env bash
echo "dnf $*" >>"$STATE/log"
[[ -f "$STATE/txfail" ]] && exit 1
args=(); seen=0
for a in "$@"; do [[ "$a" == -- ]] && { seen=1; continue; }; ((seen)) && args+=("$a"); done
for p in "${args[@]}" $(cat "$STATE/cascade" 2>/dev/null); do sed -i "/^$p\$/d" "$STATE/inv"; done
'''
STUB_DPKG = r'''#!/usr/bin/env bash
S="$STATE"
case "$*" in
*'${Essential}'*) cat "$S/essential" 2>/dev/null ;;
*'${Architecture}'*) while read -r p; do echo "$p:amd64=1"; done <"$S/inv" ;;
-W*) shift 3; shift; grep -qx -- "$1" "$S/inv" && echo "$1" || exit 1 ;;
-S*) shift 2; awk -F'\t' -v p="$1" '$1==p {print $2 ": " p; f=1} END {exit !f}' "$S/owners" || exit 1 ;;
esac
'''
STUB_APT = r'''#!/usr/bin/env bash
echo "apt-get $*" >>"$STATE/log"
args=(); seen=0
for a in "$@"; do [[ "$a" == -- ]] && { seen=1; continue; }; ((seen)) && args+=("$a"); done
if [[ " $* " == *" --simulate "* ]]; then
  for p in "${args[@]}" $(cat "$STATE/cascade" 2>/dev/null); do echo "Remv $p [1]"; done
  [[ -f "$STATE/upgrade" ]] && echo "Inst other [1] (2 repo)"; exit 0
fi
[[ -f "$STATE/txfail" ]] && exit 1
for p in "${args[@]}" $(cat "$STATE/cascade" 2>/dev/null); do sed -i "/^$p\$/d" "$STATE/inv"; done
'''


def checker(tmp_path, items="kernel\t/usr/lib/modules/6.1/vmlinuz\npackage-manager\t/usr/bin/rpm\n"):
    path = tmp_path / "contract.sh"
    path.write_text("#!/usr/bin/env bash\n[[ $1 == --list-contract ]] && printf '" + items.replace("\n", "\\n").replace("\t", "\\t") + "'\n")
    return path


def run(tmp_path, manager, requested, installed=("kernel-core", "rpm", "nano", "htop"), owners=None,
        needed=(), cascade=(), extra=(), refresh_ok=True, stubs=True, **flags):
    state, bin_dir, root = tmp_path / "state", tmp_path / "bin", tmp_path / "root"
    for d in (state, bin_dir, root):
        d.mkdir(exist_ok=True)
    (state / "inv").write_text("".join(p + "\n" for p in installed))
    (state / "owners").write_text("".join(f"{p}\t{o}\n" for p, o in (owners or {
        "/usr/lib/modules/6.1/vmlinuz": "kernel-core", "/usr/bin/rpm": "rpm"}).items()))
    (state / "needed").write_text("".join(p + "\n" for p in needed))
    (state / "cascade").write_text(" ".join(cascade))
    (state / "essential").write_text("".join(extra))
    (state / "log").touch()
    for flag in flags:
        if flags[flag]:
            (state / flag).touch()
    tools = {"dnf": {"rpm": STUB_RPM, "dnf": STUB_DNF}, "apt": {"dpkg-query": STUB_DPKG, "apt-get": STUB_APT}}
    if stubs:
        for name, body in tools.get(manager, {}).items():
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
    names = " ".join(f"'{r}'" for r in requested)
    script = (f"pkg_refresh() {{ {'true' if refresh_ok else 'false'}; }}\nsource '{LIB}'\n"
              f"tunaos_apply_removals '{root}' {names}\n")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "STATE": str(state), "PKG_MGR": manager,
           "TUNAOS_BASE_CONTRACT_CHECK": str(checker(tmp_path))}
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    receipt = root / "usr/share/tunaos/package-removal.tsv"
    return (result, (state / "inv").read_text().split(), (state / "log").read_text(),
            receipt.read_text() if receipt.exists() else None)


@pytest.mark.parametrize("manager", ["dnf", "apt"])
def test_an_exact_unprotected_removal_succeeds_and_writes_the_receipt(tmp_path, manager):
    result, inventory, log, receipt = run(tmp_path, manager, ["nano"])
    assert result.returncode == 0, result.stderr
    assert inventory == ["kernel-core", "rpm", "htop"]
    assert "removed\tnano" in receipt and "fingerprint\t" in receipt
    assert "--nodeps" not in log and "--force" not in log and "--purge" not in log


@pytest.mark.parametrize("manager", ["dnf", "apt"])
def test_a_protected_identity_is_rejected_with_its_reason_and_nothing_changes(tmp_path, manager):
    result, inventory, log, receipt = run(tmp_path, manager, ["kernel-core"])
    assert result.returncode == 1 and "::error::protected:" in result.stderr and "kernel" in result.stderr
    assert inventory == ["kernel-core", "rpm", "nano", "htop"] and receipt is None
    assert "remove -y" not in log


def test_apt_essential_packages_are_protected(tmp_path):
    result, inventory, _, receipt = run(tmp_path, "apt", ["nano"], extra=["nano\tyes\n"])
    assert result.returncode == 1 and "::error::protected:" in result.stderr and "native-essential" in result.stderr
    assert receipt is None and "nano" in inventory


def test_dnf_dependents_make_the_plan_inexact(tmp_path):
    result, inventory, log, receipt = run(tmp_path, "dnf", ["htop"], needed=["htop"])
    assert result.returncode == 1 and "::error::dependency-induced:" in result.stderr
    assert "htop" in inventory and receipt is None and "dnf remove" not in log


def test_apt_extra_removals_and_upgrades_make_the_plan_inexact(tmp_path):
    result, inventory, _, receipt = run(tmp_path, "apt", ["nano"], cascade=["htop"])
    assert result.returncode == 1 and "::error::dependency-induced:" in result.stderr and "htop" in result.stderr
    assert inventory == ["kernel-core", "rpm", "nano", "htop"] and receipt is None
    (tmp_path / "up").mkdir()
    result, *_ = run(tmp_path / "up", "apt", ["nano"], upgrade=True)
    assert result.returncode == 1 and "dependency-induced" in result.stderr


def test_a_missing_solver_names_the_prerequisite_and_runs_no_fallback(tmp_path):
    result, inventory, _, receipt = run(tmp_path, "apt", ["nano"], stubs=False)
    assert result.returncode == 1 and receipt is None
    assert "::error::" in result.stderr


def test_stale_repositories_fail_before_any_simulation(tmp_path):
    result, inventory, log, receipt = run(tmp_path, "dnf", ["nano"], refresh_ok=False)
    assert result.returncode == 1 and "::error::repository-stale:" in result.stderr
    assert log == "" and receipt is None and "nano" in inventory


def test_a_name_that_is_not_installed_is_rejected(tmp_path):
    result, _, _, receipt = run(tmp_path, "dnf", ["wget"])
    assert result.returncode == 1 and "::error::not-installed:" in result.stderr and receipt is None


@pytest.mark.parametrize("manager", ["emerge", "pacman", "zypper", ""])
def test_unsupported_families_fail_before_any_manager_runs(tmp_path, manager):
    result, _, log, receipt = run(tmp_path, manager, ["nano"])
    assert result.returncode == 1 and "::error::unsupported-family:" in result.stderr
    assert log == "" and receipt is None


@pytest.mark.parametrize("name", ["-y", "--nodeps", "a b", "a\nb", "nano*"])
def test_option_injection_is_a_schema_error_before_any_manager_runs(tmp_path, name):
    result, inventory, log, receipt = run(tmp_path, "dnf", [name])
    assert result.returncode == 1 and "::error::schema:" in result.stderr
    assert log == "" and receipt is None and "nano" in inventory


def test_an_unowned_contract_item_fails_closed(tmp_path):
    result, inventory, _, receipt = run(tmp_path, "dnf", ["nano"], owners={"/usr/bin/rpm": "rpm"})
    assert result.returncode == 1 and "::error::contract-unowned:" in result.stderr
    assert receipt is None and "nano" in inventory


def test_plan_drift_between_qualification_and_application_is_rejected(tmp_path):
    result, _, log, receipt = run(tmp_path, "dnf", ["nano"], drift=True)
    assert result.returncode == 1 and "::error::plan-drift:" in result.stderr
    assert receipt is None and "dnf remove" not in log


@pytest.mark.parametrize("manager", ["dnf", "apt"])
def test_a_failed_native_transaction_leaves_no_receipt(tmp_path, manager):
    result, _, _, receipt = run(tmp_path, manager, ["nano"], txfail=True)
    assert result.returncode == 1 and "::error::transaction-failed:" in result.stderr and receipt is None


def test_a_missing_receipt_stops_a_later_stage(tmp_path):
    script = f"source '{LIB}'\ntunaos_require_removal_receipt '{tmp_path}'\n"
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert result.returncode == 1 and "::error::receipt-missing:" in result.stderr
