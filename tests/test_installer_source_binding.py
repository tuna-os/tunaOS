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
    assignment = next(line for line in source.splitlines() if line.startswith('PAYLOAD_REF='))
    resolved = subprocess.run(['bash', '-eu', '-c',
        'tunaos_image_ref() { echo unexpected-resolver >&2; return 99; }; '
        + assignment + '; printf "%s" "$PAYLOAD_REF"'],
        env={'TUNA_LIVE_PAYLOAD_REF': payload}, text=True, capture_output=True, timeout=5)
    assert resolved.returncode == 0 and resolved.stdout == payload
    assert 'unexpected-resolver' not in resolved.stderr
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
    block = source.split('if [[ -n "${TUNA_LIVE_PAYLOAD_REF+x}"', 1)[1].split('\nfi', 1)[0]
    script = 'if [[ -n "${TUNA_LIVE_PAYLOAD_REF+x}"' + block + '\nfi'
    result = subprocess.run(["bash", "-e", "-c", script], env={
        "PATH": "/usr/bin:/bin", "SCRIPT_DIR": str(SCRIPT.parent),
        "RECIPE_FILE": str(path), "TUNA_LIVE_PAYLOAD_REF": payload,
        "TUNA_LIVE_BASE_DIGEST": DIGEST, "TUNA_LIVE_INSTALL_TARGET": TARGET,
        "TUNAOS_XFCE_CANDIDATE": "0",
    }, text=True, capture_output=True)
    assert result.returncode == expected_rc
    actual = json.loads(path.read_text())
    assert actual["local_imgref"] == ("containers-storage:" + PAYLOAD if not expected_rc else "stale")

@pytest.mark.parametrize("repo", ["local", "ghcr"])
@pytest.mark.parametrize("exact_payload", [False, True])
def test_iso_source_override_cannot_replace_canonical_payload_destination(tmp_path, repo, exact_payload):
    """#3431 r4372453161; preserve #3427's tracking/payload separation."""
    adapter = (ROOT / "scripts/build-iso-tacklebox.sh").read_text()
    assignments = "\n".join(
        line for line in adapter.splitlines()
        if line.startswith(("SOURCE_IMAGE_REF=", "PAYLOAD_REF="))
    )
    # Execute the real recipe writer, not a second hand-written recipe.
    recipe_writer = 'cat >"$RECIPE_FILE" <<EOF' + adapter.split(
        'cat >"$RECIPE_FILE" <<EOF', 1
    )[1].split('\nEOF', 1)[0] + '\nEOF\n'
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"variants": [{"id": "bonito-rawhide", "publish_name": "bonito", "tag_suffix": "rawhide"}]}))
    canonical = "registry.example:5000/acme/team/bonito:gnome-rawhide-linux-amd64"
    tracking = "registry.example:5000/acme/team/bonito:gnome-rawhide"
    override = "registry.example:5000/staging/test:source@" + DIGEST
    payload = canonical + "@" + DIGEST if exact_payload else canonical
    env = dict(os.environ, TUNAOS_BUILD_CONFIG=str(config),
               IMAGE_REGISTRY="registry.example:5000", REPO_ORGANIZATION="acme/team",
               TUNAOS_IMAGE_REF=override, VARIANT="bonito-rawhide", FLAVOR="gnome",
               TAG="gnome-rawhide-linux-amd64", REPO=repo,
               RECIPE_FILE=str(tmp_path / "recipe.json"), MEDIA_NAME="fixture",
               DESKTOP="gnome", CUSTOMIZE_DIR=str(tmp_path))
    env.pop("TUNA_LIVE_PAYLOAD_REF", None)
    if exact_payload:
        env["TUNA_LIVE_PAYLOAD_REF"] = payload
    result = subprocess.run(["bash", "-eu", "-c",
        'source scripts/lib/image.sh\n' + assignments +
        '\nIMAGE_REF=$SOURCE_IMAGE_REF\n' + recipe_writer +
        '\nbash scripts/published-image-ref.sh "$VARIANT" "$FLAVOR" ghcr'],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == tracking
    source = override if repo == "ghcr" else "localhost/bonito-rawhide:gnome-rawhide-linux-amd64"
    recipe = json.loads((tmp_path / "recipe.json").read_text())
    assert recipe["offline_payloads"] == [{"source": source, "ref": payload}]
    assert recipe["bootable_environments"][0]["image"] == source


@pytest.mark.parametrize('destination', ['ghcr.io/tuna-os', 'quay.io/review-fixture', 'registry.example:5000/acme/team',
    'localhost:5000/dev', 'registry.gitlab.com/group/sub-group/os', 'ghcr.io/my_org'])
@pytest.mark.parametrize('flavor', ['gnome', 'xfce'])
def test_configured_destination_reaches_actual_customization_binding(tmp_path, destination, flavor):
    """#3431 r4383963978: resolver output must survive the last writer."""
    registry, namespace = destination.split('/', 1)
    env = dict(os.environ, IMAGE_REGISTRY=registry, REPO_ORGANIZATION=namespace)
    result = subprocess.run(['bash', 'scripts/published-image-ref.sh', 'bonito', flavor, 'ghcr'],
                            cwd=ROOT, env=env, text=True, capture_output=True, check=True)
    target = result.stdout.strip()
    assert target == destination + '/bonito:' + flavor
    path = tmp_path / 'recipe.json'
    path.write_text('{"keep":"value"}')
    source = (ROOT / 'live-iso/common/src/customize-live.sh').read_text()
    block = source.split('if [[ -n "${TUNA_LIVE_PAYLOAD_REF+x}"', 1)[1].split('\nfi', 1)[0]
    script = 'if [[ -n "${TUNA_LIVE_PAYLOAD_REF+x}"' + block + '\nfi'
    candidate = '1' if flavor == 'xfce' else '0'
    run = subprocess.run(['bash', '-eu', '-c', script], env=dict(env,
        SCRIPT_DIR=str(SCRIPT.parent), RECIPE_FILE=str(path),
        TUNAOS_XFCE_CANDIDATE=candidate,
        TUNA_LIVE_PAYLOAD_REF=target + '@' + DIGEST, TUNA_LIVE_BASE_DIGEST=DIGEST,
        TUNA_LIVE_INSTALL_TARGET=target), text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    if flavor == 'xfce':
        # XFCE candidate skips GNOME recipe binding!
        assert json.loads(path.read_text()) == {'keep': 'value'}
    else:
        assert json.loads(path.read_text()) == dict(keep='value', imgref=target,
            local_imgref='containers-storage:' + target + '@' + DIGEST)
@pytest.mark.parametrize('target', ['https://quay.io/a/bonito:gnome', 'quay.io/a/../bonito:gnome',
    'quay.io/a/bonito:gnome\n', 'quay.io/a/bonito:gnome;false', 'quay.io/a/bonito',
    'quay.io/a/bonito:gnome@'+DIGEST])
def test_configured_binding_rejects_malformed_targets_before_writing(tmp_path, target):
    path = tmp_path/'recipe.json'
    path.write_text('{}')
    with pytest.raises(ValueError):
        BINDING.bind_recipe(path, target+'@'+DIGEST, DIGEST, target)
    assert path.read_text() == '{}'
