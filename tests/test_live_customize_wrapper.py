"""The ISO customization wrapper must run a non-executable copied script.

PR #3407 failed in ISO run 39096138132 with exit 126 because cp -a and mv
preserve customize-live.sh's 0644 mode. Exercise the generated wrapper, not
just its source text, with the same mode and a path containing spaces.
"""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _published_target(variant, flavor):
    result = subprocess.run(
        ["bash", "scripts/published-image-ref.sh", variant, flavor, "ghcr"],
        cwd=ROOT,
        env=os.environ | {"GITHUB_REPOSITORY_OWNER": "tuna-os"},
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _fetch_stubs(tmp_path):
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    fetch_log = tmp_path / "fetch-attempts"
    for command in ("flatpak", "curl", "wget", "dnf", "apt-get", "pacman", "zypper", "sudo", "podman"):
        stub = stub_dir / command
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >>"$FETCH_LOG"\nexit 97\n')
        stub.chmod(0o755)
    (stub_dir / "systemctl").write_text("#!/bin/sh\nexit 0\n")
    (stub_dir / "systemctl").chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(stub_dir) + os.pathsep + env["PATH"]
    env["FETCH_LOG"] = str(fetch_log)
    for key in ("TUNA_INSTALLER_APP", "TUNA_INSTALLER_REVISION", "TUNA_INSTALLER_BUNDLE_SHA256"):
        env.pop(key, None)
    return env, fetch_log


def _generate_customizer_wrapper(directory, session_root, env, *, variant, flavor, digest, payload_ref, candidate="0"):
    shutil.copytree(ROOT / "live-iso/common/src", directory)
    real = directory / "customize-live-real.sh"
    os.replace(directory / "customize-live.sh", real)
    real.chmod(0o755)
    source = (ROOT / "scripts/build-iso-tacklebox.sh").read_text()
    start = source.index("{\n\techo '#!/usr/bin/env bash'", source.index("CUSTOMIZE_DIR="))
    end = source.index('\nif [[ "$DEV"', start)
    env.update(
        {
            "CUSTOMIZE_DIR": str(directory),
            "TUNA_SESSION_ROOT": str(session_root),
            "TUNA_LIVE_OVERLAY_REF": "ghcr.io/tuna-os/live-overlay:test",
            "TUNA_LIVE_PAYLOAD_REF": payload_ref,
            "TUNA_LIVE_OVERLAY_DIGEST": "sha256:" + "b" * 64,
            "TUNA_LIVE_ENGINE_DIGEST": "sha256:" + "c" * 64,
            "TUNAOS_XFCE_CANDIDATE": candidate,
            "VARIANT": variant,
            "FLAVOR": flavor,
            "BASE_IMAGE": f"ghcr.io/tuna-os/{variant}:{flavor}",
            "BASE_DIGEST": digest,
            "SOURCE_PLATFORM": "linux/amd64",
            "PLATFORM": "linux/amd64",
        }
    )
    subprocess.run(["bash", "-euc", source[start:end]], cwd=ROOT, env=env, check=True)
    return directory / "customize-live.sh"


def test_wrapper_runs_nonexecutable_customizer_and_forwards_arguments(tmp_path):
    source = (ROOT / "scripts/build-iso-tacklebox.sh").read_text()
    start = source.index("{\n\techo '#!/usr/bin/env bash'", source.index('CUSTOMIZE_DIR='))
    end = source.index('\nif [[ "$DEV"', start)
    directory = tmp_path / "customize dir"
    directory.mkdir()
    real = directory / "customize-live-real.sh"
    real.write_text(
        'printf "%s\\n" "$TUNA_SESSION_ROOT" "$TUNA_LIVE_BASE_IMAGE" "$TUNA_LIVE_BASE_DIGEST" "$TUNA_LIVE_PLATFORM" "${TUNA_METADATA_ONLY:-unset}" "$@"\n'
        "exit 17\n"
    )
    real.chmod(0o644)
    env = os.environ | {
        "CUSTOMIZE_DIR": str(directory),
        "BASE_IMAGE": "ghcr.io/tuna-os/yellowfin:kde",
        "BASE_DIGEST": "sha256:" + "a" * 64,
        "SOURCE_PLATFORM": "linux/amd64",
        "PLATFORM": "",
        "TUNA_SESSION_ROOT": "/",
        "TUNA_LIVE_OVERLAY_REF": "",
        "TUNA_METADATA_ONLY": "1",
    }
    env.pop("TUNA_LIVE_PAYLOAD_REF", None)
    subprocess.run(["bash", "-euc", source[start:end]], env=env, check=True)
    result = subprocess.run([str(directory / "customize-live.sh"), "argument with spaces"], text=True, capture_output=True)
    assert result.returncode == 17, result.stderr
    assert result.stdout.splitlines() == ["/", env["BASE_IMAGE"], env["BASE_DIGEST"], env["SOURCE_PLATFORM"], "unset", "argument with spaces"]


def test_overlay_wrapper_preserves_receipt_and_stages_final_media(tmp_path):
    env, fetch_log = _fetch_stubs(tmp_path)
    variant, flavor = "yellowfin", "kde"
    digest = "sha256:" + "a" * 64
    target = _published_target(variant, flavor)
    payload_ref = f"{target}@{digest}"
    session_root = tmp_path / "session root"
    receipt = session_root / "etc/tunaos/live-installer-info"
    receipt.parent.mkdir(parents=True)
    original_receipt = (
        "# existing installer identity\n"
        "INSTALLER_APP=org.bootcinstaller.Installer\n"
        f"INSTALLER_REVISION={'d' * 64}\n"
        "INSTALLER_BUNDLE_SHA256=remote\n"
    ).encode()
    receipt.write_bytes(original_receipt)
    recipe = session_root / "etc/bootc-installer/recipe.json"
    recipe.parent.mkdir(parents=True)
    recipe.write_text(json.dumps({"imgref": "tunaos:latest", "local_imgref": ""}))
    sshd = session_root / "usr/lib/systemd/system/sshd.service"
    sshd.parent.mkdir(parents=True)
    sshd.write_text("[Service]\n")

    wrapper = _generate_customizer_wrapper(
        tmp_path / "customize dir",
        session_root,
        env,
        variant=variant,
        flavor=flavor,
        digest=digest,
        payload_ref=payload_ref,
    )
    (wrapper.parent / ".enable-sshd").touch()
    result = subprocess.run([str(wrapper)], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr

    assert receipt.read_bytes() == original_receipt
    source = json.loads((receipt.parent / "live-source.json").read_text())
    assert source["base_digest"] == digest
    assert source["overlay_digest"] == "sha256:" + "b" * 64
    assert source["engine_digest"] == "sha256:" + "c" * 64
    assert source["installer_app_id"] == "org.bootcinstaller.Installer"
    bound_recipe = json.loads(recipe.read_text())
    assert bound_recipe["imgref"] == target
    assert bound_recipe["local_imgref"] == f"containers-storage:{payload_ref}"
    assert (session_root / "etc/ssh/sshd_config.d/90-tunaos-live-e2e.conf").is_file()
    assert (session_root / "usr/lib/systemd/system/tunaos-live-ssh-credentials.service").is_file()
    assert (session_root / "usr/libexec/tunaos-live-debug").is_file()
    assert (session_root / "usr/lib/systemd/system/tunaos-live-debug.timer").is_file()
    assert (session_root / "etc/sudoers.d/90-tunaos-live-e2e").is_file()
    assert not fetch_log.exists()

    receipt.unlink()
    missing = subprocess.run([str(wrapper)], cwd=ROOT, env=env, text=True, capture_output=True)
    assert missing.returncode != 0
    assert "INSTALLER_APP" in missing.stderr
    receipt.write_text(
        "INSTALLER_APP=org.bootcinstaller.Installer\n"
        "INSTALLER_REVISION=unknown\n"
        "INSTALLER_BUNDLE_SHA256=remote\n"
    )
    unknown = subprocess.run([str(wrapper)], cwd=ROOT, env=env, text=True, capture_output=True)
    assert unknown.returncode != 0
    assert "INSTALLER_REVISION" in unknown.stderr
    assert not fetch_log.exists()


def _write_oci_blob(layout, data):
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    blob = layout / "blobs/sha256" / digest.removeprefix("sha256:")
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(data)
    return {"digest": digest, "size": len(data)}


def _write_minimal_oci_layout(layout):
    layout.mkdir(parents=True)
    (layout / "oci-layout").write_text(json.dumps({"imageLayoutVersion": "1.0.0"}))
    config = _write_oci_blob(layout, json.dumps({"architecture": "amd64", "os": "linux"}).encode())
    layer = _write_oci_blob(layout, b"candidate layer")
    manifest_data = json.dumps(
        {"schemaVersion": 2, "config": config, "layers": [layer]}
    ).encode()
    manifest = _write_oci_blob(layout, manifest_data)
    (layout / "index.json").write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "manifests": [
                    {
                        **manifest,
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    }
                ],
            }
        )
    )
    return manifest["digest"]


