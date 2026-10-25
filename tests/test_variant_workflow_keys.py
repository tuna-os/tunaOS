"""Nightly schedule and the manual sweep are variant keys in tunaos.toml.

`scripts/generate-workflows.py` held the cron table (`SCHEDULES`) and
`build-flavor.yml` held a hand-written variant list, so a fork that added or
dropped a variant edited code too. They are now `variants.<id>.schedule` and
`variants.<id>.flavor_dispatch`; the stock values below are the table and the
list the repository had before, so TunaOS's generated workflows do not change.
"""
from __future__ import annotations

import copy
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = load("workflow_keys_config", "scripts/lib/tunaos_config.py")
generator = load("workflow_keys_generator", "scripts/generate-workflows.py")

# The SCHEDULES table that lived in scripts/generate-workflows.py.
STOCK_SCHEDULES = {
    "yellowfin": "20 0 * * *",
    "albacore": "20 2 * * *",
    "gurnard": "20 4 * * *",
    "guppy": "20 6 * * *",
    "skipjack": "20 9 * * *",
    "bonito": "20 11 * * *",
    "marlin": "20 13 * * *",
    "bonito-rawhide": "20 15 * * *",
    "grouper": "20 17 * * *",
    "sailfin": "20 19 * * *",
    "flounder": "20 21 * * *",
    "hummingbird": "20 22 * * *",
    "flounder-sid": "20 23 * * *",
}
# The `matrix.variant` list that lived in build-flavor.yml (as a set: the
# generated list follows tunaos.toml order, the hand-written one did not).
STOCK_SWEEP = {"yellowfin", "albacore", "skipjack", "bonito", "bonito-rawhide", "grouper", "marlin",
               "flounder", "flounder-sid", "sailfin", "guppy"}


def stock():
    return config.load()


def test_stock_schedules_are_the_table_the_generator_used_to_hold():
    schedules = {name: v["schedule"] for name, v in stock()["variants"].items() if "schedule" in v}
    assert schedules == STOCK_SCHEDULES
    assert "wahoo" not in schedules  # experimental: dispatch-only, no cron


def test_stock_sweep_is_the_list_build_flavor_used_to_hold():
    assert set(generator.flavor_sweep(stock()["variants"])) == STOCK_SWEEP


def test_the_two_stock_opt_outs_are_the_variants_that_were_never_in_the_sweep():
    opted_out = {name for name, v in stock()["variants"].items() if v.get("flavor_dispatch") is False}
    assert opted_out == {"gurnard", "hummingbird"}


def test_workflow_keys_stay_out_of_the_build_matrix():
    """build-config.yml is what every jq/yq consumer reads; its shape must not move."""
    for variant in config.matrix(stock())["variants"]:
        assert not set(variant) & set(config.WORKFLOW_KEYS)


def test_every_committed_wrapper_has_the_cron_tunaos_toml_names():
    for name, variant in stock()["variants"].items():
        document = yaml.safe_load((ROOT / f".github/workflows/build-{name}.yml").read_text(encoding="utf-8"))
        triggers = document.get("on", document.get(True))
        if "schedule" in variant:
            assert triggers["schedule"] == [{"cron": variant["schedule"]}]
        else:
            assert "schedule" not in triggers


def test_committed_build_flavor_list_is_what_the_generator_writes():
    path = ROOT / ".github/workflows/build-flavor.yml"
    text = path.read_text(encoding="utf-8")
    assert generator.with_flavor_sweep(text, generator.flavor_sweep(stock()["variants"])) == text
    listed = yaml.safe_load(text)["jobs"]["build"]["strategy"]["matrix"]["variant"]
    assert set(listed) == STOCK_SWEEP and len(listed) == len(STOCK_SWEEP)


