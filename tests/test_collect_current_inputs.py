"""Current delivery inputs must fail closed per target, not per catalog."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "collect_current_inputs", ROOT / "scripts/collect-current-inputs.py"
)
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)

DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64


def test_engine_revision_uses_the_downloads_tacklebox_pin():
    versions = yaml.safe_load((ROOT / "image-versions.yaml").read_text(encoding="utf-8"))
    pin = versions["downloads"]["tacklebox"]
    expected = "sha256:" + hashlib.sha256(f"tacklebox:{pin}".encode()).hexdigest()

    assert COLLECTOR._engine_pin() == expected


def test_collection_isolates_missing_images_and_overlays(monkeypatch, capsys):
    config = {
        "config": {"global_platforms": ["linux/amd64"]},
        "variants": [{
            "id": "bonito",
            "platforms": ["linux/amd64"],
            "flavors": [
                {"id": "base", "build_image": True},
                {"id": "gnome", "build_image": True},
                {"id": "kde", "build_image": True},
                {"id": "xfce", "build_image": True},
            ],
        }],
    }

    def image_identity(_config, variant, flavor, platform):
        if flavor == "xfce":
            raise RuntimeError("image unavailable")
        return {
            "variant": variant,
            "flavor": flavor,
            "platform": platform,
            "platformManifestDigest": DIGEST,
        }

    def overlay_identity(variant, flavor, platform, base_digest):
        if flavor == "gnome":
            raise RuntimeError("overlay unavailable")
        assert base_digest == DIGEST
        return {
            "variant": variant,
            "flavor": flavor,
            "platform": platform,
            "liveOverlayDigest": OTHER_DIGEST,
            "liveOverlayBaseDigest": DIGEST,
        }

    monkeypatch.setattr(COLLECTOR, "_image_identity", image_identity)
    monkeypatch.setattr(COLLECTOR, "_overlay_identity", overlay_identity)
    monkeypatch.setattr(COLLECTOR, "_engine_pin", lambda: OTHER_DIGEST)

    current = COLLECTOR.collect(config)["currentInputs"]

    assert set(current["descriptors"]) == {
        "bonito:base:linux/amd64",
        "bonito:gnome:linux/amd64",
        "bonito:kde:linux/amd64",
    }
    assert set(current["overlays"]) == {"bonito:kde:linux/amd64"}
    assert "bonito:base:linux/amd64" not in current["overlays"]
    assert "overlay unavailable" in capsys.readouterr().err


@pytest.mark.parametrize("label", [None, OTHER_DIGEST])
def test_overlay_identity_requires_its_exact_base_digest(monkeypatch, label):
    response = {"Digest": OTHER_DIGEST, "Labels": {}}
    if label is not None:
        response["Labels"]["org.tunaos.live-overlay.base-digest"] = label
    monkeypatch.setattr(COLLECTOR, "_run", lambda *args: json.dumps(response))

    with pytest.raises(RuntimeError, match="base digest"):
        COLLECTOR._overlay_identity("bonito", "gnome", "linux/amd64", DIGEST)
