import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "candidate-flavor-selection.py"


CONFIG = {
    "variants": [
        {
            "id": "yellowfin",
            "platforms": ["linux/amd64", "linux/arm64"],
            "flavors": [
                {"id": "base", "stage": 1, "build_image": True},
                {"id": "base-hwe", "stage": 2, "build_image": True},
                {"id": "gnome", "stage": 2, "build_image": True,
                 "platforms": ["linux/amd64"]},
                {"id": "gnome-hwe", "stage": 3, "build_image": True},
                {"id": "disabled", "stage": 2, "build_image": False},
            ],
        },
    ],
}


def run_selector(**env):
    command_env = os.environ.copy()
    command_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(CONFIG),
        text=True,
        capture_output=True,
        env=command_env,
        check=False,
    )


def test_unfiltered_build_uses_normal_matrix_filters():
    result = run_selector(FILTER_VARIANT="all", FILTER_FLAVOR="all")
    assert result.returncode == 0
    assert json.loads(result.stdout) is None


def test_filtered_flavor_includes_prior_build_stages_and_platforms():
    result = run_selector(FILTER_VARIANT="yellowfin", FILTER_FLAVOR="gnome-hwe")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "yellowfin": {
            "base": ["linux/amd64", "linux/arm64"],
            "base-hwe": ["linux/amd64", "linux/arm64"],
            "gnome": ["linux/amd64"],
            "gnome-hwe": ["linux/amd64", "linux/arm64"],
        }
    }


def test_filtered_stage_excludes_unrelated_peer_flavors():
    result = run_selector(FILTER_VARIANT="yellowfin", FILTER_FLAVOR="gnome")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "yellowfin": {
            "base": ["linux/amd64", "linux/arm64"],
            "gnome": ["linux/amd64"],
        }
    }


def test_unknown_flavor_fails_closed():
    result = run_selector(FILTER_VARIANT="yellowfin", FILTER_FLAVOR="missing")
    assert result.returncode != 0
    assert "unknown flavor" in result.stderr
