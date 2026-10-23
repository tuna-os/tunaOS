"""CI must read Python pins from `python_packages`, not from the whole file.

image-versions.yaml pins jsonschema twice: `python_packages` (contract tools)
and `downloads` (test oracle). A whole-file match saw both and failed the
build-health and matrix-status install steps with
"missing or ambiguous central dependency pin".
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "python-package-pins.py"
VERSIONS = ROOT / "image-versions.yaml"
WORKFLOWS = (".github/workflows/build-health.yml", ".github/workflows/matrix-status.yml")


def run(versions: Path, *names: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(versions), *names],
        capture_output=True, text=True,
    )


def test_real_file_has_two_jsonschema_pins_and_reader_picks_python_packages():
    doc = yaml.safe_load(VERSIONS.read_text())
    assert doc["python_packages"]["jsonschema"] != doc["downloads"]["jsonschema"], (
        "premise changed: the two pins agree, so this regression no longer bites"
    )
    result = run(VERSIONS, "PyYAML", "jsonschema", "pytest")
    assert result.returncode == 0, result.stderr
    pins = doc["python_packages"]
    assert result.stdout.split() == [
        f"{n}=={pins[n]}" for n in ("PyYAML", "jsonschema", "pytest")
    ]


def test_duplicate_pin_in_another_section_is_ignored(tmp_path):
    f = tmp_path / "v.yaml"
    f.write_text(
        'downloads:\n  jsonschema: "9.9.9"\n'
        'python_packages:\n  jsonschema: "1.2.3"\n  PyYAML: "4.5.6"\n'
        'other:\n  PyYAML: "0.0.1"\n'
    )
    result = run(f, "jsonschema", "PyYAML")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["jsonschema==1.2.3", "PyYAML==4.5.6"]


@pytest.mark.parametrize(
    "body",
    [
        'downloads:\n  jsonschema: "9.9.9"\n',
        'python_packages:\n  PyYAML: "1.0"\n',
        'python_packages:\n  jsonschema: "1.0"\n  jsonschema: "2.0"\n',
    ],
)
def test_missing_section_or_pin_fails_closed(tmp_path, body):
    f = tmp_path / "v.yaml"
    f.write_text(body)
    result = run(f, "jsonschema")
    assert result.returncode == 1
    assert "==" not in result.stdout


@pytest.mark.parametrize("path", WORKFLOWS)
def test_workflows_use_the_section_reader_not_a_whole_file_match(path):
    text = (ROOT / path).read_text()
    assert "scripts/python-package-pins.py image-versions.yaml" in text
    assert "re.findall" not in text
