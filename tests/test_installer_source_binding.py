"""The real GUI recipe must name the payload that native media embeds."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "live-iso/common/src/installer-source-binding.py"
SPEC = importlib.util.spec_from_file_location("installer_source_binding", SCRIPT)
BINDING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BINDING)
DIGEST = "sha256:" + "a" * 64
TARGET = "ghcr.io/tuna-os/skipjack:gnome"
PAYLOAD = TARGET + "@" + DIGEST


def test_stock_recipe_binds_exact_payload_without_changing_other_fields(tmp_path):
    recipe = json.loads((ROOT / "system_files/etc/bootc-installer/recipe.json").read_text())
    assert recipe["local_imgref"] == "containers-storage:ghcr.io/tuna-os/tunaos:latest"
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe))
    BINDING.bind_recipe(path, PAYLOAD, DIGEST, TARGET)
    expected = dict(recipe, imgref=TARGET, local_imgref="containers-storage:" + PAYLOAD)
    assert json.loads(path.read_text()) == expected
    BINDING.bind_recipe(path, PAYLOAD, DIGEST, TARGET)
    assert json.loads(path.read_text()) == expected


@pytest.mark.parametrize("payload,digest,target", [
    ("", DIGEST, TARGET),
    (TARGET, DIGEST, TARGET),
    (TARGET + "@sha256:" + "b" * 64, DIGEST, TARGET),
    ("ghcr.io/tuna-os/albacore:gnome@" + DIGEST, DIGEST, TARGET),
    ("containers-storage:" + PAYLOAD, DIGEST, TARGET),
    (PAYLOAD, "unknown", TARGET),
    (PAYLOAD, "sha256:" + "A" * 64, TARGET),
    (PAYLOAD, DIGEST, "localhost/skipjack:gnome"),
    (PAYLOAD, DIGEST, TARGET + "\n"),
])
def test_invalid_binding_leaves_recipe_unchanged(tmp_path, payload, digest, target):
    path = tmp_path / "recipe.json"
    original = '{"imgref":"original","local_imgref":"original"}'
    path.write_text(original)
    with pytest.raises(ValueError):
        BINDING.bind_recipe(path, payload, digest, target)
    assert path.read_text() == original


@pytest.mark.parametrize("kind", ["missing", "symlink", "array", "invalid-json"])
def test_invalid_recipe_fails_closed(tmp_path, kind):
    path = tmp_path / "recipe.json"
    if kind == "symlink":
        target = tmp_path / "target.json"
        target.write_text("{}")
        path.symlink_to(target)
    elif kind != "missing":
        path.write_text("[]" if kind == "array" else "{")
    with pytest.raises(ValueError):
        BINDING.bind_recipe(path, PAYLOAD, DIGEST, TARGET)
    if kind == "symlink":
        assert target.read_text() == "{}"


@pytest.mark.parametrize("variant,target", [
    ("skipjack", TARGET),
    ("bonito-rawhide", "ghcr.io/tuna-os/bonito:gnome-rawhide"),
    ("flounder-sid", "ghcr.io/tuna-os/flounder:gnome-sid"),
])
def test_final_wrapper_passes_exact_payload_and_separate_tracking_target(tmp_path, variant, target):
    payload = target + "@" + DIGEST
    source = (ROOT / "scripts/build-iso-tacklebox.sh").read_text()
    block = source.split('if [[ -n "${TUNA_LIVE_PAYLOAD_REF+x}" ]]; then', 1)[1].split('\n\tfi', 1)[0]
    result = subprocess.run(["bash", "-eu", "-c", block], cwd=ROOT, env={
        "PATH": os.environ["PATH"],
        "TUNA_LIVE_PAYLOAD_REF": payload, "VARIANT": variant, "FLAVOR": "gnome",
    }, text=True, capture_output=True, check=True)
    assert "TUNA_LIVE_PAYLOAD_REF=" + payload in result.stdout
    assert "TUNA_LIVE_INSTALL_TARGET=" + target in result.stdout
    path = tmp_path / "recipe.json"
    path.write_text("{}")
    BINDING.bind_recipe(path, payload, DIGEST, target)
    assert json.loads(path.read_text()) == {"imgref": target, "local_imgref": "containers-storage:" + payload}
    assert '"ref": "${PAYLOAD_REF}"' in source
    assert 'PAYLOAD_REF="${TUNA_LIVE_PAYLOAD_REF:-$SOURCE_IMAGE_REF}"' in source
    customize = (ROOT / "live-iso/common/src/customize-live.sh").read_text()
    assert '"${SCRIPT_DIR}/installer-source-binding.py" "$RECIPE_FILE"' in customize
    assert '"$TUNA_LIVE_PAYLOAD_REF" "${TUNA_LIVE_BASE_DIGEST:-}"' in customize
    workflow = (ROOT / ".github/workflows/live-iso-bootc.yml").read_text()
    resolver = 'install_target="$(GITHUB_REPOSITORY_OWNER=tuna-os bash scripts/published-image-ref.sh "$VARIANT" "$FLAVOR" ghcr)"'
    assert resolver in workflow and resolver in source
    assert 'export TUNA_LIVE_PAYLOAD_REF="${install_target}@${TUNA_LIVE_BASE_DIGEST}"' in workflow
    assert '[[ "$payload_digest" == "$TUNA_LIVE_BASE_DIGEST" ]]' in workflow


@pytest.mark.parametrize("payload,expected_rc", [(PAYLOAD, 0), ("", 1), (TARGET, 1)])
def test_customization_executes_binding_and_propagates_failure(tmp_path, payload, expected_rc):
    path = tmp_path / "recipe.json"
    path.write_text('{"imgref":"stale","local_imgref":"stale"}')
    source = (ROOT / "live-iso/common/src/customize-live.sh").read_text()
    block = source.split('if [[ -n "${TUNA_LIVE_PAYLOAD_REF+x}" ]]; then', 1)[1].split('\nfi', 1)[0]
    result = subprocess.run(["bash", "-e", "-c", block], env={
        "PATH": "/usr/bin:/bin", "SCRIPT_DIR": str(SCRIPT.parent),
        "RECIPE_FILE": str(path), "TUNA_LIVE_PAYLOAD_REF": payload,
        "TUNA_LIVE_BASE_DIGEST": DIGEST, "TUNA_LIVE_INSTALL_TARGET": TARGET,
    }, text=True, capture_output=True)
    assert result.returncode == expected_rc
    actual = json.loads(path.read_text())
    assert actual["local_imgref"] == ("containers-storage:" + PAYLOAD if not expected_rc else "stale")
