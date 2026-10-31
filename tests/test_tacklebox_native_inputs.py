"""PR #3431 reviews r4380956350/r4380956452: inert native-input regressions."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("host,requested,expected", [
    ("x86_64", "", "linux/amd64"),
    ("x86_64", "linux/amd64", "linux/amd64"),
    ("x86_64", "linux/amd64/v2", "linux/amd64/v2"),
    ("aarch64", "linux/arm64", "linux/arm64"),
    ("aarch64", "", "linux/arm64"),
    ("x86_64", "linux/arm64", None),
    ("aarch64", "linux/amd64", None),
    ("aarch64", "linux/amd64/v2", None),
    ("x86_64", "linux/amd64/v3", None),
    ("x86_64", "windows/amd64", None),
    ("x86_64", "linux/arm64/v8", None),
    ("riscv64", "", None),
])
@pytest.mark.parametrize("repo", ["local", "ghcr"])
def test_native_platform_preflight_before_image_work(tmp_path, host, requested, expected, repo):
    source = (ROOT / "scripts/build-iso-tacklebox.sh").read_text()
    # Execute the production preflight through source measurement, stubbing only
    # image operations. No root privileges, image storage or registry is used.
    start = min(source.index('case "$(uname -m)" in'),
                source.index("# Store the project root"))
    end = source.index('# ponytail:', start)
    trace = tmp_path / "trace"
    script = '''
    uname() { echo "$HOST_ARCH"; }
    tunaos_image_ref() { echo 'ghcr.io/fixture/os:desktop'; }
    tunaos_import_to_root_storage() { echo "import:$*" >> "$TRACE"; }
    podman() { echo "podman:$*" >> "$TRACE"; }
    platform_manifest_digest() {
        echo "measure:$*" >> "$TRACE"
        printf 'sha256:%064d\\n' 0
    }
    ''' + source[start:end] + '\nprintf "%s\\n" "$SOURCE_PLATFORM"\n'
    result = subprocess.run(["bash", "-euc", script], cwd=tmp_path, text=True,
                            capture_output=True, env={**os.environ,
                                "HOST_ARCH": host, "PLATFORM": requested,
                                "VARIANT": "fixture", "FLAVOR": "desktop", "TAG": "desktop",
                                "REPO": repo, "SUDO_USER": "", "TRACE": str(trace),
                                "TUNA_LIVE_BASE_DIGEST": "", "TUNA_LIVE_OVERLAY_REF": ""})
    if expected is None:
        assert result.returncode != 0
        assert "ERROR:" in result.stderr
        assert not trace.exists(), trace.read_text()
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
        lines = trace.read_text().splitlines()
        assert lines == [
            ("import:ghcr.io/fixture/os:desktop" if repo == "local" else
             f"podman:pull --platform {expected} ghcr.io/fixture/os:desktop"),
            f"measure:ghcr.io/fixture/os:desktop {expected}",
        ]


@pytest.mark.parametrize("valid_revision", [True, False])
def test_relative_cache_miss_builds_pinned_source_without_changing_cwd(tmp_path, valid_revision):
    source = tmp_path / "source"
    source.mkdir()
    (source / "go.mod").write_text("module fixture\n\ngo 1.20\n")
    command = source / "cmd/tacklebox"
    command.mkdir(parents=True)
    (command / "main.go").write_text('''package main
import ("fmt"; "runtime/debug")
func main() {
    info, _ := debug.ReadBuildInfo()
    for _, setting := range info.Settings {
        if setting.Key == "vcs.revision" { fmt.Println(setting.Value) }
    }
}
''')
    env = {**os.environ, "GIT_AUTHOR_NAME": "Codex", "GIT_AUTHOR_EMAIL": "codex@openai.com",
           "GIT_COMMITTER_NAME": "Codex", "GIT_COMMITTER_EMAIL": "codex@openai.com",
           "GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off",
           "GOCACHE": str(tmp_path / "go-cache")}
    for args in (["init", "--quiet"], ["add", "."], ["commit", "--quiet", "-s", "-m", "local fixture"]):
        subprocess.run(["git", *args], cwd=source, env=env, check=True, capture_output=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    env.update(TACKLEBOX_SHA=sha, TACKLEBOX_CACHE="relative cache", FIXTURE_SOURCE=str(source),
               BUILD_REVISION=sha if valid_revision else "0" * 40)
    script = '''
    source "$1"
    git() {
        if [[ "$1" == clone ]]; then
            command git clone --quiet "$FIXTURE_SOURCE" .
        else
            command git "$@"
        fi
    }
    # Compile is inert; acquisition, checkout, mktemp, revision admission and
    # atomic installation all execute the production helper against real files.
    fake_go() {
        if [[ "$1" == build ]]; then
            [[ "$2" == -o && "$3" == "$PWD"/.tacklebox-build.* ]] || return 95
            printf '#!/bin/sh\\nprintf "%%s\\n" "%s"\\n' "$TACKLEBOX_SHA" > "$3"
            chmod +x "$3"
        elif [[ "$1 $2" == 'version -m' ]]; then
            printf '\\tbuild\\tvcs.revision=%s\\n' "$BUILD_REVISION"
        else
            return 96
        fi
    }
    function /home/linuxbrew/.linuxbrew/bin/go() { fake_go "$@"; }
    function /usr/bin/go() { fake_go "$@"; }
    go() { fake_go "$@"; }
    before=$PWD
    bin=$(tunaos_tacklebox_source_binary)
    [[ "$PWD" == "$before" && "$bin" == "$before/relative cache/tacklebox" ]]
    [[ "$("$bin" version)" == "$TACKLEBOX_SHA" ]]
    # The now-populated cache must work without acquiring source again.
    git() { return 97; }
    [[ "$(tunaos_tacklebox_source_binary)" == "$bin" ]]
    printf '%s\\n' "$bin"
    '''
    result = subprocess.run(["bash", "-euc", script, "fixture", str(ROOT / "scripts/lib/tacklebox.sh")],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    if not valid_revision:
        assert result.returncode != 0
        assert not (tmp_path / "relative cache/tacklebox").exists()
        assert not result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(tmp_path / "relative cache/tacklebox")
    assert not list((tmp_path / "relative cache").glob(".tacklebox-build.*"))
    assert subprocess.check_output(["git", "rev-parse", "HEAD"],
                                   cwd=tmp_path / "relative cache", text=True).strip() == sha


def test_relative_cache_snapshot_hash_identifies_invoked_bytes(tmp_path):
    import hashlib

    cache = tmp_path / "relative cache"
    cache.mkdir()
    binary = cache / "tacklebox"
    original = '''#!/bin/sh
if [ "$1" = version ]; then
    echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
else
    # Model another acquisition replacing the shared cache during invocation.
    printf '#!/bin/sh\\necho replacement\\n' > "$SHARED_BINARY"
    sha256sum "$0" > "$INVOKED_HASH"
fi
'''
    binary.write_text(original)
    binary.chmod(0o755)
    output = tmp_path / "output"
    wrapper = output / "live-customize/customize-live.sh"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("export TUNA_LIVE_ENGINE_DIGEST=unknown\n")
    recipe = tmp_path / "recipe.json"
    recipe.write_text("{}")
    result = subprocess.run(["bash", "-euc", '''
        source "$1"
        tunaos_run_tacklebox "$2" "$3" "$4"
        ''', "fixture", str(ROOT / "scripts/lib/tacklebox.sh"), str(recipe),
        str(output), str(tmp_path / "output.iso")], cwd=tmp_path,
        env={**os.environ, "TACKLEBOX_CACHE": "relative cache", "TACKLEBOX_SHA": "a" * 40,
             "TACKLEBOX_FROM_SOURCE": "1", "SHARED_BINARY": str(binary),
             "INVOKED_HASH": str(tmp_path / "invoked-hash")},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    expected = hashlib.sha256(original.encode()).hexdigest()
    assert (tmp_path / "invoked-hash").read_text().split()[0] == expected
    assert wrapper.read_text() == f"export TUNA_LIVE_ENGINE_DIGEST=sha256:{expected}\n"
    assert hashlib.sha256(binary.read_bytes()).hexdigest() != expected
    snapshots = list(output.glob(".tacklebox-exec.*"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text() == original
    assert snapshots[0].stat().st_mode & 0o222 == 0
