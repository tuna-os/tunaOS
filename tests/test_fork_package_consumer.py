"""Execute fork package adapters with stub transactions and an isolated file root."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "build_scripts/lib/fork-packages.sh"


def manifest(manager="dnf", *, add=(), optional=(), remove=(), repositories=()):
    return {
        "schema_version": 1,
        "variant": "yellowfin",
        "flavor": "gnome",
        "platform": "linux/amd64",
        "package_manager": manager,
        "image": {"registry": "localhost", "namespace": "fork-preview"},
        "intent": {
            "branding": {},
            "packages": {
                "repositories": list(repositories),
                "remove": list(remove),
                "add": list(add),
                "optional": list(optional),
            },
        },
        "sources": {"sha256": "a" * 64},
        "assets": {},
    }


@pytest.fixture
def harness(tmp_path):
    context = tmp_path / "context"
    (context / "manifests").mkdir(parents=True)
    root = tmp_path / "root"
    root.mkdir()
    log = tmp_path / "transactions"
    script = r'''
set -euo pipefail
source "$HELPER"
uname() { printf '%s\n' "${TEST_ARCH:-x86_64}"; }
pkg_refresh() {
    printf 'refresh\n' >> "$LOG"
    [[ "${FAIL_REFRESH:-0}" == 0 ]]
}
dnf_retry() { printf 'refresh:%s\n' "$*" >> "$LOG"; [[ "${FAIL_REFRESH:-0}" == 0 ]]; }
pkg_install() {
    printf 'install:%s\n' "$*" >> "$LOG"
    for package in "$@"; do
        [[ "$package" != "${FAIL_PACKAGE:-}" ]] || return 1
    done
}
pkg_remove() { printf 'UNEXPECTED REMOVE\n' >> "$LOG"; return 1; }
tunaos_apply_fork_packages "$CONTEXT" "$ROOT"
'''

    def run(config=None, **environment):
        if config is not None:
            (context / "manifests/fork-config.json").write_text(json.dumps(config))
        env = dict(os.environ, HELPER=str(HELPER), CONTEXT=str(context), ROOT=str(root),
                   LOG=str(log), PKG_MGR="dnf", IMAGE_NAME="yellowfin",
                   IMAGE_NAME_VARIANT="yellowfin", TUNAOS_IMAGE_FLAVOR="gnome")
        env.update(environment)
        return subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)

    def receipt():
        files = list(root.glob("usr/share/tunaos/fork-config/packages/*.json"))
        return json.loads(files[0].read_text()) if files else None

    def transactions():
        return log.read_text().splitlines() if log.exists() else []

    run.root = root
    run.context = context
    run.receipt = receipt
    run.transactions = transactions
    return run


def test_absent_manifest_is_noop_without_jq_or_package_manager(tmp_path):
    result = subprocess.run(
        ["/bin/bash", "-c", 'source "$1"; tunaos_apply_fork_packages "$2" "$3"',
         "test", str(HELPER), str(tmp_path), str(tmp_path / "absent-root")],
        env={"PATH": str(tmp_path / "empty-path")}, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("manager,package", [
    ("dnf", "htop"), ("zypper", "htop"), ("pacman", "htop"),
    ("apt", "htop"), ("emerge", "sys-process/htop"),
])
def test_each_manager_uses_legacy_wrappers_and_records_optional_misses(harness, manager, package):
    optional = "app-misc/missing" if manager == "emerge" else "missing"
    good_optional = "app-misc/present" if manager == "emerge" else "present"
    config = manifest(manager, add=[package], optional=[optional, good_optional])
    result = harness(config, PKG_MGR=manager, FAIL_PACKAGE=optional)
    assert result.returncode == 0, result.stderr
    assert harness.transactions() == [
        "refresh", f"install:{package}", f"install:{optional}", f"install:{good_optional}",
    ]
    receipt = harness.receipt()
    assert receipt["required_installed"] == [package]
    assert receipt["optional_missing"] == [optional]
    assert receipt["optional_installed"] == [good_optional]
    assert receipt["sources"] == config["sources"]
    assert receipt["package_manager"] == manager
    assert receipt["status"] == "complete"
    assert "optional package unavailable" in result.stderr


def test_dual_desktop_paths_do_not_repeat_transactions_or_optional_misses(harness):
    config = manifest(add=["htop"], optional=["missing"])
    assert harness(config, FAIL_PACKAGE="missing").returncode == 0
    before = harness.transactions()
    # JSON object key/whitespace formatting is not a new transaction.
    reversed_config = dict(reversed(list(config.items())))
    result = harness(reversed_config, FAIL_PACKAGE="missing")
    assert result.returncode == 0, result.stderr
    assert "already applied" in result.stdout
    assert harness.transactions() == before
    assert harness.receipt()["optional_missing"] == ["missing"]


def test_changed_manifest_refuses_reapplication(harness):
    assert harness(manifest(add=["htop"])).returncode == 0
    before = harness.transactions()
    result = harness(manifest(add=["vim"]))
    assert result.returncode != 0
    assert "existing receipt differs" in result.stderr
    assert harness.transactions() == before
    assert harness.receipt()["required_installed"] == ["htop"]


def test_required_failure_stops_optional_and_writes_no_success_receipt(harness):
    result = harness(manifest(add=["missing"], optional=["present"]), FAIL_PACKAGE="missing")
    assert result.returncode != 0
    assert harness.transactions() == ["refresh", "install:missing"]
    assert harness.receipt() is None
    assert "required package installation failed" in result.stderr


def test_refresh_failure_stops_all_installs(harness):
    result = harness(manifest(add=["htop"]), FAIL_REFRESH="1")
    assert result.returncode != 0
    assert harness.transactions() == ["refresh"]
    assert harness.receipt() is None


def test_empty_intent_records_opt_in_without_any_package_transaction(harness):
    result = harness(manifest())
    assert result.returncode == 0, result.stderr
    assert harness.transactions() == []
    assert harness.receipt()["optional_missing"] == []


@pytest.mark.parametrize("manager", ["dnf", "zypper", "pacman", "apt", "emerge"])
def test_all_removals_fail_before_transaction_or_file_write(harness, manager):
    package = "sys-apps/systemd" if manager == "emerge" else "systemd"
    result = harness(manifest(manager, remove=[package]), PKG_MGR=manager)
    assert result.returncode != 0
    assert "removals are unsupported" in result.stderr
    assert harness.transactions() == []
    assert list(harness.root.iterdir()) == []


REPOSITORY = {"id": "tools", "url": "https://repo.example.test/rpm/",
              "key_url": "https://repo.example.test/public.gpg"}


@pytest.mark.parametrize("manager,directory", [
    ("dnf", "etc/yum.repos.d"), ("zypper", "etc/zypp/repos.d"),
])
def test_signed_rpm_repository_is_namespaced_and_receipted(harness, manager, directory):
    repo_dir = harness.root / directory
    repo_dir.mkdir(parents=True)
    upstream = repo_dir / "upstream.repo"
    upstream.write_text("unchanged legacy repository\n")
    second = dict(REPOSITORY, id="extra", url="https://extra.example.test/rpm")
    result = harness(manifest(manager, add=["htop"], repositories=[REPOSITORY, second]),
                     PKG_MGR=manager)
    assert result.returncode == 0, result.stderr
    content = (repo_dir / "fork-tools.repo").read_text()
    assert "[fork-tools]" in content
    assert "gpgcheck=1\n" in content
    assert "repo_gpgcheck=1\n" in content
    assert f"gpgkey={REPOSITORY['key_url']}\n" in content
    if manager == "zypper":
        assert "pkg_gpgcheck=1\n" in content
    assert upstream.read_text() == "unchanged legacy repository\n"
    assert harness.receipt()["repositories"] == [REPOSITORY, second]
    refresh = "refresh:-y makecache" if manager == "dnf" else "refresh"
    assert harness.transactions() == [refresh, "install:htop"]


@pytest.mark.parametrize("manager", ["apt", "pacman", "emerge"])
def test_unsupported_repository_family_fails_before_mutation(harness, manager):
    result = harness(manifest(manager, repositories=[REPOSITORY]), PKG_MGR=manager)
    assert result.returncode != 0
    assert "repositories are unsupported" in result.stderr
    assert harness.transactions() == []
    assert list(harness.root.iterdir()) == []


def test_repository_collision_preflights_entire_list(harness):
    directory = harness.root / "etc/yum.repos.d"
    directory.mkdir(parents=True)
    conflict = directory / "fork-conflict.repo"
    conflict.write_text("existing unrelated source\n")
    second = dict(REPOSITORY, id="conflict")
    result = harness(manifest(repositories=[REPOSITORY, second]))
    assert result.returncode != 0
    assert "refusing to replace" in result.stderr
    assert not (directory / "fork-tools.repo").exists()
    assert conflict.read_text() == "existing unrelated source\n"
    assert harness.transactions() == []


@pytest.mark.parametrize("package", [
    "--allowerasing", "-y", "@core", "foo*", "foo bar", "foo\nbar", "foo;id",
    "$(id)", "https://example.test/a.rpm", "./a.rpm", "a.rpm", "a.RPM", "a.deb",
    "a.pkg.tar.zst", "foo>=1", "foo:stream", "repo/pkg", "htop\n", "htop\r", "htop\u0000", "",
])
def test_package_expressions_are_rejected_before_mutation(harness, package):
    result = harness(manifest(add=["htop"], optional=[package]))
    assert result.returncode != 0
    assert harness.transactions() == []
    assert list(harness.root.iterdir()) == []


@pytest.mark.parametrize("manager,package", [
    ("apt", "Foo"), ("apt", "foo_bar"), ("apt", "foo:amd64"),
    ("emerge", "htop"), ("emerge", "=sys-process/htop-1.0"),
    ("emerge", "sys-process/htop::gentoo"), ("emerge", "sys-process/htop[static]"),
])
def test_family_specific_name_validation(harness, manager, package):
    result = harness(manifest(manager, add=[package]), PKG_MGR=manager)
    assert result.returncode != 0
    assert harness.transactions() == []


@pytest.mark.parametrize("field,value", [
    ("id", "../bad"), ("id", "bad\n[upstream]"),
    ("url", "http://example.test/repo"),
    ("url", "https://example.test/$releasever"),
    ("url", "https://example.test/repo\ngpgcheck=0"),
    ("url", "https://example.test/repo\n"),
    ("url", "https://user:password@example.test/repo"),
    ("key_url", "file:///tmp/key"),
])
def test_repository_injections_are_rejected(harness, field, value):
    repo = dict(REPOSITORY, **{field: value})
    result = harness(manifest(repositories=[repo]))
    assert result.returncode != 0
    assert harness.transactions() == []
    assert list(harness.root.iterdir()) == []


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(schema_version=2),
    lambda c: c.update(hooks=[]),
    lambda c: c["image"].update(namespace="../escape"),
    lambda c: c["image"].update(registry="localhost:65536"),
    lambda c: c["image"].update(registry="localhost\n"),
    lambda c: c["sources"].update(sha256="broken"),
    lambda c: c["sources"].update(unexpected=True),
    lambda c: c["intent"]["packages"].update(execute="id"),
    lambda c: c["intent"]["packages"].update(add=["htop", "htop"]),
    lambda c: c["intent"]["packages"].update(optional=["htop"]),
    lambda c: c["intent"]["packages"].update(repositories=[REPOSITORY, REPOSITORY]),
])
def test_invalid_generated_contract_fails_closed(harness, mutation):
    config = copy.deepcopy(manifest(add=["htop"]))
    mutation(config)
    result = harness(config)
    assert result.returncode != 0
    assert harness.transactions() == []
    assert list(harness.root.iterdir()) == []


@pytest.mark.parametrize("environment", [
    {"PKG_MGR": "apt"}, {"PKG_MGR": "unknown"},
    {"IMAGE_NAME_VARIANT": "bonito"}, {"IMAGE_NAME_VARIANT": "", "IMAGE_NAME": ""},
    {"TUNAOS_IMAGE_FLAVOR": "kde"}, {"TUNAOS_IMAGE_FLAVOR": ""},
    {"TEST_ARCH": "aarch64"},
])
def test_identity_mismatch_fails_before_mutation(harness, environment):
    result = harness(manifest(add=["htop"]), **environment)
    assert result.returncode != 0
    assert harness.transactions() == []
    assert list(harness.root.iterdir()) == []


@pytest.mark.parametrize("kind", ["directory", "symlink", "dangling-symlink"])
def test_present_nonregular_manifest_is_not_a_silent_stock_fallback(harness, kind):
    path = harness.context / "manifests/fork-config.json"
    if kind == "directory":
        path.mkdir()
    else:
        target = harness.context / "other.json"
        if kind == "symlink":
            target.write_text(json.dumps(manifest()))
        path.symlink_to(target)
    result = harness()
    assert result.returncode != 0
    assert "regular file" in result.stderr
    assert harness.transactions() == []


def actual_package_wrappers():
    """Avoid lib.sh's OS cache and identity side effects, preserve wrapper bodies."""
    source = (ROOT / "build_scripts/lib.sh").read_text()
    return "\n".join(
        re.search(rf"^{name}\(\) \{{\n.*?^\}}", source, re.MULTILINE | re.DOTALL)[0]
        for name in ("pkg_refresh", "pkg_install")
    )


