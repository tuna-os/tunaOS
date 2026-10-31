"""A live ISO boots with the kernel arguments its image declares.

bootc gives every installed deployment the arguments in the image's
/usr/lib/bootc/kargs.d, but tacklebox writes the live boot entries from the
recipe's `kargs` alone. scripts/lib/image-kargs.sh reads kargs.d out of the
image, by bootc's rules (scripts/lib/bootc_kargs.py), for both ISO builders.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "scripts/lib/bootc_kargs.py"
HELPER = ROOT / "scripts/lib/image-kargs.sh"


def parse(directory, arch):
    return subprocess.run([sys.executable, str(PARSER), str(directory), arch], text=True, capture_output=True)


def write(directory, name, text):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text)


def test_kargs_follow_bootc_order_and_architecture_rules(tmp_path):
    kargs_d = tmp_path / "kargs.d"
    write(kargs_d, "20-later.toml", 'kargs = ["quiet"]\n')
    write(kargs_d, "10-board.toml", 'kargs = ["arm64.nopauth", "clk_ignore_unused pd_ignore_unused"]\n'
                                    'match-architectures = ["aarch64"]\n')
    write(kargs_d, "00-x86.toml", 'kargs = ["intel_iommu=on"]\nmatch-architectures = ["x86_64"]\n')
    write(kargs_d, "README", "not a kargs file\n")
    on_arm = parse(kargs_d, "aarch64")
    assert on_arm.returncode == 0, on_arm.stderr
    assert on_arm.stdout.split() == ["arm64.nopauth", "clk_ignore_unused", "pd_ignore_unused", "quiet"]
    assert parse(kargs_d, "x86_64").stdout.split() == ["intel_iommu=on", "quiet"]


def test_an_image_without_kargs_d_has_no_extra_arguments(tmp_path):
    proc = parse(tmp_path / "absent", "aarch64")
    assert (proc.returncode, proc.stdout) == (0, "")


@pytest.mark.parametrize("text", ['kargs = ["a"]\nmatch_architectures = ["aarch64"]\n', 'kargs = "a"\n', "kargs = [\n"])
def test_a_kargs_file_bootc_would_reject_fails_the_build(tmp_path, text):
    write(tmp_path / "kargs.d", "10-bad.toml", text)
    proc = parse(tmp_path / "kargs.d", "aarch64")
    assert proc.returncode == 1
    assert "10-bad.toml" in proc.stderr


@pytest.fixture
def images(tmp_path):
    """Fake images for a stand-in podman: <name>/arch and <name>/kargs.d."""
    store = tmp_path / "images"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("bash", "cp", "mkdir", "mktemp", "rm", "jq", "cat", "dirname"):
        (bindir / tool).symlink_to(shutil.which(tool))
    (bindir / "python3").symlink_to(sys.executable)
    # podman run ... -v <host>:/tunaos-kargs --entrypoint /bin/sh <image> -c <script>:
    # copy what the script copies out of the named image.
    (bindir / "podman").write_text(f"""#!/bin/bash
args=("$@")
for ((i = 0; i < ${{#args[@]}}; i++)); do
	[[ "${{args[i]}}" == -v ]] && out="${{args[i+1]%%:*}}"
done
image="${{args[${{#args[@]}}-3]}}"
src="{store}/${{image//[\\/:]/_}}"
[[ -d "$src" ]] || {{ echo "Error: $image: image not known" >&2; exit 125; }}
cp "$src/arch" "$out/arch"
[[ ! -d "$src/kargs.d" ]] || cp -R "$src/kargs.d" "$out/"
""")
    (bindir / "podman").chmod(0o755)

    def image(name, arch, **files):
        directory = store / name.replace("/", "_").replace(":", "_")
        directory.mkdir(parents=True)
        (directory / "arch").write_text(arch + "\n")
        for filename, text in files.items():
            write(directory / "kargs.d", filename.replace("_", "-") + ".toml", text)
        return name

    def live_kargs(*refs):
        return subprocess.run(["bash", "-c", f'set -euo pipefail; . "{HELPER}"; tunaos_live_kargs_json "$@"', "bash", *refs],
                              text=True, capture_output=True, env={"PATH": str(bindir), "TMPDIR": str(tmp_path)})

    image.live_kargs = live_kargs
    return image


BOARD = 'kargs = ["arm64.nopauth", "clk_ignore_unused", "pd_ignore_unused"]\nmatch-architectures = ["aarch64"]\n'


def test_a_hardware_image_live_entry_gets_its_kargs(images):
    ref = images("ghcr.io/tuna-os/bonito:gnome-board", "aarch64", **{"10_board": BOARD})
    proc = images.live_kargs(ref)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["arm64.nopauth", "clk_ignore_unused", "pd_ignore_unused"]


def test_an_image_for_another_architecture_contributes_nothing(images):
    ref = images("ghcr.io/tuna-os/bonito:gnome", "x86_64", **{"10_board": BOARD})
    proc = images.live_kargs(ref)
    assert (proc.returncode, json.loads(proc.stdout)) == (0, [])


def test_live_images_sharing_their_kargs_share_the_list(images):
    nvidia = 'kargs = ["rd.driver.blacklist=nouveau", "nvidia-drm.modeset=1"]\n'
    one = images("localhost/bonito:gnome-nvidia", "x86_64", **{"00_nvidia": nvidia})
    two = images("localhost/bonito:gnome-nvidia-hwe", "x86_64", **{"00_nvidia": nvidia})
    proc = images.live_kargs(one, two)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["rd.driver.blacklist=nouveau", "nvidia-drm.modeset=1"]


def test_live_images_with_different_kargs_cannot_share_one_recipe(images):
    plain = images("localhost/bonito:gnome", "aarch64")
    board = images("localhost/bonito:gnome-board", "aarch64", **{"10_board": BOARD})
    proc = images.live_kargs(plain, board)
    assert proc.returncode == 1
    assert "declare different kernel arguments" in proc.stderr and "gnome-board: arm64.nopauth" in proc.stderr


def test_an_unreadable_image_fails_instead_of_dropping_its_kargs(images):
    proc = images.live_kargs("ghcr.io/tuna-os/absent:gnome")
    assert proc.returncode == 1
    assert "could not read /usr/lib/bootc/kargs.d from ghcr.io/tuna-os/absent:gnome" in proc.stderr