def test_sweep_rewrite_replaces_only_the_variant_line():
    text = "a: 1\n        variant: [x, y]\nb: 2\n"
    assert generator.with_flavor_sweep(text, ["p", "q", "r"]) == "a: 1\n        variant: [p, q, r]\nb: 2\n"
    for broken in ("a: 1\n", "        variant: [x]\n        variant: [y]\n"):
        with pytest.raises(ValueError, match="expected one"):
            generator.with_flavor_sweep(broken, ["p"])


def test_sweep_skips_experimental_and_opted_out_variants_and_honours_opt_in():
    variants = {"a": {}, "b": {"experimental": True}, "c": {"flavor_dispatch": False},
                "d": {"experimental": True, "flavor_dispatch": True}, "e": {"flavor_dispatch": True}}
    assert generator.flavor_sweep(variants) == ["a", "d", "e"]


@pytest.mark.parametrize("schedule", ["20 0 * * *", "*/15 3 * * 1", "0 6,18 * * 1-5"])
def test_real_cron_expressions_are_accepted(schedule):
    document = copy.deepcopy(stock())
    document["variants"]["yellowfin"]["schedule"] = schedule
    config.validate(document)


@pytest.mark.parametrize("schedule", [
    "", "20 0 * *", "20 0 * * * *", '20 0 * * *"\n  evil: 1', "@daily", "20 0 * * MON", 20, None])
def test_malformed_cron_is_rejected(schedule):
    document = copy.deepcopy(stock())
    document["variants"]["yellowfin"]["schedule"] = schedule
    with pytest.raises(config.ConfigError, match="schedule"):
        config.validate(document)


def test_an_experimental_variant_cannot_have_a_nightly():
    document = copy.deepcopy(stock())
    document["variants"]["wahoo"]["schedule"] = "20 1 * * *"
    with pytest.raises(config.ConfigError, match="dispatch-only"):
        config.validate(document)


def test_flavor_dispatch_must_be_a_boolean():
    document = copy.deepcopy(stock())
    document["variants"]["yellowfin"]["flavor_dispatch"] = "no"
    with pytest.raises(config.ConfigError, match="flavor_dispatch"):
        config.validate(document)


def test_a_fork_edits_only_tunaos_toml_for_its_schedule_and_sweep(tmp_path):
    """Run the real generator over a copy of the repository with an edited tunaos.toml."""
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / ".github/workflows").mkdir(parents=True)
    shutil.copy(ROOT / ".github/workflows/build-flavor.yml", tmp_path / ".github/workflows/build-flavor.yml")
    source = (ROOT / "tunaos.toml").read_text(encoding="utf-8")
    # Move yellowfin's nightly, and take hummingbird (opted out) and gurnard (opted out) into the sweep.
    edited = source.replace('schedule = "20 0 * * *"', 'schedule = "7 7 * * *"', 1)
    edited = re.sub(r"^flavor_dispatch = false\n", "", edited, flags=re.M)
    (tmp_path / "tunaos.toml").write_text(edited, encoding="utf-8")
    subprocess.run(["python3", "scripts/generate-workflows.py"], cwd=tmp_path, check=True, capture_output=True)

    wrapper = yaml.safe_load((tmp_path / ".github/workflows/build-yellowfin.yml").read_text(encoding="utf-8"))
    assert wrapper.get("on", wrapper.get(True))["schedule"] == [{"cron": "7 7 * * *"}]
    sweep = yaml.safe_load((tmp_path / ".github/workflows/build-flavor.yml").read_text(encoding="utf-8"))
    listed = sweep["jobs"]["build"]["strategy"]["matrix"]["variant"]
    assert {"gurnard", "hummingbird"} <= set(listed) and "wahoo" not in listed


def test_sweep_rewrite_tolerates_indentation_and_spacing():
    for source, expected in (
        ("a: 1\n  variant:   [x, y]  \nb: 2\n", "a: 1\n  variant:   [p, q]\nb: 2\n"),
        ("a: 1\n\t\tvariant: [x,y]\nb: 2\n", "a: 1\n\t\tvariant: [p, q]\nb: 2\n"),
    ):
        assert generator.with_flavor_sweep(source, ["p", "q"]) == expected
