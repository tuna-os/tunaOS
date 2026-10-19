#!/usr/bin/env python3
"""Explicit local-only real-image canary. Does not enable production fork builds."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
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


def install_target_observer(context):
    """Add read-only serial proof only to an admitted local canary context."""
    if not IDENTITY.qualification(context / "manifests/fork-identity.json"):
        raise ValueError("target observer requires exact qualification authority")
    source = ROOT / "scripts/fork-install-observer.py"
    destination = context / "system_files/usr/libexec/tunaos/fork-install-observer.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    destination.chmod(0o755)
    units = context / "system_files/usr/lib/systemd/system"
    units.mkdir(parents=True, exist_ok=True)
    unit = units / "fork-install-observer.service"
    unit.write_text("[Unit]\nDescription=Read-only disposable installation proof\nAfter=multi-user.target\n"
                    "[Service]\nType=simple\nExecStart=/usr/bin/python3 /usr/libexec/tunaos/fork-install-observer.py --duration 3600\n"
                    "RuntimeMaxSec=3610\nTimeoutStopSec=10\nStandardOutput=null\nStandardError=null\n")
    wants = units / "multi-user.target.wants"
    wants.mkdir(exist_ok=True)
    (wants / unit.name).symlink_to("../" + unit.name)
    return {"scope": "qualification-only-read-only-serial", "maximum_seconds": 3600,
            "observer_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "unit_sha256": hashlib.sha256(unit.read_bytes()).hexdigest()}


def assess_serial(serial):
    """Read independent guest verdicts; readiness alone qualifies none of them."""
    checks = re.findall(r"TUNAOS_INSTALL_CHECKS_RESULT pass=(\d+) fail=(\d+) desktop=gnome", serial)
    return {
        "installed_identity": "passed" if re.search(r"(?m)^(?:(?:[A-Za-z0-9_.-]+ login: )|(?:\[[^\]\r\n]+\] [^\r\n:]+: ))?TUNAOS_FORK_IDENTITY_OK(?:\s|$)", serial)
        and "TUNAOS_FORK_IDENTITY_FAIL" not in serial else "failed",
        "base_contract": "passed" if re.search(r"(?m)^(?:(?:[A-Za-z0-9_.-]+ login: )|(?:\[[^\]\r\n]+\] [^\r\n:]+: ))?TUNAOS_BASE_CONTRACT_OK(?:\s|$)", serial)
        and "TUNAOS_BASE_CONTRACT_FAIL" not in serial else "failed",
        "installed_checks": "passed" if checks and all(int(fail) == 0 and int(passed) > 0
                                                       for passed, fail in checks) else "failed",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-build-entry", action="store_true")
    parser.add_argument("--installed-proof-observer", action="store_true")
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
              "accelerator": "kvm" if Path("/dev/kvm").exists() else "tcg",
              "build": "not-run", "image_identity": "not-run", "boot": "not-run",
              "base_contract": "not-run", "installed_checks": "not-run", "source_export": "not-run",
              "installed_identity": "not-run", "wallpaper_defaults": "not-run",
              "initramfs_theme": "not-run", "wallpaper_render": "not-run", "greeter_profile": "not-run", "greeter_render": "not-run", "login": "not-run", "installer_ui": "not-run"}
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
        if args.installed_proof_observer:
            report["target_observer"] = install_target_observer(context)
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
                        '[Service]\nType=oneshot\nExecStart=/bin/sh -c "exec >/dev/ttyS0 2>&1; python3 /usr/libexec/tunaos/fork-identity.py / '
                        '&& echo TUNAOS_FORK_IDENTITY_OK || { echo TUNAOS_FORK_IDENTITY_FAIL; exit 1; }"\n'
                        'StandardOutput=journal+console\nStandardError=journal+console\n')
        wants = units / "multi-user.target.wants"
        wants.mkdir(exist_ok=True)
        (wants / unit.name).symlink_to("../" + unit.name)
        report["guest_probe_sha256"] = hashlib.sha256(unit.read_bytes()).hexdigest()
        diagnostic = context / "system_files/usr/libexec/tunaos/fork-greeter-diagnostics"
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        diagnostic.write_text("""#!/bin/bash
exec >/dev/ttyS0 2>&1
echo TUNAOS_FORK_GREETER_DIAGNOSTICS_BEGIN
for f in /etc/dconf/profile/gdm /usr/share/dconf/profile/gdm /etc/dconf/db/gdm.d/*; do
    echo "=== $f"
    test ! -f "$f" || cat "$f"
done
DCONF_PROFILE=gdm gsettings get org.gnome.login-screen logo
for attempt in {1..30}; do
    found=0
    for user in gdm Debian-gdm; do
        uid=$(id -u "$user" 2>/dev/null) || continue
        for pid in $(pgrep -u "$uid" gnome-shell); do
            echo "greeter user=$user pid=$pid"
            tr '\\0' '\\n' <"/proc/$pid/environ" | grep '^DCONF_PROFILE=' || true
            found=1
        done
    done
    test "$found" = 0 || break
    sleep 1
done
systemctl show ssh.service ssh.socket sshd-keygen.service --property=LoadState,ActiveState,SubState,Result,After,Wants,Requires || true
journalctl -b -u sshd-keygen.service -u ssh.service --no-pager -n 60 || true
echo TUNAOS_FORK_GREETER_DIAGNOSTICS_END
""")
        diagnostic.chmod(0o755)
        diagnostic_unit = units / "fork-greeter-diagnostics.service"
        diagnostic_unit.write_text('[Unit]\nDescription=Record greeter qualification diagnostics\nAfter=display-manager.service\n'
                                   '[Service]\nType=oneshot\nExecStart=/usr/libexec/tunaos/fork-greeter-diagnostics\nTimeoutStartSec=45\n')
        (wants / diagnostic_unit.name).symlink_to("../" + diagnostic_unit.name)
        report["greeter_probe_sha256"] = hashlib.sha256(diagnostic.read_bytes()).hexdigest()
        report["greeter_unit_sha256"] = hashlib.sha256(diagnostic_unit.read_bytes()).hexdigest()
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
        report["initramfs_theme"] = "running"
        with (out / "initramfs.json").open("w") as payload, (out / "initramfs-diagnostics.txt").open("w") as diagnostics:
            subprocess.run(["podman", "run", "--rm", "--pull=never", "--entrypoint", "python3",
                            "--volume", str(ROOT / "scripts/qualify-fork-initramfs.py") + ":/probe.py:ro",
                            image, "/probe.py"], text=True, stdout=payload, stderr=diagnostics, check=True)
        report["initramfs_theme"] = "passed"
        report["greeter_profile"] = "running"
        greeter = subprocess.check_output(["podman", "run", "--rm", "--pull=never", "--entrypoint", "bash", image,
                                          "-c", 'for f in /etc/dconf/profile/gdm /usr/share/dconf/profile/gdm /etc/dconf/db/gdm.d/*; '
                                          'do echo "=== $f"; test ! -f "$f" || cat "$f"; done; '
                                          'DCONF_PROFILE=gdm gsettings get org.gnome.login-screen logo'], text=True)
        (out / "greeter-config.txt").write_text(greeter)
        if not greeter.splitlines() or greeter.splitlines()[-1] != "\'/usr/share/pixmaps/tunaos-lettermark.svg\'":
            raise ValueError("effective GDM profile does not select the supplied lettermark")
        report["greeter_profile"] = "passed"
        probe = ('source /usr/libexec/tunaos/fork-branding.sh; tunaos_verify_fork_branding /; '
                 'for key in picture-uri picture-uri-dark; do '
                 'test "$(GSETTINGS_BACKEND=memory gsettings get org.gnome.desktop.background "$key")" '
                 ' = "\'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg\'" || exit 1; done')
        subprocess.run(["podman", "run", "--rm", "--pull=never", "--entrypoint", "bash", image,
                        "-ec", probe], check=True)
        report["wallpaper_defaults"] = "passed"
        report["boot"] = "running"
        subprocess.run(["bash", str(ROOT / "scripts/corral-boot-gate.sh"), image, str(out / "boot"), "900"],
                       env={**os.environ, "TUNAOS_FORK_CANARY_SSH": "1"}, check=True)
        report["boot"] = "passed"
        serial = (out / "boot/serial.log").read_text()
        guest = assess_serial(serial)
        report.update(guest)
        failed = [stage for stage, status in guest.items() if status != "passed"]
        if failed:
            raise ValueError("guest qualification failed: " + ", ".join(failed))
        # Bind the finalized original image to local-only installer media.
        # Keep the OCI layers on the runner; upload only the external receipt.
        report["source_export"] = "running"
        exporter = module("fork_source_export", ROOT / "scripts/export-fork-source.py")
        report["exported_source"] = exporter.export(context / "manifests/fork-config.json", out / "oci-export")
        if report["exported_source"]["source_image_id"].removeprefix("sha256:") != report["image_id"].removeprefix("sha256:"):
            raise ValueError("exported installer source differs from the qualified original image")
        report["source_export"] = "passed"
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
