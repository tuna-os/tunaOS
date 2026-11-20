"""The ISO customization wrapper must run a non-executable copied script.

PR #3407 failed in ISO run 39096138132 with exit 126 because cp -a and mv
preserve customize-live.sh's 0644 mode. Exercise the generated wrapper, not
just its source text, with the same mode and a path containing spaces.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _generate_wrapper(tmp_path, route):
    source = (ROOT / "scripts/build-iso-tacklebox.sh").read_text()
    start = source.index("{\n\techo '#!/usr/bin/env bash'", source.index('CUSTOMIZE_DIR='))
    end = source.index('\nif [[ "$DEV"', start)
    directory = tmp_path / "customize dir"
    directory.mkdir()
    real = directory / "customize-live-real.sh"
    real.write_text('printf "%s\n" "$TUNA_SESSION_ROOT" "$TUNA_LIVE_BASE_IMAGE" "$TUNA_LIVE_BASE_DIGEST" "$TUNA_LIVE_PLATFORM" "${TUNA_LIVE_PAYLOAD_REF-unset}" "${TUNA_LIVE_DEFER_LOCAL_IMGREF-unset}" "$@"\nexit 17\n')
    real.chmod(0o644)
    env = os.environ | {
        "CUSTOMIZE_DIR": str(directory),
        "IMAGE_REF": "ghcr.io/tuna-os/yellowfin:kde",
        "BASE_DIGEST": "sha256:" + "a" * 64,
        "SOURCE_PLATFORM": "linux/amd64",
        "PAYLOAD_REF": "ghcr.io/tuna-os/yellowfin:kde-linux-amd64",
        "LIVE_ROUTE": route,
    }
    for name in ("TUNA_LIVE_PAYLOAD_REF", "TUNA_LIVE_DEFER_LOCAL_IMGREF"):
        env.pop(name, None)
    subprocess.run(["bash", "-euc", source[start:end]], env=env, check=True)
    result = subprocess.run([str(directory / "customize-live.sh"), "argument with spaces"], text=True, capture_output=True, env=env)
    assert result.returncode == 17, result.stderr
    return env, result.stdout.splitlines()


def test_wrapper_runs_nonexecutable_customizer_and_forwards_arguments(tmp_path):
    env, lines = _generate_wrapper(tmp_path, "generic")
    assert lines == ["/", env["IMAGE_REF"], env["BASE_DIGEST"], env["SOURCE_PLATFORM"], env["PAYLOAD_REF"], "unset", "argument with spaces"]


def test_x13s_wrapper_binds_no_offline_payload(tmp_path):
    """X13s media has no offline payload: tacklebox --x13s-live refuses one.

    Falsification: export TUNA_LIVE_PAYLOAD_REF on the x13s route and the
    installer recipe points at a store the ISO does not carry.
    """
    env, lines = _generate_wrapper(tmp_path, "x13s")
    assert lines == ["/", env["IMAGE_REF"], env["BASE_DIGEST"], env["SOURCE_PLATFORM"], "unset", "1", "argument with spaces"]


def test_overlay_staging_tags_are_unique_per_run_and_attempt():
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/live-overlay.yml").read_text())
    step = next(step for job in workflow["jobs"].values() for step in job.get("steps", []) if step.get("name") == "Run live customize and publish overlay")
    assert step["run"].count("--retry 5") >= 2
    assert "--retry-max-time 60" in step["run"]
    assignment = next(line.strip() for line in step["run"].splitlines() if line.strip().startswith('OUT='))
    tags = set()
    for run, attempt in [("123", "1"), ("124", "1"), ("123", "2")]:
        env = os.environ | {"VARIANT": "yellowfin", "FLAVOR": "kde", "SAFEPLATFORM": "linux-amd64", "PUBLISH_DEST": "ghcr.io/tuna-os", "GITHUB_RUN_ID": run, "GITHUB_RUN_ATTEMPT": attempt}
        result = subprocess.run(["bash", "-euc", assignment + '\nprintf "%s" "$OUT"'], env=env, text=True, capture_output=True, check=True)
        tags.add(result.stdout)
    assert len(tags) == 3
    assert all(tag.startswith("ghcr.io/tuna-os/live-overlay:yellowfin-kde-linux-amd64-") for tag in tags)
