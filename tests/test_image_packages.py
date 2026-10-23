"""Image-wide package additions come from tunaos.toml (#3668 F4).

[defaults.packages] and each variant's `packages` compile to
build_scripts/lib/image-packages.tsv; 30-image-packages.sh installs a
variant's rows in the base stage of every Containerfile. Removals are rejected.
The shell tests stub lib.sh's package wrappers; real dnf/apt runs are covered
by the PR's container smoke, not here.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("image_packages_config_under_test", ROOT / "scripts/lib/tunaos_config.py")
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
MANAGERS = {"yellowfin": "dnf", "grouper": "apt", "guppy": "emerge", "marlin": "pacman", "sailfin": "zypper"}
REPO = {"id": "acme", "url": "https://repo.acme.example/el10", "key_url": "https://repo.acme.example/key.asc"}


def fork(**variants):
    source = copy.deepcopy(config.load())
    for name, packages in variants.items():
        source["variants"][name]["packages"] = packages
    return source


def managers(source):
    return {name: MANAGERS.get(name, "dnf") for name in source["variants"]}


def test_stock_tunaos_adds_no_packages_and_the_adapter_says_so():
    stock = config.load()
    assert config.image_packages(stock) == {}
    committed = (ROOT / "build_scripts/lib/image-packages.tsv").read_text(encoding="utf-8")
    assert committed == config.render_image_packages(stock)
    assert not [row for row in committed.splitlines() if row and not row.startswith("#")]


def test_defaults_come_first_then_the_variant_without_duplicates():
    source = fork(yellowfin={"add": ["tree", "htop"], "optional": ["btop"]})
    source["defaults"]["packages"] = {"add": ["htop"], "optional": ["ncdu"]}
    deltas = config.image_packages(source, managers(source) | {"guppy": "dnf"})
    assert deltas["yellowfin"] == {"add": ["htop", "tree"], "optional": ["ncdu", "btop"], "repositories": [],
                                   "manager": "dnf"}
    assert deltas["marlin"]["add"] == ["htop"]          # defaults reach every variant


def test_rows_carry_the_variant_its_manager_and_signed_repositories():
    source = fork(yellowfin={"add": ["htop"], "repositories": [REPO]}, grouper={"optional": ["jq"]})
    rows = [row for row in config.render_image_packages(source, managers(source)).splitlines() if not row.startswith("#")]
    assert rows == ["yellowfin\tdnf\tadd\thtop",
                    f"yellowfin\tdnf\trepository\tacme\t{REPO['url']}\t{REPO['key_url']}",
                    "grouper\tapt\toptional\tjq"]


def test_routing_names_each_variants_package_manager():
    source = config.load()
    assert config.variant_managers(source, MANAGERS) == MANAGERS


def test_removals_are_rejected_with_the_reason():
    with pytest.raises(config.ConfigError, match="removals are not supported"):
        config.validate(fork(marlin={"remove": ["nano"]}))


@pytest.mark.parametrize("variant,packages,message", [
    ("guppy", {"add": ["htop"]}, "use category/name"),                    # emerge needs cat/name
    ("grouper", {"add": ["Htop"]}, "not a valid package name for apt"),   # apt names are lowercase
    ("grouper", {"add": ["jq"], "repositories": [REPO]}, "dnf and zypper only"),
    ("yellowfin", {"add": ["htop"], "optional": ["htop"]}, "both required and optional"),
])
def test_a_delta_the_variants_manager_cannot_take_is_rejected(variant, packages, message):
    source = fork(**{variant: packages})
    with pytest.raises(config.ConfigError, match=message):
        config.image_packages(source, managers(source))


@pytest.mark.parametrize("name", ["-y", "https://x.example/a.rpm", "htop.rpm", "foo*", "a b"])
def test_only_plain_native_names_are_accepted(name):
    with pytest.raises(config.ConfigError):
        config.validate(fork(yellowfin={"add": [name]}))


def test_a_repository_defined_twice_differently_is_rejected():
    source = fork(yellowfin={"repositories": [{**REPO, "url": "https://other.example/el10"}]})
    source["defaults"]["packages"] = {"repositories": [REPO]}
    with pytest.raises(config.ConfigError, match="defined twice"):
        config.image_packages(source, managers(source))


# The consumer, with lib.sh's wrappers stubbed to log what they were asked.
# apt-get is a fake executable: the consumer's override calls `command apt-get`.
STUBS = r"""
log() { printf '%s\n' "$*" >>"$LOG"; }
pkg_refresh() { log refresh; }
dnf_retry() { log "dnf_retry $*"; }
pkg_install() {
  for p in "$@"; do [[ "$p" == missing-* ]] && { log "install-failed $*"; return 1; }; done
  if [[ "$PKG_MGR" == apt ]]; then apt-get install -y "$@"; else log "install $*"; fi
}
"""


def consumer(tmp_path, rows, variant, manager, files=None):
    lib, bin_dir = tmp_path / "lib", tmp_path / "bin"
    lib.mkdir(exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "apt-get").write_text('#!/bin/sh\nprintf "apt-get %s\\n" "$*" >>"$LOG"\n')
    (bin_dir / "apt-get").chmod(0o755)
    shutil.copy(ROOT / "build_scripts/lib/image-packages.sh", lib)
    shutil.copy(ROOT / "build_scripts/lib/variant-aliases.tsv", lib)
    (lib / "image-packages.tsv").write_text(config.IMAGE_PACKAGES_HEADER + "".join(r + "\n" for r in rows))
    root = tmp_path / "root"
    for path, text in (files or {}).items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    root.mkdir(exist_ok=True)
    log = tmp_path / "log"
    log.touch()
    script = STUBS + f'source "{lib}/image-packages.sh"\ntunaos_apply_image_packages "{lib}" "{root}"\n'
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "LOG": str(log), "PKG_MGR": manager,
                                 "IMAGE_NAME_VARIANT": variant})
    receipt = root / "usr/share/tunaos/image-packages.tsv"
    return result, log.read_text().splitlines(), receipt.read_text() if receipt.exists() else None


def test_a_variant_without_rows_runs_and_writes_nothing(tmp_path):
    result, calls, receipt = consumer(tmp_path, ["grouper\tapt\tadd\tjq"], "yellowfin", "dnf")
    assert result.returncode == 0 and calls == [] and receipt is None


def test_required_then_optional_with_misses_recorded(tmp_path):
    rows = ["yellowfin\tdnf\tadd\thtop", "yellowfin\tdnf\tadd\ttree",
            "yellowfin\tdnf\toptional\tbtop", "yellowfin\tdnf\toptional\tmissing-thing"]
    result, calls, receipt = consumer(tmp_path, rows, "yellowfin", "dnf")
    assert result.returncode == 0, result.stderr
    assert calls == ["refresh", "install htop tree", "install btop", "install-failed missing-thing"]
    assert receipt.splitlines()[1:] == ["required\thtop", "required\ttree", "optional\tbtop",
                                        "optional-missing\tmissing-thing"]


def test_apt_additions_may_not_remove_packages_and_aliases_fold(tmp_path):
    result, calls, receipt = consumer(tmp_path, ["grouper\tapt\tadd\tjq"], "ubuntu", "apt")
    assert result.returncode == 0, result.stderr
    assert calls == ["refresh", "apt-get --no-remove install -y jq"]
    assert "for grouper (apt)" in receipt


def test_a_manager_mismatch_fails_before_any_package_work(tmp_path):
    result, calls, receipt = consumer(tmp_path, ["yellowfin\tdnf\tadd\thtop"], "yellowfin", "apt")
    assert result.returncode != 0 and "compiled yellowfin for dnf" in result.stderr
    assert calls == [] and receipt is None


def test_signed_repositories_are_written_and_never_replaced(tmp_path):
    rows = ["yellowfin\tdnf\trepository\tacme\thttps://r.example/el10\thttps://r.example/key.asc",
            "yellowfin\tdnf\tadd\tacme-tools"]
    result, calls, _ = consumer(tmp_path, rows, "yellowfin", "dnf")
    assert result.returncode == 0, result.stderr
    repo = (tmp_path / "root/etc/yum.repos.d/image-acme.repo").read_text()
    assert "gpgcheck=1\nrepo_gpgcheck=1\ngpgkey=https://r.example/key.asc" in repo
    assert calls == ["dnf_retry -y makecache", "install acme-tools"]
    clash = tmp_path / "clash"
    clash.mkdir()
    result, calls, _ = consumer(clash, rows, "yellowfin", "dnf",
                                files={"etc/yum.repos.d/image-acme.repo": "[image-acme]\nbaseurl=https://evil.example\n"})
    assert result.returncode != 0 and "refusing to replace" in result.stderr and calls == []
