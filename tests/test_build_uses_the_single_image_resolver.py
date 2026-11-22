"""The build engine takes its pinned input refs from scripts/resolve-image.sh.

resolve-image.sh is documented as the one image resolver (ADR 0007,
docs/PIPELINE.md, AGENTS.md), but scripts/build-image-inner.sh used to resolve
common, brew, utah-packages, gnome50-el10-packages and the akmods base with its
own copy of the same code (tunaOS#4750). The tests that exercised the resolver
then exercised code no build ran, and the copies had already drifted: the
resolver cut a `localhost:5000/common` override down to `localhost`.

These tests hold the single path: the engine contains no second default for
these inputs, every build argument it passes equals what the resolver prints,
and a registry host:port survives the resolver's tag stripping.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESOLVE = ROOT / "scripts" / "resolve-image.sh"
INNER = ROOT / "scripts" / "build-image-inner.sh"

# build argument -> resolve-image.sh role
ROLES = {
    "COMMON_IMAGE_REF": "common",
    "BREW_IMAGE_REF": "brew",
    "UTAH_PACKAGES_IMAGE_REF": "utah-packages",
    "GNOME50_EL10_PACKAGES_IMAGE_REF": "gnome50-el10-packages",
    "AKMODS_BASE": "akmods",
}
OVERRIDES = {
    "COMMON_IMAGE": "common",
    "BREW_IMAGE": "brew",
    "UTAH_PACKAGES_IMAGE": "utah-packages",
    "GNOME50_EL10_PACKAGES_IMAGE": "gnome50-el10-packages",
}

def resolve(role, cwd=ROOT, **env):
    out = subprocess.run(
        ["bash", str(cwd / "scripts/resolve-image.sh"), "yellowfin", role],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, **env},
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_the_build_engine_keeps_no_copy_of_the_resolver():
    text = INNER.read_text(encoding="utf-8")
    for role in ROLES.values():
        assert f"resolve_image_ref {role})" in text, role
    for variable in OVERRIDES:
        assert f"${{{variable}:-" not in text, f"{variable} default belongs in resolve-image.sh"
    assert ".digest' image-versions.yaml" not in text
    assert "AKMODS_ORG" not in text


@pytest.mark.parametrize("variable,role", sorted(OVERRIDES.items()))
def test_a_registry_port_survives_tag_stripping(variable, role):
    for image in ("localhost:5000/mirror/x", "localhost:5000/mirror/x:latest"):
        ref = resolve(role, **{variable: image})
        assert ref.startswith("localhost:5000/mirror/x@sha256:"), ref


@pytest.mark.parametrize("variable,role", sorted(OVERRIDES.items()))
def test_a_tag_on_the_override_gives_way_to_the_pin(variable, role):
    ref = resolve(role, **{variable: "mirror.example/x:latest"})
    assert ref.startswith("mirror.example/x@sha256:"), ref


def test_every_pinned_build_argument_is_the_resolvers_output(tmp_path):
    """Run the real engine against a copy of the tracked sources, with a stub
    podman that records its arguments, and compare the build arguments."""
    context = tmp_path / "context"
    tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"], text=True).split(
        "\0"
    )
    for relative in filter(None, tracked):
        if relative.split("/", 1)[0] in {
            "docs",
            "tests",
            "_upstream-snapshots",
            "system_files",
            "live-iso",
            ".spektacular",
        }:
            continue
        source = ROOT / relative
        if source.is_dir():
            continue
        (context / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, context / relative, follow_symlinks=False)
    subprocess.run(["git", "init", "-q", str(context)], check=True)
    subprocess.run(["git", "-C", str(context), "add", "--all"], check=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "builder.log"
    # verify-image-hostname.sh reads the built image with `podman create` (which
    # must print a container id) and `podman cp` of /etc/hostname (absent here).
    (binaries / "podman").write_text(
        r"""#!/bin/bash
printf "%s\n" "$@" >>"$BUILDER_LOG"
case "$1" in
create) echo stub-container ;;
cp) echo 'Error: "/etc/hostname" could not be found on container: no such file or directory' >&2; exit 1 ;;
esac
"""
    )
    (binaries / "podman").chmod(0o755)
    env = {
        **os.environ,
        "BUILDER_LOG": str(log),
        "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
        "IMAGE_TAG": "localhost/acme/yellowfin:gnome",
        "VARIANT": "yellowfin",
        "PUBLIC_IMAGE_NAME": "yellowfin",
        "CONTAINERFILE": "Containerfile.el10",
        "BASE_IMAGE": "localhost/base:1",
        "PLATFORM": "linux/amd64",
        "DESKTOP_FLAVOR": "gnome",
        "TUNAOS_IMAGE_FLAVOR": "gnome",
        "ENABLE_HWE": "0",
        "ENABLE_NVIDIA": "0",
        "ENABLE_ASAHI": "0",
        "ENABLE_SSHD": "0",
        "IMAGE_REGISTRY": "localhost",
        "REPO_ORGANIZATION": "acme",
        "USE_CACHE": "0",
        "IS_CI": "0",
        "SKIP_RECHUNK": "1",
        "SKIP_SUBMODULES": "1",
        "COMMON_IMAGE": "localhost:5000/mirror/common",
    }
    env.pop("TUNAOS_BUILD_CONFIG", None)
    result = subprocess.run(
        ["bash", "scripts/build-image-inner.sh"],
        check=False,
        cwd=context,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    args = dict(arg.split("=", 1) for arg in log.read_text().splitlines() if "=" in arg)
    resolver_env = {"COMMON_IMAGE": env["COMMON_IMAGE"]}
    for build_arg, role in ROLES.items():
        assert args[build_arg] == resolve(role, cwd=context, **resolver_env), build_arg
    assert args["COMMON_IMAGE_REF"].startswith("localhost:5000/mirror/common@sha256:")
