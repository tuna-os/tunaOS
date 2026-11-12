"""An nvidia flavor cuts over on its sibling's receipt, and only on that.

Strict qualification boots a VM with no GPU, so an nvidia image cannot be proven
by a receipt of its own; it layers the driver on the desktop the sibling proves.
The maintainer decided (2026-11-12) to assume it once the sibling qualifies, so
the 16 GB nvidia ISOs need not be built and hosted.
"""
import copy
import importlib.util
from pathlib import Path

import pytest

HELPERS_PATH = Path(__file__).with_name("test_iso_delivery_empty_policy_is_identity.py")
SPEC = importlib.util.spec_from_file_location("delivery_helpers", HELPERS_PATH)
H = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(H)
MOD = H.MOD

NVIDIA_RETAINED = [*H.KDE_RETAINED, "fish-kde-nvidia-latest.iso", "fish-kde-nvidia-1-x86_64.iso"]


@pytest.fixture(autouse=True)
def _receipt_config(monkeypatch):
    monkeypatch.setattr(MOD.qualification_receipt, "_config", lambda: H.RECEIPT_CONFIG)


def _config(targets, retained=NVIDIA_RETAINED):
    config = H._config(targets, retained)
    variant = config["variants"][0]
    variant["flavors"].append({"id": "kde-nvidia", "build_image": True, "build_iso": True})
    config["iso_groups"] = []
    return config


def _inherits(flavor="kde-nvidia", inherits="kde", qualified_at="2026-11-04", platform="linux/amd64"):
    return {"variant": "fish", "flavor": flavor, "platform": platform,
            "qualification": "browser-qualified", "qualified_at": qualified_at, "inherits": inherits}


def test_an_nvidia_flavor_cuts_over_on_its_siblings_receipt(tmp_path):
    config = _config([H._target(tmp_path, "kde"), _inherits()])
    assert MOD.active_targets(config, receipts_dir=tmp_path) == {
        ("fish", "kde", "linux/amd64"), ("fish", "kde-nvidia", "linux/amd64")}


@pytest.mark.parametrize("mutate,message", [
    (lambda t: t.update(inherits="kde-hwe"), "must inherit 'kde'"),
    (lambda t: t.update(qualified_at="2026-11-05"), "qualified_at must be 2026-11-04"),
    (lambda t: t.update(flavor="kde-hwe", inherits="kde"), "not an nvidia flavor"),
    (lambda t: t.update(platform="linux/arm64"), "has no receipt-backed cutover target for linux/arm64"),
    (lambda t: t.update(evidence="sha256:" + "0" * 64), "exactly one of evidence or inherits"),
])
def test_a_wrong_inheritance_is_refused(tmp_path, mutate, message):
    """Falsification: without check_inheritance any nvidia entry would cut over
    on nothing."""
    entry = _inherits()
    mutate(entry)
    config = _config([H._target(tmp_path, "kde"), entry],
                     NVIDIA_RETAINED + ["fish-kde-nvidia-latest-arm64.iso", "fish-kde-nvidia-1-aarch64.iso"])
    config["variants"][0]["platforms"] = ["linux/amd64", "linux/arm64"]
    with pytest.raises(MOD.PolicyError, match=message):
        MOD.active_targets(config, receipts_dir=tmp_path)


def test_inheriting_from_a_sibling_that_is_not_cut_over_is_refused(tmp_path):
    config = _config([_inherits()])
    with pytest.raises(MOD.PolicyError, match="has no receipt-backed cutover target"):
        MOD.active_targets(config, receipts_dir=tmp_path)


def test_an_inheriting_entry_cannot_inherit_from_another_inheriting_entry(tmp_path):
    entry = _inherits(flavor="kde-nvidia-hwe", inherits="kde-nvidia")
    config = _config([H._target(tmp_path, "kde"), _inherits(), entry])
    config["variants"][0]["flavors"].append({"id": "kde-nvidia-hwe", "build_image": True, "build_iso": False})
    with pytest.raises(MOD.PolicyError, match="must inherit 'kde-hwe'"):
        MOD.active_targets(config, receipts_dir=tmp_path)


def test_the_inheriting_target_still_retains_its_native_isos(tmp_path):
    """Retention is the rollback rule; inheritance does not waive it."""
    config = _config([H._target(tmp_path, "kde"), _inherits()], H.KDE_RETAINED)
    with pytest.raises(MOD.PolicyError, match="does not retain"):
        MOD.active_targets(config, receipts_dir=tmp_path)


def test_the_config_parser_accepts_exactly_one_of_evidence_or_inherits():
    sys_path = str(Path(__file__).resolve().parents[1] / "scripts")
    import sys
    sys.path.insert(0, sys_path)
    from lib import tunaos_config
    base = {"variant": "skipjack", "flavor": "gnome-nvidia", "platform": "linux/amd64",
            "qualification": "browser-qualified", "qualified_at": "2026-11-12"}
    for entry, ok in ((dict(base, inherits="gnome"), True),
                      (dict(base, evidence="sha256:" + "a" * 64), True),
                      (dict(base), False),
                      (dict(base, inherits="gnome", evidence="sha256:" + "a" * 64), False)):
        config = tunaos_config.load()
        config["iso_delivery"] = {"cutover_targets": [entry], "retained_r2_isos": []}
        if ok:
            tunaos_config.validate(config)
        else:
            with pytest.raises(tunaos_config.ConfigError, match="exactly one of evidence or inherits"):
                tunaos_config.validate(config)
