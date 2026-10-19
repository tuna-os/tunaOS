"""Executable host contracts for the opt-in local consumer preview."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_fork", ROOT / "scripts/prepare-fork-config.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def fork(tmp_path):
    config = yaml.safe_load((ROOT / "examples/fork/harbor.template.yaml").read_text())
    import shutil
    shutil.copytree(ROOT / "examples/fork/assets", tmp_path / "assets")
    config["catalog"] = {"sha256": MODULE.COMPILER.source_receipt(ROOT)["sha256"]}
    path = tmp_path / "fork.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def edit(path, change):
    config = yaml.safe_load(path.read_text())
    change(config)
    path.write_text(yaml.safe_dump(config))


def test_sample_fanout_preserves_all_catalog_flags_and_inheritance(fork):
    plan, cells, assets = MODULE.compile_cells(fork)
    assert [c["manifest"]["variant"] for c in cells] == ["yellowfin", "grouper"]
    assert [c["manifest"]["package_manager"] for c in cells] == ["dnf", "apt"]
    assert all(c["manifest"]["intent"]["packages"]["add"] == ["htop"] for c in cells)
    assert cells[0]["manifest"]["intent"]["packages"]["optional"] == ["fastfetch"]
    assert cells[1]["manifest"]["intent"]["packages"]["optional"] == []
    assert len(assets) == 1
    assert all(c["manifest"]["assets"]["wallpaper"]["path"] in assets for c in cells)
    assert plan["legacy_catalog"] == yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
    assert all("@sha256:" in c["environment"]["BASE_IMAGE"] for c in cells)
    assert all(c["environment"]["SKIP_RECHUNK"] == "1" for c in cells)


def test_prepare_copies_receipted_inputs_without_touching_source(fork, tmp_path):
    before = MODULE.COMPILER.source_receipt(ROOT)
    output = tmp_path / "prepared"
    builds = MODULE.prepare(fork, output)
    assert len(builds) == 2
    for build in builds:
        context = output / build["context"]
        payload = json.loads((context / "manifests/fork-config.json").read_text())
        assert payload["sources"] == {"sha256": before["sha256"]}
        assert (context / ".github/build-config.yml").read_bytes() == (ROOT / ".github/build-config.yml").read_bytes()
        assert (context / "scripts/build-image-inner.sh").stat().st_mode & 0o111
        assert (context / "system_files/etc/systemd/system/auditd.service").is_symlink()
    assert not (ROOT / "manifests/fork-config.json").exists()
    assert MODULE.COMPILER.source_receipt(ROOT) == before
    with pytest.raises(MODULE.ConfigError, match="not already exist"):
        MODULE.prepare(fork, output)


@pytest.mark.parametrize("flavor", ["base", "gnome-hwe"])
def test_base_and_overlay_fail_before_any_context_is_written(fork, tmp_path, flavor):
    edit(fork, lambda c: c.update(targets={"variants": ["yellowfin"], "flavors": [flavor], "platforms": ["linux/amd64"]}))
    output = tmp_path / "unsupported"
    with pytest.raises(MODULE.ConfigError, match="direct manifest-backed"):
        MODULE.prepare(fork, output)
    assert not output.exists()


def test_disabled_cells_remain_visible_but_never_run(fork):
    edit(fork, lambda c: c.update(targets={"variants": ["yellowfin"], "flavors": ["gnome", "gnome-asahi"], "platforms": ["linux/amd64", "linux/arm64"]}))
    plan, cells, _ = MODULE.compile_cells(fork)
    assert len(cells) == 1
    assert any(c["selected"] and not c["build_image"] for c in plan["cells"])


@pytest.mark.parametrize("field", ["name", "logo"])
def test_unsupported_brand_fields_fail_explicitly(fork, field):
    if field == "logo":
        (fork.parent / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    edit(fork, lambda c: c["global"]["branding"].update({field: "logo.svg" if field == "logo" else "Harbor"}))
    with pytest.raises(MODULE.ConfigError, match="embedded installer"):
        MODULE.compile_cells(fork)


def test_asset_is_decoded_and_hashed_before_build(fork):
    image = pytest.importorskip("PIL.Image")
    image.new("RGB", (32, 24), "navy").save(fork.parent / "wallpaper.jpg")
    edit(fork, lambda c: c["global"]["branding"].update(wallpaper="wallpaper.jpg"))
    _, cells, assets = MODULE.compile_cells(fork)
    asset = cells[0]["manifest"]["assets"]["wallpaper"]
    assert assets[asset["path"]] == (fork.parent / "wallpaper.jpg").read_bytes()
    (fork.parent / "wallpaper.jpg").write_text("not an image")
    with pytest.raises(MODULE.ConfigError, match="invalid wallpaper"):
        MODULE.compile_cells(fork)


@pytest.mark.parametrize("manager", ["dnf", "zypper", "pacman", "apt", "emerge"])
def test_package_supported_names_and_rejected_removals(manager):
    packages = {"repositories": [], "remove": [], "add": ["sys-process/htop" if manager == "emerge" else "htop"], "optional": []}
    MODULE.validate_packages(packages, manager)
    packages["remove"] = ["kernel"]
    with pytest.raises(MODULE.ConfigError, match="removals"):
        MODULE.validate_packages(packages, manager)


@pytest.mark.parametrize("name", ["--allowerasing", "@group", "foo*", "https://a/b.rpm", "a.rpm", "a b", "$(id)"])
def test_unsafe_package_specs_fail(name):
    with pytest.raises(MODULE.ConfigError, match="plain native"):
        MODULE.validate_packages({"repositories": [], "remove": [], "add": [name], "optional": []}, "dnf")


@pytest.mark.parametrize("manager", ["apt", "pacman", "emerge"])
def test_repository_schemas_not_invented(manager):
    with pytest.raises(MODULE.ConfigError, match="repository semantics"):
        MODULE.validate_packages({"repositories": [{"id": "extra", "url": "https://example.org/repo", "key_url": "https://example.org/key"}], "remove": [], "add": [], "optional": []}, manager)


def test_new_templates_generate_strict_pins_and_cannot_refresh_existing(fork):
    command = ["python3", str(ROOT / "scripts/resolve-fork-config.py"), "--init-template"]
    result = subprocess.run(command + [str(ROOT / "examples/fork/stock.template.yaml")], text=True, capture_output=True, check=True)
    config = yaml.safe_load(result.stdout)
    assert config["catalog"]["sha256"] == MODULE.COMPILER.source_receipt(ROOT)["sha256"]
    result = subprocess.run(command + [str(fork)], text=True, capture_output=True)
    assert result.returncode == 2
    assert "existing config pins must be reviewed manually" in result.stderr
    assert not result.stdout


def test_materializer_never_automatically_builds_or_publishes(fork, tmp_path, monkeypatch):
    calls = []
    original = subprocess.run
    def run(args, **kwargs):
        calls.append(args)
        return original(args, **kwargs)
    monkeypatch.setattr(subprocess, "run", run)
    MODULE.prepare(fork, tmp_path / "prepared")
    assert not any(any(str(arg).endswith("build-image-inner.sh") for arg in args) for args in calls)
    assert not any("push" in args for args in calls)


def test_real_build_engine_receives_fork_cell_and_cache_identity(fork, tmp_path):
    """Execute the real shell build driver; stub the container builder only."""
    import os
    output = tmp_path / "prepared"
    build = MODULE.prepare(fork, output)[0]
    context = output / build["context"]
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "builder.log"
    builder = binaries / "podman"
    builder.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >>"$BUILDER_LOG"\n')
    builder.chmod(0o755)
    env = {**os.environ, **build["environment"], "BUILDER_LOG": str(log),
           "PATH": str(binaries) + os.pathsep + os.environ["PATH"]}
    env.pop("TUNAOS_BUILD_CONFIG", None)
    def execute():
        log.write_text("")
        result = subprocess.run(["bash", "scripts/build-image-inner.sh"], cwd=context,
                                env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        args = log.read_text().splitlines()
        assert args[0] == "build"
        assert ("--no-cache" in args) == (context / "manifests/fork-config.json").exists()
        assert args[args.index("--platform") + 1] == "linux/amd64"
        assert "IMAGE_NAME=yellowfin" in args
        assert "IMAGE_VENDOR=harbor-preview" in args
        assert "TUNAOS_IMAGE_FLAVOR=gnome" in args
        assert "push" not in args
        return next(arg for arg in args if arg.startswith("BUILD_SCRIPTS_HASH="))
    initial = execute()
    payload = context / "manifests/fork-config.json"
    manifest = json.loads(payload.read_text())
    manifest["intent"]["branding"]["homepage"] = "https://another.example.org/"
    payload.write_text(json.dumps(manifest))
    assert execute() != initial
    assets = context / "manifests/fork-assets"
    assets.mkdir(exist_ok=True)
    asset = assets / "probe.jpg"
    asset.write_bytes(b"first asset bytes")
    first_asset = execute()
    asset.write_bytes(b"changed asset bytes")
    assert execute() != first_asset
    # A stock context gets the original script-only key and no fork suffix.
    payload.unlink()
    stock = execute()
    assert len(stock.split("=", 1)[1]) == 16
    assert stock != initial


def test_full_direct_desktop_fanout_is_derived_from_catalog(fork):
    def select(c):
        c["targets"] = {"flavors": ["gnome", "kde", "niri", "cosmic", "xfce", "pantheon", "tuna"],
                        "platforms": ["linux/amd64"]}
        c.pop("global")
        c.pop("overrides")
    edit(fork, select)
    plan, cells, _ = MODULE.compile_cells(fork)
    expected = {(c["variant"], c["flavor"], c["platform"]) for c in plan["cells"]
                if c["selected"] and c["build_image"]}
    actual = {(c["manifest"]["variant"], c["manifest"]["flavor"], c["manifest"]["platform"]) for c in cells}
    assert actual == expected
    assert {c["manifest"]["package_manager"] for c in cells} == {"dnf", "apt", "pacman", "emerge", "zypper"}
    assert any(c["selected"] and not c["build_image"] for c in plan["cells"])


def test_mutable_base_refs_are_preserved_and_disclosed(fork):
    edit(fork, lambda c: c.update(targets={"variants": ["sailfin"], "flavors": ["gnome"], "platforms": ["linux/amd64"]}))
    _, cells, _ = MODULE.compile_cells(fork)
    assert cells[0]["base_digest_pinned"] is False
    assert cells[0]["environment"]["BASE_IMAGE"] == "registry.opensuse.org/opensuse/tumbleweed:latest"

@pytest.mark.parametrize("relative", ["manifests/fork-config.json", "manifests/fork-assets"])
def test_dangling_reserved_payload_symlink_fails_before_compilation(tmp_path, monkeypatch, relative):
    source = tmp_path / "source"
    path = source / relative
    path.parent.mkdir(parents=True)
    outside = tmp_path / "outside-payload"
    path.symlink_to(outside)
    assert path.is_symlink() and not path.exists()
    def must_not_compile(*args, **kwargs):
        pytest.fail("reserved generated symlink reached compilation")
    monkeypatch.setattr(MODULE, "compile_cells", must_not_compile)
    output = tmp_path / "prepared"
    with pytest.raises(MODULE.ConfigError, match="reserved generated fork payload"):
        MODULE.prepare(tmp_path / "unused.yaml", output, root=source)
    assert not output.exists()
    assert not outside.exists()


def test_preview_build_scrubs_input_overrides_secrets_and_shell_hooks(fork, tmp_path, monkeypatch):
    import os
    import sys
    # Compile before poisoning the environment, then exercise the actual CLI
    # handoff with preparation and the external build process stubbed only.
    _, cells, _ = MODULE.compile_cells(fork)
    cell = cells[0]
    build = {"context": "preview-cell", "environment": cell["environment"],
             "base_digest_pinned": True}
    monkeypatch.setattr(MODULE, "prepare", lambda *_: [build])
    forbidden = {
        "TUNAOS_BUILD_CONFIG": "/tmp/unreviewed-catalog.yaml",
        "COMMON_IMAGE": "unreviewed.example/common",
        "BREW_IMAGE": "unreviewed.example/brew",
        "UTAH_PACKAGES_IMAGE": "unreviewed.example/utah",
        "GNOME50_EL10_PACKAGES_IMAGE": "unreviewed.example/gnome",
        "BUILDAH_CACHE_FLAGS": "--layers --build-arg ENABLE_NVIDIA=1",
        "OVERLAY_TYPE": "nvidia",
        "COREOS_STABLE_VERSION": "999",
        "TUNA_REGISTRY_ghcr": "unreviewed.example",
        "TUNA_IMAGE_PATH_common": "unreviewed/common",
        "RHSM_USER": "test-only-user",
        "RHSM_PASSWORD": "test-only-password",
        "RHSM_ORG": "test-only-org",
        "RHSM_ACTIVATION_KEY": "test-only-key",
        "BASH_ENV": "/tmp/unreviewed-shell-hook",
        "ENV": "/tmp/unreviewed-shell-hook",
        "BASH_FUNC_podman%%": "() { false; }",
    }
    for name, value in forbidden.items():
        monkeypatch.setenv(name, value)
    # Host tool selection remains a declared prerequisite, not a build input.
    expected_path = os.environ["PATH"]
    monkeypatch.setenv("YQ", "/tmp/explicit-host-yq")
    monkeypatch.setenv("ENABLE_NVIDIA", "1")
    monkeypatch.setenv("SKIP_RECHUNK", "0")
    monkeypatch.setenv("IS_CI", "1")
    calls = []
    def build_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(subprocess, "run", build_run)
    output = tmp_path / "prepared"
    monkeypatch.setattr(sys, "argv", ["prepare-fork-config.py", str(fork),
                                      "--output", str(output), "--build"])
    MODULE.main()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["bash", "scripts/build-image-inner.sh"]
    assert kwargs["cwd"] == output / "preview-cell"
    handed_off = kwargs["env"]
    assert not set(forbidden) & set(handed_off)
    assert handed_off["PATH"] == expected_path
    assert handed_off["YQ"] == "/tmp/explicit-host-yq"
    for key, value in cell["environment"].items():
        assert handed_off[key] == value


def test_apt_typed_repository_only_routes_to_apt():
    repo = {"type": "apt", "id": "tools", "url": "https://example.org/apt", "key_url": "https://example.org/key.asc",
            "key_sha256": "a" * 64, "suites": ["noble"], "components": ["main"]}
    packages = {"repositories": [repo], "remove": [], "add": [], "optional": []}
    MODULE.validate_packages(packages, "apt")
    for manager in ("dnf", "zypper", "pacman", "emerge"):
        with pytest.raises(MODULE.ConfigError):
            MODULE.validate_packages(packages, manager)


@pytest.mark.parametrize("variant,manager", [("yellowfin", "dnf"), ("grouper", "apt")])
def test_optional_stock_removal_policy_is_explicit(variant, manager):
    packages = {"repositories": [], "remove": ["fastfetch"], "add": [], "optional": []}
    policy = MODULE.validate_packages(packages, manager, variant, "gnome")
    assert isinstance(policy, dict) and policy


@pytest.mark.parametrize("variant,manager,flavor,package", [
    ("yellowfin", "dnf", "gnome", "bash"),
    ("yellowfin", "dnf", "gnome", "glow"),
    ("yellowfin", "dnf", "kde", "fastfetch"),
    ("grouper", "apt", "xfce", "fastfetch"),
    ("bonito", "dnf", "gnome", "fastfetch"),
    ("marlin", "pacman", "gnome", "fastfetch"),
    ("guppy", "emerge", "gnome", "app-misc/fastfetch"),
])
def test_unqualified_stock_removal_has_actionable_preview_error(variant, manager, flavor, package):
    packages = {"repositories": [], "remove": [package], "add": [], "optional": []}
    with pytest.raises(MODULE.ConfigError, match="removals are unsupported"):
        MODULE.validate_packages(packages, manager, variant, flavor)


def test_selected_removal_policy_survives_prepared_build_plan(fork, tmp_path):
    def change(config):
        config["global"]["packages"]["remove"] = ["fastfetch"]
        # The sample adds fastfetch optionally on Yellowfin; overlapping intent
        # must still be removed explicitly rather than silently overwritten.
        config["overrides"]["variants"]["yellowfin"]["packages"]["optional"] = []
    edit(fork, change)
    builds = MODULE.prepare(fork, tmp_path / "with-removal")
    assert all(isinstance(build["package_removal_policy"], dict) for build in builds)
