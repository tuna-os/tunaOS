"""Filtered candidate overlays build their exact native parent chain in CI."""

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_selection", ROOT / "scripts/candidate-flavor-selection.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def config():
    return {"variants": [{"id": "flounder-sid", "platforms": ["linux/amd64", "linux/arm64"],
                          "base_image": "debian:sid", "flavors": [
        {"id": "base", "stage": 1, "build_image": True},
        {"id": "gnome", "stage": 2, "build_image": True},
        {"id": "gnome-hwe", "stage": 3, "build_image": True, "platforms": ["linux/amd64"]},
        {"id": "gnome-nvidia", "stage": 3, "build_image": True, "platforms": ["linux/amd64"]},
        {"id": "gnome-nvidia-hwe", "stage": 4, "build_image": True, "platforms": ["linux/amd64"]},
    ]}]}


def select(value, flavor, **kwargs):
    return MODULE.select(value, "flounder-sid", flavor,
                         kwargs.get("event", "workflow_dispatch"),
                         kwargs.get("repository", "tuna-os/tunaOS"),
                         kwargs.get("ref", "refs/heads/feature"))


def test_nvidia_selects_gnome_on_only_the_required_platform():
    assert select(config(), "gnome-nvidia") == {"flounder-sid": {
        "gnome": ["linux/amd64"], "gnome-nvidia": ["linux/amd64"],
    }}


def test_combined_overlay_uses_actual_hwe_parent_not_nvidia_prefix():
    assert select(config(), "gnome-nvidia-hwe") == {"flounder-sid": {
        "gnome": ["linux/amd64"], "gnome-hwe": ["linux/amd64"],
        "gnome-nvidia-hwe": ["linux/amd64"],
    }}


def test_plain_desktop_remains_a_full_source_build_without_artificial_base():
    assert select(config(), "gnome") == {"flounder-sid": {
        "gnome": ["linux/amd64", "linux/arm64"],
    }}


@pytest.mark.parametrize("options", [
    {"ref": "refs/heads/main"}, {"event": "pull_request"}, {"event": "schedule"},
])
def test_main_and_ordinary_scheduling_are_unchanged(options):
    assert select(config(), "gnome-nvidia", **options) is None


def test_full_variant_selection_remains_unchanged():
    assert select(config(), "all") is None


def test_fork_main_is_still_candidate_scope():
    assert select(config(), "gnome-nvidia", repository="fork/tunaOS", ref="refs/heads/main") is not None


@pytest.mark.parametrize("problem", ["disabled", "missing", "platform", "stage"])
def test_unavailable_parent_fails_without_production_fallback(problem):
    value = config()
    flavors = value["variants"][0]["flavors"]
    parent = flavors[1]
    if problem == "disabled":
        parent["build_image"] = False
    elif problem == "missing":
        flavors.remove(parent)
    elif problem == "platform":
        parent["platforms"] = ["linux/arm64"]
    else:
        parent["stage"] = 3
    with pytest.raises(ValueError):
        select(value, "gnome-nvidia")


def test_disabled_requested_flavor_is_never_reenabled():
    value = config()
    value["variants"][0]["flavors"][3]["build_image"] = False
    assert select(value, "gnome-nvidia") == {}


def test_actual_sid_config_and_jq_matrix_consume_parent_platform_selection(monkeypatch):
    value = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
    selection = select(value, "gnome-nvidia")
    assert set(selection["flounder-sid"]) == {"gnome", "gnome-nvidia"}
    assert selection["flounder-sid"]["gnome"] == ["linux/amd64"]
    workflow = (ROOT / ".github/workflows/build-variant.yml").read_text()
    expression = re.search(r"FULL_MATRIX=.*?--argjson selection.*?'(.*?)'\s*\|\s*jq", workflow, re.S)
    assert expression
    monkeypatch.setenv("FILTER_VARIANT", "flounder-sid")
    monkeypatch.setenv("FILTER_FLAVOR", "gnome-nvidia")
    result = subprocess.run(["jq", "-c", "--arg", "event", "workflow_dispatch",
                             "--argjson", "selection", json.dumps(selection), expression[1]],
                            input=json.dumps(value), text=True, capture_output=True, check=True)
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert {(row["flavor"], row["stage"]) for row in rows} == {("gnome", 2), ("gnome-nvidia", 3)}
    assert all(row["platforms"] == "linux/amd64" for row in rows)
    assert all(json.loads(row["platforms_json"]) == [{"platform": "linux/amd64", "safeplatform": "linux-amd64"}]
               for row in rows)
