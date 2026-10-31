"""Tacklebox reads each environment image's /usr/lib/bootc/kargs.d itself
(tuna-os/tacklebox#428) and appends the recipe's `kargs` after them. A recipe
that also carries those arguments puts them on the live command line twice,
so both ISO builders write only tunaOS's own arguments into the recipe, and a
group ISO whose live images declare different kargs.d is a valid group.

The real build scripts run under fakeroot (they refuse to run as a normal
user) with stand-in podman and skopeo; the stand-in tacklebox stops the build
after the recipe is written.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOARD_KARG = "arm64.nopauth"
NVIDIA_KARG = "nvidia-drm.modeset=1"

pytestmark = pytest.mark.skipif(shutil.which("fakeroot") is None, reason="needs fakeroot")


@pytest.fixture
def build(tmp_path):
    tree = tmp_path / "repo"
    shutil.copytree(ROOT, tree, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", ".build", "_upstream-snapshots", "*.iso"))
    images = tmp_path / "images"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # Any image the stand-in podman is asked to read: <images>/<tag>/kargs.d.
    (bindir / "podman").write_text(f"""#!/bin/bash
out="" image=""
for arg in "$@"; do
	case "$arg" in
	*:/tunaos-kargs) out="${{arg%%:*}}" ;;
	tacklebox-stub*) exit 1 ;;
	-*|*:/*) ;;
	*/*:*) image="$arg" ;;
	esac
done
if [[ -n "$out" ]]; then
	uname -m >"$out/arch"
	src="{images}/${{image##*:}}/kargs.d"
	[[ ! -d "$src" ]] || cp -R "$src" "$out/"
fi
exit 0
""")
    (bindir / "skopeo").write_text("#!/bin/sh\necho sha256:0000000000000000000000000000000000000000000000000000000000000000\n")
    for stub in ("podman", "skopeo"):
        (bindir / stub).chmod(0o755)

    def image(tag, *kargs):
        directory = images / tag / "kargs.d"
        directory.mkdir(parents=True)
        (directory / "10-image.toml").write_text(f"kargs = {json.dumps(list(kargs))}\n")

    # yellowfin's flagship group lists gnome-nvidia-hwe but does not build it;
    # building it makes the group two live environments.
    config = json.loads(subprocess.run(["yq", "-o=json", ".", str(tree / ".github/build-config.yml")],
                                       text=True, capture_output=True, check=True).stdout)
    for variant in config["variants"]:
        for flavor in variant["flavors"]:
            if (variant["id"], flavor["id"]) == ("yellowfin", "gnome-nvidia-hwe"):
                flavor["build_image"] = True
    two_env_config = tmp_path / "build-config.json"
    two_env_config.write_text(json.dumps(config))

    def run(script, *args):
        env = {
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "TACKLEBOX_IMAGE": "tacklebox-stub",
            "TUNAOS_BUILD_CONFIG": str(two_env_config),
            "TUNAOS_ROOT_HOME": str(tmp_path / "home"),
            "TUNAOS_ISO_OUT_BASE": str(tmp_path / "iso-group"),
            "TMPDIR": str(tmp_path),
        }
        proc = subprocess.run(["fakeroot", "bash", f"scripts/{script}", *args], cwd=tree,
                              text=True, capture_output=True, env=env)
        recipes = list(tree.glob(".build/iso-tacklebox/*/recipe.json")) + list((tmp_path / "iso-group").glob("*/recipe.json"))
        return proc, (json.loads(recipes[0].read_text()) if recipes else None)

    build.image = image
    build.run = run
    return build


def test_a_single_flavor_recipe_carries_only_tunaos_own_kargs(build):
    build.image("gnome", BOARD_KARG, NVIDIA_KARG)
    proc, recipe = build.run("build-iso-tacklebox.sh", "yellowfin", "gnome", "ghcr")
    assert recipe is not None, proc.stderr
    assert recipe["kargs"] == ["console=ttyS0"]
    assert BOARD_KARG not in json.dumps(recipe)


def test_a_group_recipe_does_not_repeat_the_images_kargs(build):
    build.image("gnome-nvidia", NVIDIA_KARG)
    build.image("gnome-nvidia-hwe", NVIDIA_KARG)
    proc, recipe = build.run("build-iso-group.sh", "yellowfin", "default", "ghcr")
    assert recipe is not None, proc.stderr
    assert NVIDIA_KARG not in json.dumps(recipe)


def test_live_images_with_different_kargs_still_make_one_group(build):
    build.image("gnome-nvidia", NVIDIA_KARG)
    build.image("gnome-nvidia-hwe", BOARD_KARG)
    proc, recipe = build.run("build-iso-group.sh", "yellowfin", "default", "ghcr")
    assert recipe is not None, proc.stderr
    assert [env["image"].rsplit(":", 1)[1] for env in recipe["bootable_environments"]] == ["gnome-nvidia", "gnome-nvidia-hwe"]
