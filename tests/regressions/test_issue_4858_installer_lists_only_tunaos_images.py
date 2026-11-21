"""tunaOS#4858: the installer's image list names this project's images only.

The niri installer on the bonito:niri live ISO listed "Aurora > Aurora DX >
Fedora 43" (ghcr.io/ublue-os/aurora-dx:43) and six more Aurora rows (strict
run walkthrough-niri.json, frames 05 and 06). No TunaOS image shipped
/etc/bootc-installer/images.json, so every frontend fell back to the catalog
it bundles from fisherman (data/images.json), which lists other projects.

90-image-info.sh now writes that file with this image as the only leaf, and
build_scripts/checks/verify-installer-catalog.sh reads it back and stops the
build. The real 90-image-info.sh runs here through the
tests/test_anime_finalization.py harness (literal roots redirected into a
fixture image), so the real writer and the real check both run.

Falsification: behavioural. Delete the images.json writer from
90-image-info.sh and the build fails, because the check finds no catalog.
Feed the check the Aurora rows the walkthrough recorded, a tag leaf under a
foreign registry, a catalog without this image, or an empty list: each run
exits non-zero and prints TUNAOS_INSTALLER_CATALOG_FAIL.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_anime_finalization import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "build_scripts/checks/verify-installer-catalog.sh"
STOCK_RECIPE = ROOT / "system_files/etc/bootc-installer/recipe.json"
PAYLOAD = ROOT / "live-iso/common/src/recipe_payload.py"

# The rows the Bonito Installer showed (walkthrough-niri.json frame 06).
AURORA = {"images": [{"name": "Aurora", "registry": "ghcr.io/ublue-os/aurora", "children": [
    {"name": "Aurora DX", "registry": "ghcr.io/ublue-os/aurora-dx", "children": [
        {"name": "Fedora 43", "tag": "43"}, {"name": "Stable", "tag": "stable"}]},
    {"name": "Beta", "tag": "beta"}]}]}


def built_image(tmp_path, variant, flavor, **env):
    image = Image(tmp_path, variant, flavor)
    image.env.update({f"IS_{base}": "false" for base in (
        "HUMMINGBIRD", "ALMALINUX", "ALMALINUXKITTEN", "CENTOS", "UBUNTU",
        "DEBIAN", "ARCH", "OPENSUSE", "GENTOO")}, IS_FEDORA="true", IMAGE_FLAVOR=flavor, **env)
    recipe = image.root / "etc/bootc-installer/recipe.json"
    recipe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(STOCK_RECIPE, recipe)
    return image


def catalog_of(image):
    return json.loads((image.root / "etc/bootc-installer/images.json").read_text())


def check(etc_dir):
    return subprocess.run(["bash", str(CHECK)], env={"PATH": "/usr/bin:/bin", "TUNAOS_INSTALLER_ETC": str(etc_dir)},
                          capture_output=True, text=True)


def fixture(tmp_path, catalog, imgref="ghcr.io/tuna-os/bonito:niri"):
    etc_dir = tmp_path / "etc-bootc-installer"
    etc_dir.mkdir()
    (etc_dir / "recipe.json").write_text(json.dumps({"imgref": imgref}))
    if catalog is not None:
        (etc_dir / "images.json").write_text(json.dumps(catalog))
    return etc_dir


def test_bonito_niri_build_ships_a_catalog_of_bonito_only(tmp_path):
    image = built_image(tmp_path, "bonito", "niri")
    image.info()
    assert catalog_of(image) == {"images": [{"name": "Bonito", "imgref": "ghcr.io/tuna-os/bonito:niri"}]}
    result = check(image.root / "etc/bootc-installer")
    assert result.returncode == 0, result.stderr
    assert "TUNAOS_INSTALLER_CATALOG_OK leaves=1 prefix=ghcr.io/tuna-os/ ghcr.io/tuna-os/bonito:niri" in result.stdout


def test_a_forks_catalog_follows_its_publish_destination(tmp_path):
    """[build.publish] (IMAGE_REGISTRY/REPO_ORGANIZATION) moves the allowed namespace."""
    image = built_image(tmp_path, "bonito", "kde",
                        IMAGE_REGISTRY="registry.example:5000", IMAGE_VENDOR="acme/team")
    image.info()
    assert catalog_of(image)["images"] == [{"name": "Bonito", "imgref": "registry.example:5000/acme/team/bonito:kde"}]
    assert check(image.root / "etc/bootc-installer").returncode == 0


def test_the_build_fails_when_the_catalog_writer_is_gone(tmp_path):
    image = built_image(tmp_path, "bonito", "niri")
    script = image.context / "build_scripts/90-image-info.sh"
    source = script.read_text()
    start = source.index('\tpython3 - "${RECIPE_FILE%/*}/images.json"')
    end = source.index("PYEOF\n", start) + len("PYEOF\n")
    script.write_text(source[:start] + source[end:])
    image.env["TUNAOS_PUBLISHED_IMAGE_REF"] = image.resolve_published_ref()
    result = subprocess.run(["bash", str(script)], env=image.env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "the installer would list its bundled catalog" in result.stderr


@pytest.mark.parametrize("catalog, message", [
    (AURORA, "lists images outside ghcr.io/tuna-os/: Aurora > Aurora DX > Fedora 43 (ghcr.io/ublue-os/aurora-dx:43)"),
    ({"images": [{"name": "Bonito", "imgref": "ghcr.io/tuna-os/bonito:niri"},
                 {"name": "Other", "registry": "quay.io/fedora/fedora-bootc", "children": [{"name": "44", "tag": "44"}]}]},
     "Other > 44 (quay.io/fedora/fedora-bootc:44)"),
    ({"images": [{"name": "Bonito", "imgref": "ghcr.io/tuna-os/bonito:niri",
                  "nvidia_imgref": "ghcr.io/ublue-os/aurora-dx-nvidia:43"}]}, "aurora-dx-nvidia:43"),
    ({"images": [{"name": "Yellowfin", "imgref": "ghcr.io/tuna-os/yellowfin:gnome"}]},
     "does not list this image, ghcr.io/tuna-os/bonito:niri"),
    ({"images": []}, "has no non-empty `images` list"),
    (None, "cannot read"),
], ids=["walkthrough-aurora", "foreign-tag-leaf", "foreign-nvidia", "own-image-missing", "empty", "missing"])
def test_the_check_rejects_a_catalog_that_lists_other_images(tmp_path, catalog, message):
    result = check(fixture(tmp_path, catalog))
    assert result.returncode != 0
    assert "TUNAOS_INSTALLER_CATALOG_FAIL" in result.stdout
    assert message in result.stderr


def test_live_customize_stamps_the_probed_layout_on_the_catalog_leaf(tmp_path):
    """A user who picks the catalog row gets the layout the live ISO probed."""
    etc_dir = fixture(tmp_path, {"images": [{"name": "Yellowfin", "imgref": "ghcr.io/tuna-os/yellowfin:gnome"}]},
                      imgref="ghcr.io/tuna-os/yellowfin:gnome")
    result = subprocess.run([sys.executable, str(PAYLOAD), str(etc_dir / "recipe.json"), "grub2", "false", "xfs"],
                            env={"TUNA_LIVE_DEFER_LOCAL_IMGREF": "1"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    leaf = json.loads((etc_dir / "images.json").read_text())["images"][0]
    assert (leaf["bootloader"], leaf["composefs"], leaf["filesystem"]) == ("grub2", False, "xfs")
    assert check(etc_dir).returncode == 0