ADAPTER_CASES = [
    ("dnf", "htop", ["dnf:makecache", "dnf:install -y --setopt=install_weak_deps=False htop"]),
    ("zypper", "htop", ["zypper:--non-interactive --gpg-auto-import-keys refresh",
                         "zypper:--non-interactive in --no-recommends htop"]),
    ("pacman", "htop", ["pacman:-Sy --noconfirm", "pacman:-S --noconfirm --needed htop"]),
    ("emerge", "sys-process/htop", ["emerge:--sync --quiet",
                                   "emerge:--verbose --getbinpkg sys-process/htop"]),
    ("apt", "htop", ["apt-get:update", "apt-get:update -qq",
                      "apt-get:--no-remove install -y --no-install-recommends "
                      "-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold htop"]),
]


@pytest.mark.parametrize("manager,package,expected,with_repo", [
    (*case, with_repo)
    for case in ADAPTER_CASES
    for with_repo in ([False, True] if case[0] in ("dnf", "zypper") else [False])
])
@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("operation", ["add", "optional"])
def test_actual_lib_adapter_dispatch_and_required_failure(
        tmp_path, manager, package, expected, fails, with_repo, operation):
    context = tmp_path / "context"
    (context / "manifests").mkdir(parents=True)
    config = manifest(manager, repositories=[REPOSITORY] if with_repo else [], **{operation: [package]})
    (context / "manifests/fork-config.json").write_text(json.dumps(config))
    root = tmp_path / "root"
    root.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands"
    # Only these harmless executables can receive a package-manager invocation.
    for name in ("dnf", "zypper", "pacman", "emerge", "emaint", "apt-get", "dpkg"):
        executable = bin_dir / name
        executable.write_text('''#!/bin/bash
printf '%s:%s\\n' "${0##*/}" "$*" >> "$LOG"
for argument in "$@"; do
    [[ "$argument" != "${FAIL_PACKAGE:-}" ]] || exit 12
done
''')
        executable.chmod(0o755)
    script = actual_package_wrappers() + r'''
set -euo pipefail
source "$HELPER"
uname() { printf 'x86_64\n'; }
dnf_retry() { dnf "$@"; }
zypper_retry() { zypper "$@"; }
mkdir() {
    # The real apt wrapper prepares absolute system directories. Redirect that
    # unrelated preparation in the test; retain the exact transaction commands.
    if [[ "$*" == *"/var/lib/apt/lists/partial"* ]]; then return 0; fi
    command mkdir "$@"
}
status=0
tunaos_apply_fork_packages "$CONTEXT" "$ROOT" || status=$?
if declare -F apt-get >/dev/null; then
    printf 'fork apt override leaked into stock caller\n' >&2
    exit 97
fi
exit "$status"
'''
    env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin", LOG=str(log), HELPER=str(HELPER),
               CONTEXT=str(context), ROOT=str(root), PKG_MGR=manager,
               IMAGE_NAME_VARIANT="yellowfin", TUNAOS_IMAGE_FLAVOR="gnome",
               FAIL_PACKAGE=package if fails else "")
    result = subprocess.run(["/bin/bash", "-c", script], env=env, text=True, capture_output=True)
    commands = log.read_text().splitlines()
    expected = expected.copy()
    if with_repo and manager == "dnf":
        expected[0] = "dnf:-y makecache"
    assert commands[:len(expected)] == expected
    if fails and manager == "apt":
        assert commands[len(expected):] == [
            "dpkg:--configure -a --force-depends",
            "apt-get:--no-remove install -y -f --no-install-recommends htop",
        ]
    else:
        assert commands == expected
    receipts = list(root.glob("usr/share/tunaos/fork-config/packages/*.json"))
    if fails and operation == "add":
        assert result.returncode != 0
        assert "required package installation failed" in result.stderr
        assert receipts == []
    else:
        assert result.returncode == 0, result.stderr
        assert len(receipts) == 1
        receipt = json.loads(receipts[0].read_text())
        if operation == "optional":
            assert receipt["optional_missing"] == ([package] if fails else [])
            assert receipt["optional_installed"] == ([] if fails else [package])


