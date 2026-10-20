"""GDM's resource verifier must accept the stylesheet layouts its hook writes."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "build_scripts/checks/verify-desktop-experience.sh"


def _resource_selector() -> str:
    for line in VERIFY.read_text().splitlines():
        if line.startswith("\t\t/org/gnome/shell/theme/") and line.endswith(")"):
            return line.strip()[:-1]
    raise AssertionError("GDM resource selector is missing")


def test_gdm_resource_verifier_accepts_root_and_nested_stylesheets():
    selector = _resource_selector()
    script = f'''case "$1" in
    {selector}) exit 0 ;;
    *) exit 1 ;;
esac
'''
    cases = {
        "/org/gnome/shell/theme/gnome-shell.css": True,
        "/org/gnome/shell/theme/gnome-shell-high-contrast.css": True,
        "/org/gnome/shell/theme/Yaru/gnome-shell.css": True,
        "/org/gnome/shell/theme/Yaru/gnome-shell-high-contrast.css": True,
        "/org/gnome/shell/theme/Yaru/other.css": False,
    }
    for resource, accepted in cases.items():
        result = subprocess.run(
            ["bash", "-c", script, "resource-selector", resource],
            capture_output=True,
            text=True,
        )
        assert (result.returncode == 0) is accepted, (resource, result.stderr)
