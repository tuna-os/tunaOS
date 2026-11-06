"""Run 39310599051: a transient API error must not freeze or corrupt the snapshot."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github/scripts/gh-read-retry.sh"
GENERATOR = ROOT / ".github/scripts/update-build-status.sh"


@pytest.fixture
def harness(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        "gh": '''#!/usr/bin/env bash
if [[ "${FAIL_STAGE:-}" == api && "$1" == run ]]; then
    echo '[{"databaseId":1,"conclusion":"success","createdAt":"2026-10-19T00:00:00Z","url":"https://github.com/example/run/1"}]'
    exit 0
fi
n=$(cat "$CASE_DIR/count" 2>/dev/null || echo 0)
n=$((n+1))
echo "$n" > "$CASE_DIR/count"
printf '%s\\n' "$*" >> "$CASE_DIR/args"
if ((n <= FAIL_COUNT)); then
    printf 'build / gnome / Promote\\tsuccess\\n'
    echo "$FAIL_MESSAGE" >&2
    exit 7
fi
echo 'complete response'
''',
        "sleep": '#!/usr/bin/env bash\necho "$1" >> "$CASE_DIR/sleeps"\n',
        "yq": '''#!/usr/bin/env bash
case "$*" in
  *'.id, .emoji'*) printf 'yellowfin\\tfish\\n' ;;
  *'build_image == true'*) echo gnome ;;
esac
''',
    }
    for name, content in scripts.items():
        executable = bin_dir / name
        executable.write_text(content)
        executable.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "CASE_DIR": str(tmp_path), "FAIL_COUNT": "1",
           "FAIL_MESSAGE": "gh: Server Error (HTTP 502)"}
    return tmp_path, env


def call(harness, message, failures=1):
    directory, env = harness
    env.update(FAIL_MESSAGE=message, FAIL_COUNT=str(failures))
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; gh_read_retry api --paginate "repos/example/actions/runs/1/jobs?per_page=100"',
         "bash", str(HELPER)], env=env, capture_output=True, text=True, check=False)
    return result, int((directory / "count").read_text())


@pytest.mark.parametrize("message", [
    "gh: Server Error (HTTP 502)", "gh: HTTP 503", "connection reset by peer",
    "TLS handshake timeout", "unexpected EOF",
])
def test_transient_failure_discards_partial_pages_before_retry(harness, message):
    result, count = call(harness, message)
    assert result.returncode == 0
    assert count == 2
    assert result.stdout == "complete response\n"
    assert (harness[0] / "sleeps").read_text() == "5\n"
    assert len(set((harness[0] / "args").read_text().splitlines())) == 1


@pytest.mark.parametrize("message", [
    "gh: API rate limit exceeded (HTTP 403)",
    "gh: secondary rate limit exceeded (HTTP 403)", "gh: HTTP 429",
])
def test_rate_limits_without_reset_metadata_preserve_error(harness, message):
    result, count = call(harness, message)
    assert result.returncode == 7 and count == 1
    assert message in result.stderr
    assert result.stdout == ""
    assert not (harness[0] / "sleeps").exists()


@pytest.mark.parametrize("message", [
    "gh: Bad credentials (HTTP 401)", "gh: Resource not accessible (HTTP 403)",
    "gh: Not Found (HTTP 404)", "gh: Validation Failed (HTTP 422)",
    "unknown flag: --wrong",
])
def test_permanent_errors_fail_immediately(harness, message):
    result, count = call(harness, message, failures=9)
    assert result.returncode == 7 and count == 1
    assert result.stdout == ""
    assert message in result.stderr
    assert not (harness[0] / "sleeps").exists()


def test_exhaustion_preserves_error_and_exit_status_without_partial_output(harness):
    result, count = call(harness, "gh: Server Error (HTTP 502)", failures=9)
    assert result.returncode == 7 and count == 3
    assert result.stdout == ""
    assert "gh: Server Error (HTTP 502)" in result.stderr
    assert (harness[0] / "sleeps").read_text() == "5\n10\n"


@pytest.mark.parametrize("stage", ["run", "api"])
def test_generator_does_not_replace_readme_when_reads_fail(harness, stage):
    directory, env = harness
    env["FAIL_COUNT"] = "9"
    env["FAIL_STAGE"] = stage
    readme = directory / "README.md"
    original = "Before\n<!-- build-status:start -->\nold snapshot\n<!-- build-status:end -->\nAfter\n"
    readme.write_text(original)
    result = subprocess.run(["bash", str(GENERATOR), "unused.yml", str(readme)],
                            cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 7
    assert readme.read_text() == original
    assert int((directory / "count").read_text()) == 3


def test_both_load_bearing_api_reads_use_the_wrapper():
    script = GENERATOR.read_text()
    assert "runs=$(gh_read_retry run list" in script
    assert "stage_jobs=$(gh_read_retry api --paginate" in script
