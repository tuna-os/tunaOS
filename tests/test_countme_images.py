"""Test effective countme output for every declared official matrix cell."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
CELLS = [(v["id"], f["id"]) for v in CONFIG["variants"] for f in v.get("flavors", []) if f.get("build_image", True)]
INHERITED = [f"{name}.{kind}" for name in ("bluefin-countme", "dakota-countme", "bluefin-lts-countme") for kind in ("service", "timer")]


def install(tmp_path, variant="bonito-rawhide", flavor="gnome-nvidia-hwe"):
    context = tmp_path / "context"
    context.mkdir(exist_ok=True)
    if not (context / "files").exists():
        (context / "files").symlink_to(ROOT / "system_files", target_is_directory=True)
    image = tmp_path / "image"
    env = {**os.environ, "TUNAOS_COUNTME_CONTEXT": str(context), "TUNAOS_COUNTME_ROOT": str(image), "IMAGE_NAME_VARIANT": variant, "TUNAOS_IMAGE_FLAVOR": flavor}
    proc = subprocess.run(["bash", str(ROOT / "build_scripts/install-countme.sh")], env=env, capture_output=True, text=True)
    return image, proc


@pytest.mark.parametrize("variant,flavor", CELLS)
def test_every_matrix_identity_survives_effective_installer_output(tmp_path, variant, flavor):
    image, proc = install(tmp_path, variant, flavor)
    assert proc.returncode == 0, proc.stderr
    metadata = json.loads((image / "usr/share/tunaos/countme.json").read_text())
    assert metadata == {"schema": 1, "variant": variant, "flavor": flavor}
    assert (image / "usr/share/tunaos/countme-allowlist.json").read_text() == (ROOT / "services/countme/src/allowlist.json").read_text()
    assert not (image / "var/lib/tunaos-countme").exists()
    assert not (image / "etc/tunaos/countme/enabled").exists()
    assert os.access(image / "usr/libexec/tunaos-countme", os.X_OK)
    for unit in INHERITED:
        mask = image / "usr/lib/systemd/system" / unit
        assert mask.is_symlink() and os.readlink(mask) == "/dev/null"


def test_reasserting_install_masks_upstream_recopies_and_preserves_admin_optout(tmp_path):
    image, proc = install(tmp_path)
    assert proc.returncode == 0, proc.stderr
    disabled = image / "etc/tunaos/countme/disabled"
    disabled.parent.mkdir(parents=True)
    disabled.touch()
    state = image / "var/lib/tunaos-countme/state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"epoch":1704067200,"last_week":2800}')
    for unit in INHERITED:
        mask = image / "usr/lib/systemd/system" / unit
        mask.unlink()
        mask.write_text("[Service]\nExecStart=/usr/bin/upstream-report\n")
        for prefix in ("etc", "usr/lib"):
            link = image / prefix / "systemd/system/timers.target.wants" / unit
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(f"../{unit}")
    image, proc = install(tmp_path, "flounder-sid", "kde-hwe")
    assert proc.returncode == 0, proc.stderr
    assert disabled.exists()
    assert state.read_text() == '{"epoch":1704067200,"last_week":2800}'
    for unit in INHERITED:
        assert os.readlink(image / "usr/lib/systemd/system" / unit) == "/dev/null"
        for prefix in ("etc", "usr/lib"):
            assert not (image / prefix / "systemd/system/timers.target.wants" / unit).is_symlink()
    preset = (image / "usr/lib/systemd/system-preset/00-tunaos-countme.preset").read_text()
    assert "enable tunaos-countme.timer" in preset


@pytest.mark.parametrize("variant,flavor", [("", "gnome"), ("yellowfin", ""), ("yellowfin", "gnome/hostname")])
def test_missing_or_invalid_build_identity_fails_loudly(tmp_path, variant, flavor):
    image, proc = install(tmp_path, variant, flavor)
    assert proc.returncode != 0
    assert "original variant and full flavor are required" in proc.stderr
    assert not (image / "usr/share/tunaos/countme.json").exists()


def test_all_build_families_wire_original_flavor_and_reach_installer():
    for family in ("el10", "arch", "debian", "ubuntu", "opensuse", "gentoo", "overlay"):
        content = (ROOT / f"Containerfile.{family}").read_text()
        assert "ARG TUNAOS_IMAGE_FLAVOR" in content
        assert "ENV TUNAOS_IMAGE_FLAVOR=${TUNAOS_IMAGE_FLAVOR}" in content
        assert "build_scripts/90-image-info.sh" in content
    info = (ROOT / "build_scripts/90-image-info.sh").read_text()
    assert 'IMAGE_NAME_VARIANT="${VARIANT_KEY}" /run/context/build_scripts/install-countme.sh' in info
    build = (ROOT / "scripts/build-image-inner.sh").read_text()
    assert 'TUNAOS_IMAGE_FLAVOR=${TUNAOS_IMAGE_FLAVOR:?' in build


def test_unit_runs_with_persistent_state_and_runtime_consent_conditions():
    unit = (ROOT / "system_files/usr/lib/systemd/system/tunaos-countme.service").read_text()
    for line in ("DynamicUser=yes", "StateDirectory=tunaos-countme", "StateDirectoryMode=0700", "ConditionPathExists=!/etc/tunaos/countme/disabled", "ExecStart=/usr/libexec/tunaos-countme report"):
        assert line in unit
    timer = (ROOT / "system_files/usr/lib/systemd/system/tunaos-countme.timer").read_text()
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=" in timer


def test_collector_categories_are_derived_from_current_matrix_without_drift():
    proc = subprocess.run([os.sys.executable, str(ROOT / "scripts/generate-countme-allowlist.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    categories = json.loads((ROOT / "services/countme/src/allowlist.json").read_text())
    arch_map = {"amd64": "x86_64", "arm64": "aarch64"}
    expected = set()
    for variant in CONFIG["variants"]:
        for flavor in variant["flavors"]:
            if flavor.get("build_image", True) is False:
                continue
            platforms = flavor.get("platforms", variant.get("platforms", CONFIG["config"]["global_platforms"]))
            for platform in platforms:
                expected.add((variant["id"], flavor["id"], arch_map[platform.split("/")[1]]))
    assert {(item["variant"], item["flavor"], item["arch"]) for item in categories} == expected


def test_desktop_install_reassertion_is_reached_and_gentoo_last_copy_is_masked():
    desktop = (ROOT / "build_scripts/desktop/install-desktop.sh").read_text()
    assert '"${_TD_CTX}/build_scripts/install-countme.sh"' in desktop
    assert not re.search(r"^\s*exit\s+0\b", desktop[:desktop.index('"${_TD_CTX}/build_scripts/install-countme.sh"')], re.MULTILINE)
    gentoo = (ROOT / "Containerfile.gentoo").read_text()
    gnome = gentoo[gentoo.index("FROM desktop AS gnome"):gentoo.index("FROM desktop AS kde")]
    assert gnome.index("COPY --from=common /system_files/bluefin /") < gnome.index("/run/context/build_scripts/install-countme.sh")


def test_automated_vm_boot_paths_explicitly_exclude_telemetry():
    for filename in ("scripts/iso-e2e.sh", "scripts/install-test.sh", "scripts/run-walkthrough.sh", "scripts/bench-gdm-paint.sh", ".github/workflows/weekly-qcow2-screenshots.yml"):
        assert "type=1,product=tunaos-countme-disabled" in (ROOT / filename).read_text()
    e2e = (ROOT / "scripts/iso-e2e.sh").read_text()
    assert "--karg tunaos.countme=0" in e2e
    launches = list(re.finditer(r'^\s*"\$QEMU" (?:\\\n|[^\n]*-name)', e2e, re.MULTILINE))
    assert launches
    for launch in launches:
        assert "-smbios type=1,product=tunaos-countme-disabled" in e2e[launch.start():launch.start() + 250]
