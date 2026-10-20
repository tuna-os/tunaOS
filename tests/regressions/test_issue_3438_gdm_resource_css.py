"""tunaOS#3438: GDM's resource verifier must accept the stylesheet layouts its hook writes.

Falsification: root-only selectors reject the nested Yaru stylesheet fixtures,
while the behavioral rebuild tests verify root and nested resources preserve
non-CSS assets and leave the original resource untouched on compile failure.
"""

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "build_scripts/desktop/lib/tuna-gdm-resource.sh"
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


def _run_rebuild(
    tmp_path: Path,
    *,
    compile_failure: bool = False,
    resource_names: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    resource = tmp_path / "gnome-shell-theme.gresource"
    resource.write_bytes(b"ORIGINAL RESOURCE")
    resource_names = resource_names or [
        "/org/gnome/shell/theme/gnome-shell.css",
        "/org/gnome/shell/theme/HighContrast/gnome-shell-high-contrast.css",
        "/org/gnome/shell/theme/assets/logo.svg",
    ]
    (tmp_path / "gnome-shell-theme.gresource.list").write_text(
        "\n".join(resource_names) + "\n"
    )
    theme = tmp_path / "tuna-gdm.css"
    theme.write_text("/* TunaOS GDM theme overrides */\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gresource = bin_dir / "gresource"
    gresource.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  list) cat "$RESOURCE.list" ;;
  extract) printf 'payload:%s\\n' "$3" ;;
esac
"""
    )
    compiler = bin_dir / "glib-compile-resources"
    compiler.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
xml="$1"
source_dir=""
target=""
for arg in "${@:2}"; do
  case "$arg" in
    --sourcedir=*) source_dir="${arg#*=}" ;;
    --target=*) target="${arg#*=}" ;;
  esac
done
if [[ "${FAIL_COMPILE:-0}" == 1 ]]; then
  exit 7
fi
{
  cat "$xml"
  while IFS= read -r tag; do
    relative="${tag#<file>}"
    relative="${relative%</file>}"
    cat "$source_dir/$relative"
  done < <(grep -o '<file>[^<]*</file>' "$xml")
} >"$target"
"""
    )
    gresource.chmod(0o755)
    compiler.chmod(0o755)
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "RESOURCE": str(resource),
        "FAIL_COMPILE": "1" if compile_failure else "0",
    }
    result = subprocess.run(
        [
            "bash",
            "-euo",
            "pipefail",
            "-c",
            'source "$1"; tuna_gdm_rebuild_resource "$2" "$3"',
            "gdm-resource-test",
            str(HELPER),
            str(resource),
            str(theme),
        ],
        env=env,
        text=True,
        capture_output=True,
    )
    return result, resource


def test_rebuild_resource_preserves_root_nested_stylesheets_and_assets(tmp_path: Path):
    result, resource = _run_rebuild(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "2"
    rebuilt = resource.read_text()
    assert "<file>gnome-shell.css</file>" in rebuilt
    assert "<file>HighContrast/gnome-shell-high-contrast.css</file>" in rebuilt
    assert "<file>assets/logo.svg</file>" in rebuilt
    assert rebuilt.count("TunaOS GDM theme overrides") == 2
    assert "payload:/org/gnome/shell/theme/assets/logo.svg" in rebuilt


def test_rebuild_resource_compile_failure_keeps_original(tmp_path: Path):
    result, resource = _run_rebuild(tmp_path, compile_failure=True)

    assert result.returncode != 0
    assert resource.read_bytes() == b"ORIGINAL RESOURCE"

def test_rebuild_resource_rejects_unexpected_prefix(tmp_path: Path):
    result, resource = _run_rebuild(
        tmp_path,
        resource_names=[
            "/org/gnome/shell/theme/gnome-shell.css",
            "/org/other/theme/unexpected.css",
        ],
    )

    assert result.returncode != 0
    assert "unsupported GResource prefix" in result.stderr
    assert resource.read_bytes() == b"ORIGINAL RESOURCE"

def test_rebuild_resource_rejects_path_traversal(tmp_path: Path):
    result, resource = _run_rebuild(
        tmp_path,
        resource_names=[
            "/org/gnome/shell/theme/gnome-shell.css",
            "/org/gnome/shell/theme/../escape.css",
        ],
    )

    assert result.returncode != 0
    assert "unsafe GResource path" in result.stderr
    assert resource.read_bytes() == b"ORIGINAL RESOURCE"
