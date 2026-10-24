"""Execute the opt-in brand adapter against an isolated filesystem.

This proves source-level consumers and tamper detection, not booted artwork,
installer branding or package-family acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "build_scripts/lib/fork-branding.sh"
PLATFORM = "linux/arm64" if os.uname().machine == "aarch64" else "linux/amd64"


def run_helper(context, root, function="tunaos_apply_fork_branding", env=None):
    command = 'set -euo pipefail; source "$1"; "$2" "$3" "$4"'
    args = [str(context), str(root)]
    if function == "tunaos_verify_fork_branding":
        args = [str(root), ""]
    return subprocess.run(
        ["bash", "-c", command, "test", str(HELPER), function, *args],
        text=True, capture_output=True,
        env={**os.environ, "IMAGE_NAME_VARIANT": "yellowfin", "TUNAOS_IMAGE_FLAVOR": "gnome",
             "PKG_MGR": "dnf", **(env or {})},
    )


def snapshot(root):
    return {str(p.relative_to(root)): ("link", os.readlink(p)) if p.is_symlink() else ("file", p.read_bytes())
            for p in root.rglob("*") if p.is_file() or p.is_symlink()}


@pytest.fixture
def fixture(tmp_path):
    context, root = tmp_path / "context", tmp_path / "root"
    for relative in ("usr/lib", "etc/xdg", "usr/share/ublue-os", "usr/share/tunaos"):
        (root / relative).mkdir(parents=True)
    osr = ('NAME="Yellowfin"\nPRETTY_NAME="Yellowfin"\nVERSION_CODENAME="Thunnus albacares"\n'
           'CPE_NAME="cpe:/o:jamesreilly:yellowfin-tunaos"\nLOGO="tunaos"\n'
           'HOME_URL="https://github.com/tuna-os/tunaos"\n'
           'DOCUMENTATION_URL="https://github.com/tuna-os/tunaos/tree/main/docs"\n'
           'SUPPORT_URL="https://github.com/tuna-os/tunaos/issues/"\n'
           'BUG_REPORT_URL="https://github.com/tuna-os/tunaos/issues/"\n')
    (root / "usr/lib/os-release").write_text(osr)
    (root / "etc/os-release").write_text(osr)
    (root / "etc/xdg/kcm-about-distrorc").write_text("[General]\nWebsite=https://github.com/tuna-os/tunaos\nVariant=part of TunaOS\n")
    (root / "usr/share/ublue-os/image-info.json").write_text(json.dumps({
        "image-name": "yellowfin", "image-vendor": "fork-preview", "image-flavor": "gnome",
        "image-ref": "ostree-image-signed:docker://localhost/fork-preview/yellowfin",
    }))
    (root / "usr/share/tunaos/identity.env").write_text("TUNAOS_VARIANT='yellowfin'\n")
    (context / "manifests/fork-assets").mkdir(parents=True)
    (context / "build_scripts/lib").mkdir(parents=True)
    shutil.copyfile(HELPER, context / "build_scripts/lib/fork-branding.sh")
    # Consumers hash already-decoded host input; the compiler tests own image
    # decoding. Use a tracked real JPEG here so this test also uses image bytes.
    asset = (ROOT / "system_files/usr/share/backgrounds/tunaos/tunaos-default.jpg").read_bytes()
    digest = hashlib.sha256(asset).hexdigest()
    asset_path = f"fork-assets/{digest}.jpg"
    (context / "manifests" / asset_path).write_bytes(asset)
    manifest = {
        "schema_version": 1, "variant": "yellowfin", "flavor": "gnome", "platform": PLATFORM,
        "image": {"registry": "localhost", "namespace": "fork-preview"},
        "package_manager": "dnf", "sources": {"sha256": "a" * 64},
        "intent": {"branding": {"homepage": "https://example.test/?a=1&b=2", "documentation": "https://example.test/docs",
                                "support": "https://example.test/help", "wallpaper": "art/final.jpeg"},
                   "packages": {"add": [], "remove": [], "optional": [], "repositories": []}},
        "assets": {"wallpaper": {"path": asset_path, "sha256": digest}},
    }
    path = context / "manifests/fork-config.json"
    path.write_text(json.dumps(manifest))
    return context, root, path, manifest


def test_absent_input_is_byte_for_byte_noop(fixture):
    context, root, path, _ = fixture
    path.unlink()
    before = snapshot(root)
    result = run_helper(context, root)
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""
    assert snapshot(root) == before


def test_urls_art_receipt_and_runtime_verification(fixture):
    context, root, _, manifest = fixture
    result = run_helper(context, root)
    assert result.returncode == 0, result.stderr
    for path in (root / "usr/lib/os-release", root / "etc/os-release"):
        text = path.read_text()
        for field, key in (("HOME_URL", "homepage"), ("DOCUMENTATION_URL", "documentation"),
                           ("SUPPORT_URL", "support"), ("BUG_REPORT_URL", "support")):
            assert f'{field}="{manifest["intent"]["branding"][key]}"' in text
            assert text.count(f"\n{field}=") == 1
        assert 'NAME="Yellowfin"' in text
        assert 'VERSION_CODENAME="Thunnus albacares"' in text
        assert 'CPE_NAME="cpe:/o:jamesreilly:yellowfin-tunaos"' in text
        assert 'LOGO="tunaos"' in text
    assert "Website=https://example.test/?a=1&b=2" in (root / "etc/xdg/kcm-about-distrorc").read_text()
    info = json.loads((root / "usr/share/ublue-os/image-info.json").read_text())
    assert info["image-name"] == "yellowfin"
    assert info["fork-config"]["sources"] == manifest["sources"]
    assert (root / "usr/share/backgrounds/tunaos/tunaos-default.jpg").read_bytes() == (
        context / "manifests" / manifest["assets"]["wallpaper"]["path"]).read_bytes()
    checked = run_helper(context, root, "tunaos_verify_fork_branding", {"IMAGE_NAME_VARIANT": "ignored-at-runtime"})
    assert checked.returncode == 0, checked.stderr


def test_repeated_application_is_byte_idempotent(fixture):
    context, root, _, _ = fixture
    assert run_helper(context, root).returncode == 0
    before = snapshot(root)
    assert run_helper(context, root).returncode == 0
    assert snapshot(root) == before


def test_os_release_symlink_is_preserved(fixture):
    context, root, _, _ = fixture
    path = root / "etc/os-release"
    path.unlink()
    path.symlink_to("../usr/lib/os-release")
    result = run_helper(context, root)
    assert result.returncode == 0, result.stderr
    assert path.is_symlink()
    assert run_helper(context, root, "tunaos_verify_fork_branding").returncode == 0


def test_url_is_literal_shell_data(fixture):
    context, root, path, manifest = fixture
    marker = root / "must-not-execute"
    url = f'https://example.test/?q="$(touch${{IFS}}{marker})"&literal=$HOME`false`\\x'
    manifest["intent"]["branding"]["homepage"] = url
    path.write_text(json.dumps(manifest))
    result = run_helper(context, root)
    assert result.returncode == 0, result.stderr
    parsed = subprocess.check_output(["bash", "-c", 'source "$1"; printf %s "$HOME_URL"', "test", str(root / "etc/os-release")], text=True)
    assert parsed == url
    assert not marker.exists()
    assert run_helper(context, root, "tunaos_verify_fork_branding").returncode == 0


@pytest.mark.parametrize("change", [
    lambda x: x.update(extra=True),
    lambda x: x["image"].update(extra=True),
    lambda x: x["image"].update(namespace="../../escape"),
    lambda x: x.update(schema_version=True),
    lambda x: x.update(variant="marlin"),
    lambda x: x.update(flavor="kde"),
    lambda x: x.update(platform="linux/amd64" if PLATFORM == "linux/arm64" else "linux/arm64"),
    lambda x: x.update(package_manager="apt"),
    lambda x: x["sources"].update(branch="main"),
    lambda x: x["intent"].update(scripts=[]),
    lambda x: x["intent"]["branding"].update(name="Fork"),
    lambda x: x["intent"]["branding"].update(logo="logo.svg"),
    lambda x: x["intent"]["branding"].update(homepage="http://example.test"),
    lambda x: x["intent"]["branding"].update(homepage="https://example.test/\nBAD=yes"),
    lambda x: x["intent"]["packages"].update(unknown=[]),
    lambda x: x["assets"]["wallpaper"].update(path="../outside.jpg"),
    lambda x: x["assets"]["wallpaper"].update(path="fork-assets/" + "0" * 64 + ".jpg"),
    lambda x: x["assets"]["wallpaper"].update(path=x["assets"]["wallpaper"]["path"].replace(".jpg", ".png")),
    lambda x: x["assets"].update(logo={}),
])
def test_invalid_manifest_fails_before_writes(fixture, change):
    context, root, path, manifest = fixture
    change(manifest)
    path.write_text(json.dumps(manifest))
    before = snapshot(root)
    result = run_helper(context, root)
    assert result.returncode != 0
    assert "fork branding" in result.stderr
    assert snapshot(root) == before


@pytest.mark.parametrize("damage", ["corrupt", "missing", "symlink", "manifest-symlink", "multi-json"])
def test_input_tampering_fails_before_writes(fixture, tmp_path, damage):
    context, root, path, manifest = fixture
    asset = context / "manifests" / manifest["assets"]["wallpaper"]["path"]
    if damage == "corrupt":
        asset.write_bytes(b"wrong bytes")
    elif damage == "missing":
        asset.unlink()
    elif damage == "symlink":
        target = tmp_path / "outside.jpg"
        shutil.copyfile(asset, target)
        asset.unlink()
        asset.symlink_to(target)
    elif damage == "manifest-symlink":
        target = tmp_path / "outside.json"
        shutil.copyfile(path, target)
        path.unlink()
        path.symlink_to(target)
    else:
        path.write_text(path.read_text() + "\n" + path.read_text())
    before = snapshot(root)
    assert run_helper(context, root).returncode != 0
    assert snapshot(root) == before


@pytest.mark.parametrize("target", ["wallpaper", "usr-url", "etc-url", "receipt", "variant", "flavor", "vendor", "image-ref", "kde-about"])
def test_runtime_detects_changed_applied_state(fixture, target):
    context, root, _, _ = fixture
    result = run_helper(context, root)
    assert result.returncode == 0, result.stderr
    if target == "wallpaper":
        (root / "usr/share/backgrounds/tunaos/tunaos-default.jpg").write_bytes(b"stock overwrote custom")
    elif target in ("usr-url", "etc-url"):
        path = root / ("usr/lib/os-release" if target == "usr-url" else "etc/os-release")
        path.write_text(path.read_text() + 'HOME_URL="https://other.test/"\n')
    elif target in ("receipt", "flavor", "vendor", "image-ref"):
        path = root / "usr/share/ublue-os/image-info.json"
        data = json.loads(path.read_text())
        if target == "receipt":
            data["fork-config"]["sources"]["sha256"] = "b" * 64
        elif target == "flavor":
            data["image-flavor"] = "kde"
        elif target == "vendor":
            data["image-vendor"] = "other-owner"
        else:
            data["image-ref"] = "ostree-image-signed:docker://localhost/other-owner/yellowfin"
        path.write_text(json.dumps(data))
    elif target == "variant":
        (root / "usr/share/tunaos/identity.env").write_text("TUNAOS_VARIANT='marlin'\n")
    else:
        (root / "etc/xdg/kcm-about-distrorc").write_text("[General]\nWebsite=https://stock.test\n")
    assert run_helper(context, root, "tunaos_verify_fork_branding").returncode != 0


def test_partial_url_override_preserves_unspecified_values(fixture):
    context, root, path, manifest = fixture
    manifest["intent"]["branding"] = {"homepage": "https://example.test/"}
    manifest["assets"] = {}
    path.write_text(json.dumps(manifest))
    result = run_helper(context, root)
    assert result.returncode == 0, result.stderr
    assert 'SUPPORT_URL="https://github.com/tuna-os/tunaos/issues/"' in (root / "usr/lib/os-release").read_text()
    assert not (root / "usr/share/backgrounds/tunaos/tunaos-default.jpg").exists()
    assert run_helper(context, root, "tunaos_verify_fork_branding").returncode == 0


@pytest.mark.parametrize("entry", ["install-desktop.sh", "configure-desktop-runtime.sh"])
def test_both_paths_reapply_after_stock_selection_and_before_final_check(entry):
    source = (ROOT / "build_scripts/desktop" / entry).read_text()
    validate = source.index("tunaos_validate_fork_branding")
    packages = source.index("tunaos_apply_fork_packages")
    select = source.index('/build_scripts/desktop/select-wallpaper.sh"' if entry == "install-desktop.sh"
                          else "/build_scripts/desktop/select-wallpaper.sh ")
    assert validate < packages < select
    assert source.index("tunaos_apply_fork_branding", select) < source.index('BRANDING_EXTRA=""', select)
    kde = source.index("/build_scripts/desktop/kde-set-look-and-feel.sh")
    final_apply = source.index("tunaos_apply_fork_branding", kde)
    assert kde < final_apply < source.index("tunaos_verify_fork_branding", final_apply)
    assert source.index("tunaos_verify_fork_branding", final_apply) < source.index("cat >/usr/lib/systemd/system/tunaos-desktop-contract.service")


def test_stock_verification_is_retained_and_fork_urls_need_validation():
    source = (ROOT / "build_scripts/checks/verify-branding.sh").read_text()
    assert 'if tunaos_verify_fork_branding; then' in source
    assert 'if [[ "$fork_branding_valid" == true ]]; then' in source
    for check in ('[[ "$jvendor" == "$want_vendor" ]]',
                  "TunaOS plymouth theme active", 'names_upstream "$got_pretty"'):
        assert check in source
    info = (ROOT / "build_scripts/90-image-info.sh").read_text()
    assert info.index("tunaos_apply_fork_branding") > info.index("# fastfetch,")


@pytest.mark.parametrize("duplicate", [
    '"schema_version":1,"schema_version":1',
    '"sources":{"sha256":"' + "a" * 64 + '"},"sources":{"sha256":"' + "a" * 64 + '"}',
])
def test_duplicate_json_keys_fail_closed(fixture, duplicate):
    context, root, path, manifest = fixture
    key = "schema_version" if duplicate.startswith('"schema_version"') else "sources"
    del manifest[key]
    path.write_text("{" + duplicate + "," + json.dumps(manifest)[1:])
    before = snapshot(root)
    result = run_helper(context, root)
    assert result.returncode != 0
    assert "duplicate" in result.stderr
    assert snapshot(root) == before


def test_kde_website_changes_only_general_section(fixture):
    context, root, _, _ = fixture
    path = root / "etc/xdg/kcm-about-distrorc"
    path.write_text("[General]\nWebsite=https://stock.test\nVariant=part of TunaOS\n[Other]\nWebsite=https://other.test\n")
    result = run_helper(context, root)
    assert result.returncode == 0, result.stderr
    assert path.read_text() == ("[General]\nWebsite=https://example.test/?a=1&b=2\nVariant=part of TunaOS\n"
                                "[Other]\nWebsite=https://other.test\n")
    assert run_helper(context, root, "tunaos_verify_fork_branding").returncode == 0


def test_gnome_consumes_custom_wallpaper_after_variant_selection(fixture):
    context, root, _, manifest = fixture
    assert run_helper(context, root).returncode == 0
    (root / "usr/share/backgrounds/tunaos/yellowfin-gnome.jpg").write_bytes(b"stock desktop art")
    subprocess.run(["bash", str(ROOT / "build_scripts/desktop/select-wallpaper.sh"), "gnome", str(root)], check=True)
    # Selection runs first in both call sites; the fork adapter must win back
    # the active path before GNOME writes the settings which consume it.
    assert run_helper(context, root, "tunaos_verify_fork_branding").returncode != 0
    assert run_helper(context, root).returncode == 0
    subprocess.run(["bash", str(ROOT / "build_scripts/desktop/gnome-set-branding.sh"), str(root)], check=True)
    for db in ("local", "gdm"):
        (root / f"etc/dconf/db/{db}").write_text("test compiled-database placeholder")
    (root / "usr/share/pixmaps").mkdir(parents=True)
    (root / "usr/share/pixmaps/tunaos.svg").write_text("<svg/>")
    checked = subprocess.run(["bash", str(ROOT / "build_scripts/checks/verify-branding-gnome.sh"), "yellowfin"],
                             env={**os.environ, "TUNAOS_BRANDING_ROOT": str(root),
                                  "TUNAOS_DCONF_DB": str(root / "etc/dconf/db")},
                             capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert run_helper(context, root, "tunaos_verify_fork_branding").returncode == 0
    assert hashlib.sha256((root / "usr/share/backgrounds/tunaos/tunaos-default.jpg").read_bytes()).hexdigest() == manifest["assets"]["wallpaper"]["sha256"]


def test_kde_homepage_is_restored_after_stock_writer(fixture):
    context, root, _, _ = fixture
    assert run_helper(context, root).returncode == 0
    about = root / "etc/xdg/kcm-about-distrorc"
    subprocess.run(["bash", str(ROOT / "build_scripts/desktop/kde-set-look-and-feel.sh"), str(root / "etc/xdg/kdeglobals")],
                   env={**os.environ, "TUNAOS_KCM_ABOUT": str(about), "TUNAOS_IDENTITY": str(root / "usr/share/tunaos/identity.env"),
                        "TUNAOS_DM_ROOT": str(root)}, check=True)
    assert "Website=https://github.com/tuna-os/tunaos" in about.read_text()
    assert run_helper(context, root, "tunaos_verify_fork_branding").returncode != 0
    assert run_helper(context, root).returncode == 0
    assert run_helper(context, root, "tunaos_verify_fork_branding").returncode == 0


def test_tuna_wallpaper_is_explicitly_unsupported(fixture):
    context, root, path, manifest = fixture
    manifest["flavor"] = "tuna"
    path.write_text(json.dumps(manifest))
    before = snapshot(root)
    result = run_helper(context, root, env={"TUNAOS_IMAGE_FLAVOR": "tuna"})
    assert result.returncode != 0
    assert "tuna wallpaper override is unsupported" in result.stderr
    assert snapshot(root) == before


@pytest.mark.parametrize("variable", ["IMAGE_NAME_VARIANT", "TUNAOS_IMAGE_FLAVOR"])
def test_missing_authoritative_build_identity_fails(fixture, variable):
    context, root, _, _ = fixture
    before = snapshot(root)
    result = run_helper(context, root, env={variable: ""})
    assert result.returncode != 0
    assert "must identify the build cell" in result.stderr
    assert snapshot(root) == before