@pytest.mark.parametrize("variant", ["yellowfin", "grouper"])
def test_compiled_sample_runs_both_real_helpers_and_repeats_without_transactions(tmp_path, variant):
    """A real compiler output must be accepted by both consumers unchanged.

    This is a local command/filesystem contract. It does not resolve packages,
    run Containerfiles, contact repositories, or establish image acceptance.
    """
    spec = importlib.util.spec_from_file_location(
        "fork_consumer_compiler_integration", ROOT / "scripts/prepare-fork-config.py")
    compiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compiler)
    config_dir = tmp_path / "fork"
    (config_dir / "art").mkdir(parents=True)
    jpeg = ROOT / "system_files/usr/share/backgrounds/tunaos/tunaos-default.jpg"
    shutil.copyfile(jpeg, config_dir / "art/wallpaper.jpg")
    config = yaml.safe_load((ROOT / "examples/fork/harbor.template.yaml").read_text())
    config["targets"]["variants"] = [variant]
    config["global"]["branding"]["wallpaper"] = "art/wallpaper.jpg"
    # Pin immediately before compilation: other test fixtures need not carry a
    # hand-transcribed receipt that changes whenever the compiler is edited.
    config["catalog"] = {"sha256": compiler.COMPILER.source_receipt(ROOT)["sha256"]}
    config_path = config_dir / "harbor.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    plan, cells, assets = compiler.compile_cells(config_path)
    assert len(cells) == 1
    generated = cells[0]["manifest"]
    assert generated["sources"] == {"sha256": plan["sources"]["sha256"]}
    assert generated["image"] == config["image"]
    assert generated["variant"] == variant
    assert generated["package_manager"] == ("dnf" if variant == "yellowfin" else "apt")

    context, root = tmp_path / "context", tmp_path / "root"
    (context / "manifests").mkdir(parents=True)
    (context / "manifests/fork-config.json").write_text(json.dumps(generated, indent=2))
    for relative, content in assets.items():
        path = context / "manifests" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (context / "build_scripts/lib").mkdir(parents=True)
    for helper in ("fork-packages.sh", "fork-branding.sh"):
        shutil.copyfile(ROOT / "build_scripts/lib" / helper, context / "build_scripts/lib" / helper)

    # These are the pre-existing identity files the normal build writes before
    # either adapter. Their namespace comes from the compiler's generated data.
    for relative in ("usr/lib", "etc/xdg", "usr/share/ublue-os", "usr/share/tunaos"):
        (root / relative).mkdir(parents=True)
    os_release = f'NAME="{variant}"\nHOME_URL="https://stock.example.test/"\n'
    (root / "usr/lib/os-release").write_text(os_release)
    (root / "etc/os-release").write_text(os_release)
    (root / "etc/xdg/kcm-about-distrorc").write_text("[General]\nWebsite=https://stock.example.test/\n")
    image = generated["image"]
    (root / "usr/share/ublue-os/image-info.json").write_text(json.dumps({
        "image-name": variant, "image-flavor": generated["flavor"],
        "image-vendor": image["namespace"],
        "image-ref": f"ostree-image-signed:docker://{image['registry']}/{image['namespace']}/{variant}",
    }))
    (root / "usr/share/tunaos/identity.env").write_text(f"TUNAOS_VARIANT='{variant}'\n")
    log = tmp_path / "transactions"
    script = r'''
set -euo pipefail
source "$CONTEXT/build_scripts/lib/fork-packages.sh"
source "$CONTEXT/build_scripts/lib/fork-branding.sh"
uname() { printf 'x86_64\n'; }
pkg_refresh() { printf 'refresh\n' >> "$LOG"; }
pkg_install() {
    printf 'install:%s\n' "$*" >> "$LOG"
    [[ "$*" != fastfetch ]]
}
pkg_remove() { printf 'UNEXPECTED REMOVE\n' >> "$LOG"; return 97; }
tunaos_validate_fork_branding "$CONTEXT"
tunaos_apply_fork_packages "$CONTEXT" "$ROOT"
tunaos_apply_fork_branding "$CONTEXT" "$ROOT"
tunaos_verify_fork_branding "$ROOT"
'''
    env = {**os.environ, **cells[0]["environment"], "CONTEXT": str(context), "ROOT": str(root),
           "LOG": str(log), "IMAGE_NAME_VARIANT": variant,
           "PKG_MGR": generated["package_manager"]}
    result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    expected = ["refresh", "install:htop"]
    if variant == "yellowfin":
        expected.append("install:fastfetch")
    assert calls == expected
    receipts = list(root.glob("usr/share/tunaos/fork-config/packages/*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["status"] == "complete"
    assert receipt["sources"] == generated["sources"]
    assert receipt["image"] == generated["image"]
    assert receipt["optional_missing"] == (["fastfetch"] if variant == "yellowfin" else [])
    assert json.loads((root / "usr/share/tunaos/fork/fork-config.json").read_text()) == generated
    assert (root / "usr/share/backgrounds/tunaos/tunaos-default.jpg").read_bytes() == jpeg.read_bytes()
    assert f'HOME_URL="{config["global"]["branding"]["homepage"]}"' in (
        root / "usr/lib/os-release").read_text()
    before = {str(path.relative_to(root)): path.read_bytes()
              for path in root.rglob("*") if path.is_file()}
    repeated = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
    assert repeated.returncode == 0, repeated.stderr
    assert "already applied" in repeated.stdout
    assert log.read_text().splitlines() == calls
    assert {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()} == before
