"""tunaOS#1411: runs 31559580365/31559619276 reported five runtime gaps.

Hyperscale filelists (2026-11-03) provide asahi-diagnose in /usr/sbin via
asahi-scripts. Missing packaged diagnostics must fail on EL10 too; only the
four target-unavailable checks may warn, with a packaging tracker.
Falsification: behavioural — run the production verifier against mounted
filesystem fixtures; the old verifier warns instead of failing on diagnostics
loss, and warns instead of accepting the real Hyperscale diagnostic path.
"""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULES = """asahi appledrm nvme-apple hci_bcm4377 brcmfmac apple-dart macsmc
apple-isp spi-hid-apple apple-admac apple-soc-cpufreq dockchannel-hid""".split()


@pytest.fixture
def image(tmp_path):
    mount = tmp_path / "image"

    def touch(path, text=""):
        target = mount / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    touch("etc/os-release", 'ID=almalinux\nVERSION_ID="10"\nPLATFORM_ID="platform:el10"\n')
    kernel = "usr/lib/modules/6.16.asahi+16k"
    for name in ("vmlinuz", "initramfs.img"):
        touch(f"{kernel}/{name}")
    touch(f"{kernel}/modules.dep", "".join(f"kernel/{mod}.ko: modules\n" for mod in MODULES if mod != "apple-isp"))
    for name in ["t8103-j313"] + [f"model-{i}" for i in range(50)]:
        touch(f"{kernel}/dtb/apple/{name}.dtb")
    for path in (
        "usr/lib64/m1n1/m1n1.bin", "usr/share/uboot/apple_m1/u-boot-nodtb.bin",
        "usr/sbin/update-m1n1", "usr/bin/asahi-fwextract", "usr/sbin/asahi-fwupdate",
        "usr/bin/speakersafetyd", "usr/lib/systemd/system/speakersafetyd.service",
        "usr/sbin/asahi-diagnose",
    ):
        touch(path)
    for directory in (
        "usr/lib/dracut/modules.d/99asahi-firmware",
        "usr/lib/dracut/modules.d/91kernel-modules-asahi",
        "usr/share/alsa/ucm2/conf.d/macaudio",
    ):
        (mount / directory).mkdir(parents=True)
    touch("usr/lib/dracut/dracut.conf.d/asahi.conf", 'add_dracutmodules+=" asahi-firmware "\n')
    for i in range(5):
        touch(f"usr/share/asahi-audio/profile-{i}")

    # Only container transport is mocked: execute the verifier's actual inner
    # shell against a complete filesystem, including its summary/exit status.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    podman = bindir / "podman"
    podman.write_text("""#!/bin/bash
case "$1" in
    create) echo fixture ;;
    unshare) shift; exec "$@" ;;
    mount) echo "$ASAHI_FIXTURE" ;;
    umount|rm) exit 0 ;;
    *) exit 99 ;;
esac
""")
    podman.chmod(0o755)
    lsinitrd = bindir / "lsinitrd"
    lsinitrd.write_text("#!/bin/bash\necho asahi-firmware\n")
    lsinitrd.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "ASAHI_FIXTURE": str(mount)}

    def verify():
        return subprocess.run(
            ["bash", str(ROOT / "scripts/verify-asahi-image.sh"), "fixture", "--no-pull"],
            env=env, capture_output=True, text=True, check=False,
        )

    return mount, touch, verify


def test_el10_accepts_packaged_diagnostic_path_and_tracks_only_real_gaps(image):
    _, _, verify = image
    result = verify()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok   asahi-diagnose (/usr/sbin/asahi-diagnose)" in result.stdout
    warnings = [line for line in result.stdout.splitlines() if "  warn " in line]
    assert len(warnings) == 4, result.stdout
    assert all("https://github.com/tuna-os/tunaos/issues/4259" in line for line in warnings)


@pytest.mark.parametrize("family", ["el10", "fedora"])
def test_missing_diagnostics_is_a_regression_on_every_target(image, family):
    mount, touch, verify = image
    if family == "fedora":
        touch("etc/os-release", 'ID=fedora\nVERSION_ID="44"\n')
    (mount / "usr/sbin/asahi-diagnose").unlink()
    result = verify()
    assert result.returncode == 1
    assert "FAIL asahi-diagnose missing" in result.stdout


def test_fedora_does_not_inherit_el10_exceptions(image):
    _, touch, verify = image
    touch("etc/os-release", 'ID=fedora\nVERSION_ID="44"\n')
    result = verify()
    assert result.returncode == 1
    assert "4 failed, 0 warnings" in result.stdout


def test_available_el10_components_pass_without_warnings(image):
    _, touch, verify = image
    for path in (
        "usr/lib/kernel/install.d/15-update-m1n1.install",
        "usr/bin/tiny-dfr", "usr/lib/systemd/system/tiny-dfr.service",
    ):
        touch(path)
    touch("usr/lib/modules/6.16.asahi+16k/modules.dep",
          "".join(f"kernel/{mod}.ko: modules\n" for mod in MODULES))
    result = verify()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failed, 0 warnings" in result.stdout


def test_rpm_overlay_requires_the_diagnostic_provider():
    # Falsification: structural — move asahi-scripts back to best-effort in
    # the centos branch (the pre-fix tree) and this assertion fails.
    import re

    overlay = (ROOT / "build_scripts/overlay/asahi.sh").read_text()
    for family in ("fedora", "centos"):
        branch = overlay.split(f"\n{family})", 1)[1].split("\n\t;;", 1)[0]
        commands = branch.replace("\\\n", " ").splitlines()
        required = [line for line in commands if re.match(r"\s*dnf -y install --allowerasing ", line)]
        assert any("asahi-scripts" in line.split() for line in required), family
