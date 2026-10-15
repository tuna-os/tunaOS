"""Keep user installs aligned with Marlin's composefs VM installation."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_marlin_installer_override_reaches_the_base_image():
    base = tomllib.loads((ROOT / "system_files/usr/lib/bootc/install/00-tunaos.toml").read_text())
    override = tomllib.loads((ROOT / "system_files_overrides/marlin/usr/lib/bootc/install/50-marlin.toml").read_text())
    assert base["install"]["filesystem"]["root"]["type"] == "xfs"
    assert override["install"]["filesystem"]["root"]["type"] == "ext4"
    assert override["install"]["bootloader"] == "systemd"
    source = (ROOT / "Containerfile.arch").read_text()
    assert "COPY system_files_overrides /overrides" in source
    hook = source.index("/run/context/build_scripts/92-variant-customizations.sh")
    assert source.index("COPY --from=context /files /") < hook < source.index("/run/context/build_scripts/99-cleanup.sh", hook)
    # The build checks bootc's merged result, rather than just the file's presence.
    assert "bootc install print-configuration | jq -e" in source[hook:]
