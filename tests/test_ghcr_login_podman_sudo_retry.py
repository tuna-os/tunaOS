"""The sudo podman login must retry, and retrying must not hide a real failure.

Six live arm64 runners, both podman versions the fleet hands out (4.9.3 and
5.8.4, with and without a pre-existing containers.conf), all showed the same
thing: `podman login`/`podman info` succeed at sudo's DEFAULT soft nofile of
1024 -- the descriptor-limit fix this action carried since #1101 does not
address the failure at all. A follow-up measurement reproduced the exact
login sequence (unsudo login, then sudo login, real credentials, no ulimit
override) on the same six runners and it succeeded cleanly on all six too.
See tunaOS#1495 for the measurements.

Nothing available to an isolated diagnostic job reproduces the production
failure, so this is a retry -- a mitigation for an unreproduced intermittent,
following the same idiom this repo already trusts for GHCR push and cosign
sign -- not a fix for a diagnosed cause.

The one way a retry can make things worse than no retry at all: a
`for ... && break; sleep; done` with nothing after it exits with `sleep`'s
status (near-always 0) even when every attempt failed, silently reporting
success while podman was never actually authenticated. These tests pin that
exhaustion is a real, visible failure.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/ghcr-login/action.yml"


@pytest.fixture(scope="module")
def sudo_login_step():
    action = yaml.safe_load(ACTION.read_text())
    return next(
        s for s in action["runs"]["steps"] if s.get("name") == "Login to Podman (sudo)"
    )


def test_the_step_retries_more_than_cosigns_own_two_attempts(sudo_login_step):
    max_retries = sudo_login_step.get("env", {}).get("MAX_RETRIES")
    assert max_retries is not None, "MAX_RETRIES is not set for the sudo login step"
    assert int(max_retries) >= 3


def _drive_step(sudo_login_step, tmp_path, login_cmd):
    """Run the REAL step body, substituting a fake `sudo` so no real sudo call happens."""
    # The body reads its untrusted values ($GHCR_TOKEN, $GHCR_ACTOR) from the
    # step's `env:` block rather than interpolating ${{ }} expressions inline,
    # so drive it the way a runner does: evaluate the expressions in `env:`
    # and export them around the verbatim body. Substituting inside the body
    # instead would leave $GHCR_TOKEN unbound under `set -u`.
    body = sudo_login_step["run"]
    step_env = {
        name: str(value)
        .replace("${{ github.token }}", "fake-token")
        .replace("${{ github.actor }}", "fake-actor")
        for name, value in sudo_login_step.get("env", {}).items()
    }
    env_block = "\n".join(f'export {name}="{value}"' for name, value in step_env.items())
    # The step invokes `sudo TOKEN=... ACTOR=... bash -c '...'`. Swap in a
    # fake `sudo` on PATH that runs the given login_cmd instead of the real
    # podman/bash construct, so this drives the loop/exit logic without
    # requiring podman, sudo, or network access.
    fake_sudo = tmp_path / "sudo"
    fake_sudo.write_text(f"#!/usr/bin/env bash\n{login_cmd}\n")
    fake_sudo.chmod(0o755)

    script = tmp_path / "probe.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            PATH="{tmp_path}:$PATH"
            {env_block}
            {body}
            echo "REACHED END"
            """
        )
    )
    return subprocess.run(["bash", str(script)], capture_output=True, text=True)


def test_exhausting_every_retry_fails_the_step(sudo_login_step, tmp_path):
    proc = _drive_step(sudo_login_step, tmp_path, "exit 1")
    assert proc.returncode != 0, "the step must fail when every retry fails"
    assert "REACHED END" not in proc.stdout, (
        f"execution continued past exhausted retries: {proc.stdout!r}"
    )
    assert "sudo podman login failed after" in proc.stderr + proc.stdout


def test_a_flake_that_clears_on_a_later_attempt_still_succeeds(sudo_login_step, tmp_path):
    marker = tmp_path / "attempts"
    login_cmd = (
        f'n=0; [[ -f "{marker}" ]] && n=$(cat "{marker}"); n=$((n+1)); '
        f'echo "$n" > "{marker}"; [[ "$n" -ge 2 ]]'
    )
    proc = _drive_step(sudo_login_step, tmp_path, login_cmd)
    assert proc.returncode == 0, f"a flake that clears must not fail the step: {proc.stderr!r}"
    assert "REACHED END" in proc.stdout


def test_success_on_the_first_attempt_does_not_wait_out_the_backoff(sudo_login_step, tmp_path):
    proc = _drive_step(sudo_login_step, tmp_path, "exit 0")
    assert proc.returncode == 0
    assert "failed (attempt" not in proc.stdout + proc.stderr
