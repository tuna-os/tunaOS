"""Execute staged identity consumers; no container/GTK/boot acceptance claim."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare", ROOT / "scripts/prepare-fork-config.py")
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)
SPEC = importlib.util.spec_from_file_location("identity", ROOT / "build_scripts/lib/fork-identity.py")
IDENTITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IDENTITY)


@pytest.fixture
def staged(tmp_path):
    image = pytest.importorskip("PIL.Image")
    image.new("RGBA", (32, 32), "navy").save(tmp_path / "logo.png")
    config = yaml.safe_load((ROOT / "examples/fork/identity.template.yaml").read_text())
    config["catalog"] = {"sha256": PREPARE.COMPILER.source_receipt(ROOT)["sha256"]}
    path = tmp_path / "fork.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def materialize(staged, tmp_path):
    plan, cells, blobs = PREPARE.compile_cells(staged, identity_staging=True)
    manifest = tmp_path / "manifests/fork-identity.json"
    manifest.parent.mkdir(exist_ok=True)
    manifest.write_text(json.dumps(cells[0]["identity"]))
    (manifest.parent / "fork-config.json").write_text(json.dumps(cells[0]["manifest"]))
    for path, data in blobs.items():
        dest = manifest.parent / path
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(data)
    root = tmp_path / "root"
    for path, text in {
        "usr/lib/os-release": 'ID=almalinux\nNAME="Yellowfin"\nCPE_NAME="cpe:/o:old:vendor"\n',
        "etc/os-release": 'ID=almalinux\nNAME="Yellowfin"\nCPE_NAME="cpe:/o:old:vendor"\n',
        "usr/share/ublue-os/image-info.json": json.dumps({"image-name": "yellowfin", "image-flavor": "gnome"}),
        "etc/bootc-installer/recipe.json": '{"distro_logo":"resource:///stock.svg"}',
    }.items():
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    return manifest, root, plan, cells


def test_fanout_receipts_and_default_refusal(staged, tmp_path):
    manifest, root, plan, cells = materialize(staged, tmp_path)
    assert {c["manifest"]["variant"] for c in cells} == {"yellowfin", "grouper"}
    assert {c["manifest"]["package_manager"] for c in cells} == {"dnf", "apt"}
    assert all(c["identity"]["sources"]["sha256"] == plan["sources"]["sha256"] for c in cells)
    assert all(c["identity"]["name"] == "Harbor" for c in cells)
    assert all("name" not in c["manifest"]["intent"]["branding"] for c in cells)
    assert any(c["intent"]["branding"].get("name") == "Harbor" for c in plan["cells"] if c["selected"])
    with pytest.raises(PREPARE.ConfigError, match="embedded installer"):
        PREPARE.compile_cells(staged)


def test_real_paths_identity_idempotence_and_tamper(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    IDENTITY.apply(manifest, root)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    IDENTITY.apply(manifest, root)
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    IDENTITY.verify(root)
    osr = (root / "usr/lib/os-release").read_text()
    assert 'NAME="Harbor"' in osr and "CPE_NAME" not in osr and "ID=almalinux" in osr
    assert (root / "etc/os-release").read_text() == osr
    assert json.loads((root / "etc/bootc-installer/recipe.json").read_text())["distro_name"] == "Harbor"
    assert "TunaOS" not in (root / "etc/xdg/fastfetch/config.jsonc").read_text()
    (root / "usr/share/pixmaps/tunaos-lettermark.svg").write_text("tamper")
    with pytest.raises(ValueError, match="hash mismatch"):
        IDENTITY.verify(root)


def test_normal_os_release_symlink_preserved(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    (root / "etc/os-release").unlink()
    (root / "etc/os-release").symlink_to("../usr/lib/os-release")
    IDENTITY.apply(manifest, root)
    assert (root / "etc/os-release").is_symlink()
    IDENTITY.verify(root)


@pytest.mark.parametrize("name", ["", " name", "bad\nname", "$(touch pwn)", "a" * 65, "München"])
def test_name_contract(staged, name):
    config = yaml.safe_load(staged.read_text())
    config["global"]["branding"]["name"] = name
    staged.write_text(yaml.safe_dump(config))
    with pytest.raises(PREPARE.ConfigError):
        PREPARE.compile_cells(staged, identity_staging=True)


def test_asset_tamper_and_cell_mismatch_fail_before_writes(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    original = (root / "usr/lib/os-release").read_bytes()
    m = json.loads(manifest.read_text())
    m["variant"] = "grouper"
    manifest.write_text(json.dumps(m))
    with pytest.raises(ValueError, match="cell"):
        IDENTITY.apply(manifest, root)
    assert (root / "usr/lib/os-release").read_bytes() == original
    (manifest.parent / m["assets"]["logo"]["path"]).write_text("tamper")
    with pytest.raises(ValueError, match="hash"):
        IDENTITY.apply(manifest, root)
    assert (root / "usr/lib/os-release").read_bytes() == original


def test_symlink_target_escape_refused_before_writes(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "usr/share/pixmaps").symlink_to(outside)
    original = (root / "usr/lib/os-release").read_bytes()
    with pytest.raises(ValueError, match="symlinked"):
        IDENTITY.apply(manifest, root)
    assert not list(outside.iterdir())
    assert (root / "usr/lib/os-release").read_bytes() == original


def test_staged_builder_and_cli_refuse_before_work(staged, tmp_path):
    context = tmp_path / "blocked"
    (context / "manifests").mkdir(parents=True)
    (context / "manifests/fork-identity.json").write_text("{}")
    run = subprocess.run(["bash", str(ROOT / "scripts/build-image-inner.sh")], cwd=context, capture_output=True, text=True)
    assert run.returncode == 2 and "staging cannot build" in run.stderr
    output = tmp_path / "not-created"
    run = subprocess.run(["python3", str(ROOT / "scripts/prepare-fork-config.py"), str(staged),
                          "--output", str(output), "--identity-staging", "--build"], capture_output=True, text=True)
    assert run.returncode == 2 and "staging cannot build" in run.stderr
    assert not output.exists()


@pytest.mark.parametrize("variant,manager", [("yellowfin", "dnf"), ("grouper", "apt")])
def test_existing_brand_adapter_reaches_identity_on_both_families(staged, tmp_path, variant, manager):
    import os
    import shutil
    manifest, root, _, cells = materialize(staged, tmp_path)
    cell = next(c for c in cells if c["manifest"]["variant"] == variant)
    manifest.write_text(json.dumps(cell["identity"]))
    (manifest.parent / "fork-config.json").write_text(json.dumps(cell["manifest"]))
    info = {"image-name": variant, "image-flavor": "gnome", "image-vendor": "fork-preview",
            "image-ref": f"ostree-image-signed:docker://localhost/fork-preview/{variant}"}
    (root / "usr/share/ublue-os/image-info.json").write_text(json.dumps(info))
    context = manifest.parent.parent
    (context / "build_scripts/lib").mkdir(parents=True)
    for name in ("fork-branding.sh", "fork-identity.py"):
        shutil.copyfile(ROOT / "build_scripts/lib" / name, context / "build_scripts/lib" / name)
    run = subprocess.run(["bash", "-c", 'set -euo pipefail; source "$1"; tunaos_apply_fork_branding "$2" "$3"',
                          "test", str(context / "build_scripts/lib/fork-branding.sh"), str(context), str(root)],
                         env={**os.environ, "IMAGE_NAME_VARIANT": variant, "TUNAOS_IMAGE_FLAVOR": "gnome", "PKG_MGR": manager},
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    IDENTITY.verify(root)
    for entry in ("install-desktop.sh", "configure-desktop-runtime.sh"):
        assert "tunaos_apply_fork_branding" in (ROOT / "build_scripts/desktop" / entry).read_text()


def test_full_preparation_marks_builds_blocked(staged, tmp_path):
    output = tmp_path / "prepared"
    builds = PREPARE.prepare(staged, output, identity_staging=True)
    assert len(builds) == 2
    for build in builds:
        assert build["build_blocked"] == IDENTITY.BLOCKERS
        manifest = output / build["context"] / "manifests/fork-identity.json"
        assert IDENTITY.load(manifest)["name"] == "Harbor"
    assert not (ROOT / "manifests/fork-identity.json").exists()


def test_non_png_and_unsupported_desktop_fail(staged):
    (staged.parent / "logo.png").write_text("not a PNG")
    with pytest.raises(PREPARE.ConfigError):
        PREPARE.compile_cells(staged, identity_staging=True)
    config = yaml.safe_load(staged.read_text())
    config["targets"]["flavors"] = ["kde"]
    staged.write_text(yaml.safe_dump(config))
    with pytest.raises(PREPARE.ConfigError, match="only direct"):
        PREPARE.compile_cells(staged, identity_staging=True)


def test_live_root_refused(staged, tmp_path):
    manifest, _, _, _ = materialize(staged, tmp_path)
    alias = tmp_path / "live-root"
    alias.symlink_to("/")
    for root in (Path("/"), alias):
        with pytest.raises(ValueError, match="non-live"):
            IDENTITY.apply(manifest, root)


def test_check_performs_no_writes_and_link_change_fails(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    (root / "etc/os-release").unlink()
    (root / "etc/os-release").symlink_to("../usr/lib/os-release")
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    IDENTITY.apply(manifest, root, check=True)
    assert before == sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    assert 'NAME="Yellowfin"' in (root / "usr/lib/os-release").read_text()
    IDENTITY.apply(manifest, root)
    (root / "etc/os-release").unlink()
    (root / "etc/os-release").write_text('NAME="Wrong"\n')
    with pytest.raises(ValueError, match="link state"):
        IDENTITY.verify(root)


def test_nonregular_target_and_source_mismatch_fail_before_writes(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    original = (root / "usr/lib/os-release").read_bytes()
    (root / "usr/share/pixmaps/tunaos.svg").mkdir(parents=True)
    with pytest.raises(ValueError, match="non-regular"):
        IDENTITY.apply(manifest, root)
    assert (root / "usr/lib/os-release").read_bytes() == original
    payload = json.loads(manifest.read_text())
    payload["sources"]["sha256"] = "b" * 64
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="paired"):
        IDENTITY.apply(manifest, root)
    assert (root / "usr/lib/os-release").read_bytes() == original


def test_hardlinks_and_outer_targets_fail_before_writes(staged, tmp_path):
    import os
    manifest, root, _, _ = materialize(staged, tmp_path)
    osr = root / "usr/lib/os-release"
    outside = tmp_path / "outside-os-release"
    os.link(osr, outside)
    original = outside.read_bytes()
    with pytest.raises(ValueError, match="hardlinked"):
        IDENTITY.apply(manifest, root, check=True)
    assert outside.read_bytes() == original
    outside.unlink()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (root / "usr/share/tunaos").mkdir()
    (root / "usr/share/tunaos/fork").symlink_to(outside_dir)
    with pytest.raises(ValueError, match="symlinked"):
        IDENTITY.apply(manifest, root, check=True)
    assert not list(outside_dir.iterdir())


def test_existing_source_receipt_mismatch_refused(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    path = root / "usr/share/ublue-os/image-info.json"
    info = json.loads(path.read_text())
    info["fork-config"] = {"sources": {"sha256": "f" * 64}, "variant": "yellowfin", "flavor": "gnome", "platform": "linux/arm64"}
    path.write_text(json.dumps(info))
    with pytest.raises(ValueError, match="source/platform"):
        IDENTITY.apply(manifest, root, check=True)


def test_non_directory_ancestor_fails_before_writes(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    original = (root / "usr/lib/os-release").read_bytes()
    (root / "usr/share/pixmaps").write_text("not a directory")
    with pytest.raises(ValueError, match="non-directory"):
        IDENTITY.apply(manifest, root)
    assert (root / "usr/lib/os-release").read_bytes() == original


def test_boot_assets_and_selection_before_desktop_identity(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    original = (root / "usr/lib/os-release").read_bytes()
    IDENTITY.apply_boot(manifest, root)
    assert (root / "usr/lib/os-release").read_bytes() == original
    conf = (root / "etc/plymouth/plymouthd.conf").read_text()
    assert "Theme=fork-identity" in conf
    assert "ThemeDir=/usr/share/plymouth/themes" in conf
    theme = root / IDENTITY.THEME_DIR
    from PIL import Image
    with Image.open(theme / "splash.png") as image:
        assert image.format == "PNG" and image.width > 128
    script = (theme / "splash.script").read_text()
    assert 'Image("splash.png")' in script
    assert "FRAME_COUNT = 1;" in script
    for callback in ("SetDisplayPasswordFunction", "SetDisplayQuestionFunction", "SetDisplayNormalFunction"):
        assert callback in script
    IDENTITY.apply(manifest, root)
    IDENTITY.verify(root)


def test_installer_single_brand_projection_and_preserved_options(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    recipe_path = root / "etc/bootc-installer/recipe.json"
    recipe = {"imgref": "example.org/fork/os:gnome", "local_imgref": "containers-storage:example.org/fork/os:gnome",
              "filesystem": "xfs", "steps": {"encryption": {"template": "encryption"}}}
    recipe_path.write_text(json.dumps(recipe))
    branding_path = root / "etc/bootc-installer/branding.json"
    branding_path.write_text(json.dumps({"id": "existing-id", "vendor": "existing-vendor", "default_hostname": "existing-host"}))
    catalog_path = root / "etc/bootc-installer/images.json"
    other = {"name": "Other", "imgref": "example.org/other:latest", "icon": "resource:///other.svg"}
    catalog_path.write_text(json.dumps({"images": [{"name": "Group", "registry": "example.org/fork/os", "children": [
        {"name": "Stock", "imgref": None, "tag": "gnome", "filesystem": "xfs"}, other]}]}))
    IDENTITY.apply(manifest, root)
    brand = json.loads(branding_path.read_text())
    assert brand == {"name": "Harbor", "logo": "/usr/share/pixmaps/tunaos.svg", "home_url": "https://example.org/harbor",
                     "id": "existing-id", "vendor": "existing-vendor", "default_hostname": "existing-host"}
    actual_recipe = json.loads(recipe_path.read_text())
    assert all(actual_recipe[k] == v for k, v in recipe.items())
    nodes = json.loads(catalog_path.read_text())["images"][0]["children"]
    assert nodes[0] == {"name": "Harbor", "imgref": None, "tag": "gnome", "filesystem": "xfs", "icon": brand["logo"]}
    assert nodes[1] == other
    IDENTITY.verify(root)


@pytest.mark.parametrize("relative", ["etc/bootc-installer/branding.json", "etc/plymouth/plymouthd.conf",
                                      "usr/share/plymouth/themes/fork-identity/splash.png"])
def test_new_consumer_symlinks_refused_before_mutation(staged, tmp_path, relative):
    manifest, root, _, _ = materialize(staged, tmp_path)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.write_text("protected")
    path.symlink_to(outside)
    original = (root / "usr/lib/os-release").read_bytes()
    with pytest.raises(ValueError, match="symlink"):
        IDENTITY.apply(manifest, root)
    assert outside.read_text() == "protected"
    assert (root / "usr/lib/os-release").read_bytes() == original


def test_early_selector_reaches_staged_payload(staged, tmp_path):
    import os
    import shutil
    manifest, root, _, _ = materialize(staged, tmp_path)
    context = manifest.parent.parent
    (context / "build_scripts/lib").mkdir(parents=True)
    shutil.copyfile(ROOT / "build_scripts/lib/fork-identity.py", context / "build_scripts/lib/fork-identity.py")
    shutil.copyfile(ROOT / "build_scripts/plymouth-set-theme.sh", context / "build_scripts/plymouth-set-theme.sh")
    run = subprocess.run(["bash", str(context / "build_scripts/plymouth-set-theme.sh"), "yellowfin"],
                         env={**os.environ, "TUNAOS_SYSROOT": str(root)}, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert (root / "etc/plymouth/plymouthd.conf").read_text().strip() == "[Daemon]\nTheme=fork-identity\nThemeDir=/usr/share/plymouth/themes"
    # Same entry point remains closed to live image writes until qualification.
    run = subprocess.run(["bash", str(context / "build_scripts/plymouth-set-theme.sh"), "yellowfin"],
                         env={k: v for k, v in os.environ.items() if k != "TUNAOS_SYSROOT"}, capture_output=True, text=True)
    assert run.returncode != 0 and "non-live" in run.stderr


def test_recipe_tour_projects_stock_copy_and_art_only(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    path = root / "etc/bootc-installer/recipe.json"
    recipe = json.loads((ROOT / "system_files/etc/bootc-installer/recipe.json").read_text())
    recipe["tour"]["custom"] = {"title": "Independent slide", "image": "/usr/share/custom.png"}
    path.write_text(json.dumps(recipe))
    IDENTITY.apply(manifest, root)
    actual = json.loads(path.read_text())
    assert "Harbor" in actual["tour"]["welcome"]["title"]
    assert "TunaOS" not in actual["tour"]["completed"]["description"]
    assert actual["tour"]["welcome"]["image"] == "/run/host/usr/share/pixmaps/tunaos.svg"
    assert actual["tour"]["custom"] == recipe["tour"]["custom"]
    assert actual["imgref"] == recipe["imgref"]
    IDENTITY.verify(root)


def test_identity_pair_must_match_canonical_intent(staged, tmp_path):
    manifest, root, _, _ = materialize(staged, tmp_path)
    canonical = root / "usr/share/tunaos/fork/fork-config.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes((manifest.parent / "fork-config.json").read_bytes())
    IDENTITY.apply(manifest, root)
    paired = root / "usr/share/tunaos/fork-identity/fork-config.json"
    value = json.loads(paired.read_text())
    value["intent"]["branding"]["homepage"] = "https://other.example/"
    paired.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="canonical"):
        IDENTITY.verify(root)


@pytest.mark.parametrize("source,content", [
    (None, None),
    ("etc/dconf/profile/gdm", "user-db:user\nfile-db:/var/lib/gdm3/greeter-dconf-defaults\n"),
    ("usr/share/dconf/profile/gdm", "user-db:user\nfile-db:/usr/share/gdm/greeter-dconf-defaults\n"),
    ("etc/dconf/profile/gdm", "# Keep defaults\nuser-db:user\nsystem-db:site\nsystem-db:gdm\n"),
])
def test_gdm_profile_precedes_vendor_defaults(staged, tmp_path, source, content):
    manifest, root, _, _ = materialize(staged, tmp_path)
    if source:
        path = root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    IDENTITY.apply(manifest, root)
    profile = root / "etc/dconf/profile/gdm"
    active = [line for line in profile.read_text().splitlines() if not line.startswith("#")]
    assert active[:2] == ["user-db:user", "system-db:gdm"]
    if content:
        assert all(line in profile.read_text().splitlines() for line in content.splitlines())
    IDENTITY.apply(manifest, root)
    IDENTITY.verify(root)
    profile.write_text("user-db:user\nfile-db:/usr/share/gdm/greeter-dconf-defaults\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        IDENTITY.verify(root)
    # Even an updated hash cannot make a disconnected greeter profile valid.
    import hashlib
    receipt = root / "usr/share/tunaos/fork-identity/applied.json"
    applied = json.loads(receipt.read_text())
    applied["etc/dconf/profile/gdm"] = hashlib.sha256(profile.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(applied))
    with pytest.raises(ValueError, match="greeter, boot or installer"):
        IDENTITY.verify(root)


@pytest.mark.parametrize("bad", ["symlink", "wrong-profile"])
def test_gdm_profile_rejected_before_identity_mutation(staged, tmp_path, bad):
    manifest, root, _, _ = materialize(staged, tmp_path)
    profile = root / "etc/dconf/profile/gdm"
    profile.parent.mkdir(parents=True)
    if bad == "symlink":
        profile.symlink_to(tmp_path / "outside")
    else:
        profile.write_text("file-db:/vendor\nuser-db:user\n")
    before = (root / "usr/lib/os-release").read_bytes()
    with pytest.raises(ValueError):
        IDENTITY.apply(manifest, root)
    assert (root / "usr/lib/os-release").read_bytes() == before


@pytest.mark.parametrize("omit_theme_dir", [False, True])
def test_ubuntu_populate_initrd_selects_the_generated_theme(staged, tmp_path, omit_theme_dir):
    import configparser
    import os
    manifest, root, _, _ = materialize(staged, tmp_path)
    IDENTITY.apply_boot(manifest, root)
    path = root / "etc/plymouth/plymouthd.conf"
    conf = configparser.ConfigParser(interpolation=None)
    conf.optionxform = str
    conf.read(path)
    assert conf["Daemon"]["ThemeDir"] == "/usr/share/plymouth/themes"
    # Remap only the fixture's root. The actual vendor selection functions
    # below must choose fork-identity even while alternatives names bgrt.
    if omit_theme_dir:
        conf.remove_option("Daemon", "ThemeDir")
    else:
        conf["Daemon"]["ThemeDir"] = str(root / "usr/share/plymouth/themes")
    with path.open("w") as stream:
        conf.write(stream, space_around_delimiters=False)
    policy = root / "usr/share/plymouth"
    (policy / "plymouthd.defaults").write_text("[Daemon]\nTheme=bgrt\n")
    fixture = ROOT / "tests/fixtures/plymouth/ubuntu-theme-selection.sh"
    run = subprocess.run(
        ["bash", "-c", 'source "$1"; set_theme_dir; printf "%s\n" "$PLYMOUTH_THEME_NAME" "$PLYMOUTH_THEME_DIR"', "test", str(fixture)],
        env={**os.environ, "PLYMOUTH_CONFDIR": str(path.parent),
             "PLYMOUTH_POLICYDIR": str(policy), "PLYMOUTH_DATADIR": str(root / "usr/share"),
             "PLYMOUTH_THEME_NAME": "bgrt"}, capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr
    expected = "bgrt" if omit_theme_dir else "fork-identity"
    assert run.stdout.splitlines() == [expected, str(root / "usr/share/plymouth/themes" / expected)]
