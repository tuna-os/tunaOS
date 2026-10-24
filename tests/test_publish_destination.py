"""A fork names its publish destination once, in tunaos.toml [build.publish].

The destination decides where images are pushed and what each image records as
its own vendor and update reference. Precedence, highest first: an operator
override in the environment, [build.publish], the GitHub repository owner, and
finally ghcr.io/tuna-os. The stock file omits [build.publish] so TunaOS itself
is unchanged and a fresh fork stays zero-config on GitHub.
"""
from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("publish_config_under_test", ROOT / "scripts/lib/tunaos_config.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)

FORK = {"registry": "quay.io", "namespace": "acme"}


def adapter(tmp_path, publish=None):
    """Write the generated build config a fork with `publish` would produce."""
    source = config.load()
    if publish is not None:
        source = copy.deepcopy(source)
        source["build"]["publish"] = publish
        config.validate(source)
    path = tmp_path / "build-config.yml"
    path.write_text(config.render(source), encoding="utf-8")
    return path


def resolve(path, **env):
    clean = {k: v for k, v in os.environ.items()
             if k not in ("IMAGE_REGISTRY", "REPO_ORGANIZATION", "GITHUB_REPOSITORY_OWNER")}
    result = subprocess.run(
        ["bash", "-c", 'source scripts/lib/publish-destination.sh; tunaos_publish_destination "$1"', "_", str(path)],
        cwd=ROOT, env={**clean, **env}, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def test_stock_file_stays_fork_neutral():
    assert "publish" not in config.load()["build"]


@pytest.mark.parametrize("publish", [
    {"registry": "Quay.io", "namespace": "acme"},
    {"registry": "quay.io", "namespace": "Acme"},
    {"registry": "quay.io/acme", "namespace": "acme"},
    {"registry": "quay.io", "namespace": "../escape"},
    {"registry": "quay.io"},
    {"registry": "quay.io", "namespace": "acme", "tag": "latest"},
])
def test_malformed_destination_is_rejected(publish):
    source = copy.deepcopy(config.load())
    source["build"]["publish"] = publish
    with pytest.raises(config.ConfigError):
        config.validate(source)


@pytest.mark.parametrize("registry,namespace", [
    ("localhost:5000", "dev"), ("registry.gitlab.com", "group/sub-group/os"), ("ghcr.io", "my_org")])
def test_real_registry_shapes_are_accepted(registry, namespace):
    source = copy.deepcopy(config.load())
    source["build"]["publish"] = {"registry": registry, "namespace": namespace}
    config.validate(source)


def test_stock_resolves_exactly_as_before(tmp_path):
    stock = adapter(tmp_path)
    assert resolve(stock) == "ghcr.io tuna-os"
    assert resolve(stock, GITHUB_REPOSITORY_OWNER="tuna-os") == "ghcr.io tuna-os"


def test_unconfigured_github_fork_publishes_under_its_owner(tmp_path):
    # GitHub owners may contain uppercase; registries reject it.
    assert resolve(adapter(tmp_path), GITHUB_REPOSITORY_OWNER="Acme-Fork") == "ghcr.io acme-fork"


def test_configured_destination_beats_the_repository_owner(tmp_path):
    assert resolve(adapter(tmp_path, FORK), GITHUB_REPOSITORY_OWNER="someone-else") == "quay.io acme"


def test_operator_override_beats_the_config_per_field(tmp_path):
    fork = adapter(tmp_path, FORK)
    assert resolve(fork, REPO_ORGANIZATION="staging") == "quay.io staging"
    assert resolve(fork, IMAGE_REGISTRY="registry.example.com") == "registry.example.com acme"


def test_ci_combined_registry_form_is_split_not_doubled(tmp_path):
    # CI jobs export IMAGE_REGISTRY=ghcr.io/<owner>. Under sudo every other
    # variable is reset, so this one value must carry the namespace.
    assert resolve(adapter(tmp_path), IMAGE_REGISTRY="ghcr.io/acme-fork") == "ghcr.io acme-fork"
    assert resolve(adapter(tmp_path, FORK), IMAGE_REGISTRY="quay.io/acme") == "quay.io acme"


def test_published_ref_used_by_iso_and_gates_follows_the_fork(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if k not in ("IMAGE_REGISTRY", "REPO_ORGANIZATION", "GITHUB_REPOSITORY_OWNER")}
    env["TUNAOS_BUILD_CONFIG"] = str(adapter(tmp_path, FORK))
    ref = subprocess.run(["bash", "scripts/published-image-ref.sh", "yellowfin", "gnome", "ghcr"],
                         cwd=ROOT, env=env, text=True, capture_output=True, check=True).stdout.strip()
    assert ref == "quay.io/acme/yellowfin:gnome"
