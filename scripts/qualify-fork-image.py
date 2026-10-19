#!/usr/bin/env python3
"""Explicit local-only real-image canary. Does not enable production fork builds."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


IDENTITY = module("identity", ROOT / "build_scripts/lib/fork-identity.py")


def validate_entry(context, env):
    manifest = context / "manifests/fork-identity.json"
    if not IDENTITY.qualification(manifest):
        raise ValueError("identity staging is not a qualification context")
    m = IDENTITY.load(manifest)
    required = {"VARIANT": m["variant"], "PLATFORM": "linux/amd64", "DESKTOP_FLAVOR": "gnome",
                "TUNAOS_IMAGE_FLAVOR": "gnome", "IMAGE_REGISTRY": "localhost",
                "REPO_ORGANIZATION": "fork-qualification", "PUBLIC_IMAGE_NAME": m["variant"],
                "IMAGE_TAG": f"localhost/fork-qualification/{m['variant']}:gnome-linux-amd64",
                "CONTAINERFILE": "Containerfile.el10" if m["variant"] == "yellowfin" else "Containerfile.ubuntu",
                "SKIP_RECHUNK": "1", "IS_CI": "0", "USE_CACHE": "0",
                "ENABLE_HWE": "0", "ENABLE_NVIDIA": "0", "ENABLE_ASAHI": "0", "ENABLE_SSHD": "0"}
    if any(env.get(key) != value for key, value in required.items()):
        raise ValueError("qualification build environment differs from admitted local canary")
    for key in ("BUILDAH_CACHE_FLAGS", "OVERLAY_TYPE", "TUNAOS_BUILD_CONFIG"):
        if env.get(key):
            raise ValueError(f"qualification forbids {key}")


def authorize(context):
    manifests = context / "manifests"
    receipt = {"schema_version": 1, "purpose": "nonpublishing-canary"}
    for key, name in (("identity", "fork-identity.json"), ("config", "fork-config.json")):
        receipt[key + "_sha256"] = hashlib.sha256((manifests / name).read_bytes()).hexdigest()
    (manifests / "fork-qualification.json").write_text(json.dumps(receipt, indent=2) + "\n")
    IDENTITY.qualification(manifests / "fork-identity.json")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-build-entry", action="store_true")
    parser.add_argument("--variant", choices=("yellowfin", "grouper"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.validate_build_entry:
        validate_entry(Path.cwd(), os.environ)
        return
    if not args.variant or not args.output:
        parser.error("--variant and --output are required")
    if args.output.exists():
        raise ValueError("qualification output must not already exist")
    args.output.mkdir(parents=True)
    out = args.output.resolve()
    report = {"variant": args.variant, "platform": "linux/amd64", "publishing": False,
              "build": "not-run", "image_identity": "not-run", "boot": "not-run",
              "installed_identity": "not-run", "wallpaper_defaults": "not-run",
              "initramfs_theme": "not-run", "wallpaper_render": "not-run", "login": "not-run", "installer_ui": "not-run"}
    try:
        import yaml
        from PIL import Image
        prepare = module("prepare", ROOT / "scripts/prepare-fork-config.py")
        Image.new("RGB", (128, 128), "#eb922d").save(out / "logo.png")
        Image.new("RGB", (1920, 1080), "#12394b").save(out / "wallpaper.jpg")
        source = prepare.COMPILER.source_receipt(ROOT)
        config = {"schema_version": 1, "catalog": {"sha256": source["sha256"]},
                  "image": {"registry": "localhost", "namespace": "fork-qualification"},
                  "targets": {"variants": [args.variant], "flavors": ["gnome"], "platforms": ["linux/amd64"]},
                  "global": {"branding": {"name": "Harbor Canary", "logo": "logo.png", "wallpaper": "wallpaper.jpg",
                                            "homepage": "https://example.org/harbor"}}}
        config_path = out / "fork.yaml"
        config_path.write_text(yaml.safe_dump(config))
        builds = prepare.prepare(config_path, out / "prepared", identity_staging=True)
        if len(builds) != 1:
            raise ValueError("qualification requires exactly one canary")
        build = builds[0]
        context = out / "prepared" / build["context"]
        report["authority"] = authorize(context)
        env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "LANG": "C.UTF-8", **build["environment"]}
        validate_entry(context, env)
        report["source"] = source
        report["base_image"] = env["BASE_IMAGE"]
        report["base_digest_pinned"] = build["base_digest_pinned"]
        image = env["IMAGE_TAG"]
        report["image"] = image
        # The guest verifies receipt hashes against the installed filesystem before
        # display-manager starts. This is independent of desktop readiness/login.
        units = context / "system_files/usr/lib/systemd/system"
        units.mkdir(parents=True, exist_ok=True)
        unit = units / "fork-qualification.service"
        unit.write_text('[Unit]\nDescription=Verify installed fork qualification receipt\nBefore=display-manager.service\n'
                        '[Service]\nType=oneshot\nExecStart=/bin/sh -c "python3 /usr/libexec/tunaos/fork-identity.py / '
                        '&& echo TUNAOS_FORK_IDENTITY_OK || { echo TUNAOS_FORK_IDENTITY_FAIL; exit 1; }"\n'
                        'StandardOutput=journal+console\nStandardError=journal+console\n')
        wants = units / "multi-user.target.wants"
        wants.mkdir(exist_ok=True)
        (wants / unit.name).symlink_to("../" + unit.name)
        report["guest_probe_sha256"] = hashlib.sha256(unit.read_bytes()).hexdigest()
        report["build"] = "running"
        subprocess.run(["bash", "scripts/build-image-inner.sh"], cwd=context, env=env, check=True)
        report["build"] = "passed"
        inspect = subprocess.check_output(["podman", "image", "inspect", image], text=True)
        (out / "image-inspect.json").write_text(inspect)
        report["image_id"] = json.loads(inspect)[0]["Id"]
        report["image_digest"] = json.loads(inspect)[0].get("Digest", "")
        subprocess.run(["podman", "run", "--rm", "--pull=never", "--entrypoint", "python3", image,
                        "/usr/libexec/tunaos/fork-identity.py", "/"], check=True)
        report["image_identity"] = "passed"
        probe = ('source /usr/libexec/tunaos/fork-branding.sh; tunaos_verify_fork_branding /; '
                 'for key in picture-uri picture-uri-dark; do '
                 'test "$(GSETTINGS_BACKEND=memory gsettings get org.gnome.desktop.background "$key")" '
                 ' = "\'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg\'" || exit 1; done')
        subprocess.run(["podman", "run", "--rm", "--pull=never", "--entrypoint", "bash", image,
                        "-ec", probe], check=True)
        report["wallpaper_defaults"] = "passed"
        report["boot"] = "running"
        subprocess.run(["bash", str(ROOT / "scripts/corral-boot-gate.sh"), image, str(out / "boot"), "900"], check=True)
        report["boot"] = "passed"
        serial = (out / "boot/serial.log").read_text()
        if "TUNAOS_FORK_IDENTITY_OK" not in serial or "TUNAOS_FORK_IDENTITY_FAIL" in serial:
            raise ValueError("installed identity probe did not pass on guest serial")
        report["installed_identity"] = "passed"
    finally:
        for stage, status in list(report.items()):
            if status == "running":
                report[stage] = "failed"
        if sys.exc_info()[0] is not None:
            report["error"] = str(sys.exc_info()[1])[:1000]
        # Never turn an unexecuted UI/login assertion into a green result.
        (out / "qualification.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: fork qualification: {exc}", file=sys.stderr)
        sys.exit(2)