def test_overlay_wrapper_stages_xfce_candidate_payload(tmp_path):
    env, fetch_log = _fetch_stubs(tmp_path)
    variant, flavor = "bonito", "xfce"
    target = _published_target(variant, flavor)
    session_root = tmp_path / "xfce session root"
    receipt = session_root / "etc/tunaos/live-installer-info"
    receipt.parent.mkdir(parents=True)
    original_receipt = (
        "INSTALLER_APP=org.tunaos.InstallerXfce\n"
        f"INSTALLER_REVISION={'e' * 64}\n"
        "INSTALLER_BUNDLE_SHA256=remote\n"
    )
    receipt.write_text(original_receipt)

    fixture = tmp_path / "candidate fixture"
    digest = _write_minimal_oci_layout(fixture)
    wrapper = _generate_customizer_wrapper(
        tmp_path / "xfce customize dir",
        session_root,
        env,
        variant=variant,
        flavor=flavor,
        digest=digest,
        payload_ref=f"{target}@{digest}",
        candidate="1",
    )
    shutil.copytree(fixture, wrapper.parent / "xfce-candidate-oci")
    result = subprocess.run([str(wrapper)], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr

    staged = session_root / "usr/lib/tunaos/xfce-candidate-oci"
    assert (staged / "index.json").is_file()
    media_input = json.loads((session_root / "etc/bootc-installer/media-input.json").read_text())
    assert media_input["image"] == target
    assert media_input["platformManifestDigest"] == digest
    assert receipt.read_text() == original_receipt
    assert not fetch_log.exists()


def test_overlay_staging_tags_are_unique_per_run_and_attempt():
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/live-overlay.yml").read_text())
    step = next(step for job in workflow["jobs"].values() for step in job.get("steps", []) if step.get("name") == "Run live customize and publish overlay")
    assert step["run"].count("--retry 5") >= 2
    assert "--retry-max-time 60" in step["run"]
    assignment = next(line.strip() for line in step["run"].splitlines() if line.strip().startswith('OUT='))
    tags = set()
    for run, attempt in [("123", "1"), ("124", "1"), ("123", "2")]:
        env = os.environ | {"VARIANT": "yellowfin", "FLAVOR": "kde", "SAFEPLATFORM": "linux-amd64", "PUBLISH_DEST": "ghcr.io/tuna-os", "GITHUB_RUN_ID": run, "GITHUB_RUN_ATTEMPT": attempt}
        result = subprocess.run(["bash", "-euc", assignment + '\nprintf "%s" "$OUT"'], env=env, text=True, capture_output=True, check=True)
        tags.add(result.stdout)
    assert len(tags) == 3
    assert all(tag.startswith("ghcr.io/tuna-os/live-overlay:yellowfin-kde-linux-amd64-") for tag in tags)
