"""Installer recipe refs resolve end to end and fail closed.

build-image-inner.sh resolves the canonical TOML published ref through
scripts/published-image-ref.sh (variant publish_name + tag_suffix, so
bonito-rawhide and flounder-sid keep their suffixes) and passes it to the
image build as TUNAOS_PUBLISHED_IMAGE_REF. build_scripts/90-image-info.sh
interpolates that exact value into recipe.json imgref/local_imgref, refusing
to build when it is absent.

These tests execute the actual 90-image-info.sh through the
test_anime_finalization Image harness (redirected roots), not a
sed-extracted fragment of it. Display-branding and URI-preservation
execution coverage lives in test_identity_publish_integration.py and
test_anime_finalization.py.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent))
from test_anime_finalization import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STOCK_RECIPE = ROOT / "system_files/etc/bootc-installer/recipe.json"


def image_with_recipe(tmp_path, variant="yellowfin", flavor="kde", **env):
    image = Image(tmp_path, variant, flavor)
    image.env.update({f"IS_{base}": "false" for base in (
        "FEDORA", "HUMMINGBIRD", "ALMALINUX", "ALMALINUXKITTEN", "CENTOS", "UBUNTU",
        "DEBIAN", "OPENSUSE", "GENTOO")}, IS_ARCH="true", IMAGE_FLAVOR=flavor, **env)
    target = image.root / "etc/bootc-installer/recipe.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(STOCK_RECIPE, target)
    return image


def read_recipe(image):
    return json.loads((image.root / "etc/bootc-installer/recipe.json").read_text(encoding="utf-8"))


def test_suffix_variant_recipe_names_the_suffixed_published_ref(tmp_path):
    """bonito:gnome-rawhide (not gnome, not the umbrella) lands in the recipe."""
    image = image_with_recipe(tmp_path, "bonito-rawhide", "gnome")
    image.info()
    recipe = read_recipe(image)
    assert recipe["imgref"] == "ghcr.io/tuna-os/bonito:gnome-rawhide"
    assert recipe["local_imgref"] == "containers-storage:ghcr.io/tuna-os/bonito:gnome-rawhide"


def test_flavor_suffix_variant_recipe_names_the_suffixed_published_ref(tmp_path):
    """flounder:xfce-sid lands in the recipe for the sid stream variant."""
    image = image_with_recipe(tmp_path, "flounder-sid", "xfce")
    image.info()
    recipe = read_recipe(image)
    assert recipe["imgref"] == "ghcr.io/tuna-os/flounder:xfce-sid"
    assert recipe["local_imgref"] == "containers-storage:ghcr.io/tuna-os/flounder:xfce-sid"


def test_missing_published_ref_fails_the_build_without_interpolating_refs(tmp_path):
    """Without the engine-resolved ref the build stops; no ref is interpolated."""
    image = image_with_recipe(tmp_path)
    before = json.loads((image.root / "etc/bootc-installer/recipe.json").read_text(encoding="utf-8"))
    env = {k: v for k, v in image.env.items() if k != "TUNAOS_PUBLISHED_IMAGE_REF"}
    result = subprocess.run(["bash", str(image.context / "build_scripts/90-image-info.sh")],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "missing canonical published image ref" in result.stderr
    after = read_recipe(image)
    assert after.get("imgref") == before.get("imgref")
    assert "local_imgref" not in after
