from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
GNOME_MANIFEST = REPO_ROOT / "manifests/desktops/gnome.yaml"


def test_repository_does_not_bundle_gnome_extensions():
    extensions = REPO_ROOT / "system_files/usr/share/gnome-shell/extensions"

    assert not extensions.exists() or not any(extensions.iterdir())
    assert not (REPO_ROOT / "build_scripts/desktop/gnome-extensions.sh").exists()
    assert not (REPO_ROOT / ".gitmodules").exists()


def test_gnome_manifest_does_not_request_extension_packages_or_build_hooks():
    manifest = GNOME_MANIFEST.read_text()

    assert "gnome-extensions.sh" not in manifest
    assert "gnome-classic-session" not in manifest
    assert "gnome-shell-extensions-common" not in manifest
    assert "gnome-shell-extension-manager" not in manifest


def test_gnome_users_are_offered_extension_manager_without_an_extension(tmp_path):
    script = REPO_ROOT / "build_scripts/desktop/flatpak-preinstall.sh"
    for desktop in ("gnome", "kde", "tuna"):
        output = tmp_path / desktop / "preinstall.d"
        result = subprocess.run(["bash", str(script)], env={
            "PATH": "/usr/bin:/bin", "DESKTOP_FLAVOR": desktop,
            "TUNAOS_PREINSTALL_DIR": str(output),
            "TUNAOS_SYSTEMD_SYSTEM_DIR": str(tmp_path / "no-unit")},
            capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        declarations = (output / f"tunaos-{desktop}.preinstall").read_text()
        offered = "[Flatpak Preinstall com.mattjakeman.ExtensionManager]" in declarations
        assert offered == (desktop == "gnome")
