"""tunaOS#4864: the UEFI boot entry must carry the variant's name.

The installed yellowfin booted `Boot000A "AlmaLinux Kitten"
\\EFI\\almalinux\\shimx64.efi` (strict log t38,
strict-plain-installed-serial.log:1); bonito installs booted `"Fedora"`.
`bootc install` runs bootupd from the image, and bootupd names the entry from
/etc/system-release up to "release", or os-release NAME without that file
(bootupd src/efi.rs, get_product_name). The bonito image (main 69f7e8a) has
/etc/system-release -> fedora-release ("Fedora release 44") and
/usr/lib/efi/shim/16.1-7/EFI/fedora/BOOTAA64.CSV labelled "Fedora". The
published yellowfin has /etc/system-release hard-linked to redhat-release ->
almalinux-release and /usr/lib/bootupd/updates/EFI/almalinux/BOOTX64.CSV.

The real 90-image-info.sh runs here against the tests/test_anime_finalization.py
fixture, with those upstream files laid in. It must leave both labels equal to
os-release NAME, and checks/verify-efi-boot-label.sh must say so.

Falsification: behavioural. Remove the efi-boot-label.sh call from
90-image-info.sh and the verifier it runs next fails the writer for every RPM
variant here. The verifier tests feed it the measured upstream files and
require exit 1.
"""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from test_anime_finalization import Image  # noqa: E402

CHECK = ROOT / "build_scripts/checks/verify-efi-boot-label.sh"
FEDORA_CSV = "shimaa64.efi,Fedora,,This is the boot entry for Fedora\n"
ALMA_CSV = "shimx64.efi,AlmaLinux Kitten,,This is the boot entry for AlmaLinux Kitten\n"


def utf16(text):
    return b"\xff\xfe" + text.encode("utf-16-le")


def lay_fedora(root):
    (root / "usr/lib/fedora-release").write_text("Fedora release 44 (Forty Four)\n")
    (root / "etc/fedora-release").symlink_to("../usr/lib/fedora-release")
    (root / "etc/redhat-release").symlink_to("fedora-release")
    (root / "etc/system-release").hardlink_to(root / "etc/redhat-release")
    csv = root / "usr/lib/efi/shim/16.1-7/EFI/fedora/BOOTAA64.CSV"
    csv.parent.mkdir(parents=True)
    csv.write_bytes(utf16(FEDORA_CSV))
    return csv


def lay_alma(root):
    (root / "usr/lib/almalinux-release").write_text("AlmaLinux Kitten release 10 (Lion Cub)\n")
    (root / "etc/almalinux-release").symlink_to("../usr/lib/almalinux-release")
    (root / "etc/redhat-release").symlink_to("almalinux-release")
    (root / "etc/system-release").hardlink_to(root / "etc/redhat-release")
    csv = root / "usr/lib/bootupd/updates/EFI/almalinux/BOOTX64.CSV"
    csv.parent.mkdir(parents=True)
    csv.write_bytes(utf16(ALMA_CSV))
    return csv


def check(root):
    return subprocess.run(["bash", str(CHECK)], env={"PATH": "/usr/bin:/bin", "TUNAOS_SYSROOT": str(root)},
                          capture_output=True, text=True)


def os_release(root, name):
    (root / "usr/lib").mkdir(parents=True, exist_ok=True)
    (root / "etc").mkdir(exist_ok=True)
    (root / "usr/lib/os-release").write_text(f'NAME="{name}"\nVERSION_ID=44\n')
    (root / "etc/os-release").symlink_to("../usr/lib/os-release")


@pytest.mark.parametrize("lay, label", [(lay_fedora, "Fedora"), (lay_alma, "AlmaLinux Kitten")])
def test_the_measured_upstream_labels_fail(tmp_path, lay, label):
    os_release(tmp_path, "Bonito")
    lay(tmp_path)
    result = check(tmp_path)
    assert result.returncode == 1, result.stdout
    assert f"bootupd would name the boot entry '{label}'" in result.stderr
    assert f"is labelled '{label}', want 'Bonito'" in result.stderr


@pytest.mark.parametrize("name", ["Fedora Linux", "AlmaLinux Kitten", "Ubuntu", "Arch Linux"])
def test_an_upstream_name_cannot_pass_by_agreeing_with_itself(tmp_path, name):
    os_release(tmp_path, name)
    result = check(tmp_path)
    assert result.returncode == 1
    assert "is an upstream name" in result.stderr


def test_a_base_without_system_release_or_shim_uses_os_release(tmp_path):
    """Arch, Debian, Ubuntu, openSUSE and Gentoo: bootupd would read NAME."""
    os_release(tmp_path, "Marlin")
    result = check(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "TUNAOS_EFI_LABEL_OK name=Marlin product=Marlin csvs=0" in result.stdout


@pytest.mark.parametrize("variant, lay", [
    ("yellowfin", lay_alma), ("albacore", lay_alma), ("skipjack", lay_alma),
    ("bonito", lay_fedora), ("bonito-rawhide", lay_fedora), ("hummingbird", lay_fedora),
])
def test_90_image_info_names_both_entries_after_the_variant(tmp_path, variant, lay):
    image = Image(tmp_path, variant)
    # The fixture's /etc/os-release is a separate file; the real bases link it.
    (image.root / "etc/os-release").unlink()
    (image.root / "etc/os-release").symlink_to("../usr/lib/os-release")
    csv = lay(image.root)
    image.info()
    name = next(line.split("=", 1)[1].strip('"')
                for line in (image.root / "usr/lib/os-release").read_text().splitlines()
                if line.startswith("NAME="))
    assert name.lower().startswith(variant.split("-")[0])
    release = image.root / "etc/system-release"
    assert release.read_text().split(" release")[0] == name
    assert csv.read_bytes()[:2] == b"\xff\xfe"
    fields = csv.read_bytes()[2:].decode("utf-16-le").strip().split(",")
    assert fields[1] == name and fields[3] == f"This is the boot entry for {name}"
    assert fields[0] in ("shimaa64.efi", "shimx64.efi") and fields[2] == ""
    # The base's own release files stay, for tools that read them.
    assert "release" in (image.root / "etc/redhat-release").read_text()
    assert name not in (image.root / "etc/redhat-release").read_text()
    assert check(image.root).returncode == 0
