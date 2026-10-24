"""Only the byte-reviewed Chunkah Containerfile receives cache compatibility."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/chunkah-cache-compat.py"
SPEC = importlib.util.spec_from_file_location("chunkah_compat", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
KNOWN = (ROOT / "tests/fixtures/chunkah/Containerfile").read_bytes()


def test_exact_fixture_only_removes_four_redundant_cache_flags():
    assert len(KNOWN) == 2432
    output = MODULE.transform(KNOWN)
    assert output == KNOWN.replace(b"--mount=type=cache,rw,", b"--mount=type=cache,")
    assert output.count(b"--mount=type=bind,target=/run/src,rw") == 1
    assert len(KNOWN) - len(output) == 12


def test_cli_does_not_overwrite_input_or_existing_output(tmp_path):
    source = tmp_path / "Containerfile"
    source.write_bytes(KNOWN)
    result = subprocess.run(
        [sys.executable, HELPER, source, source], check=False, capture_output=True
    )
    assert result.returncode != 0 and source.read_bytes() == KNOWN
    output = tmp_path / "existing"
    output.write_bytes(b"owned")
    result = subprocess.run(
        [sys.executable, HELPER, source, output], check=False, capture_output=True
    )
    assert result.returncode != 0 and output.read_bytes() == b"owned"


@pytest.mark.parametrize("builder", ["podman", "buildah"])
@pytest.mark.parametrize("exit_code", [0, 42])
@pytest.mark.parametrize("supported", [True, False])
def test_real_build_script_uses_compat_file_without_mutating_source(
    tmp_path, builder, exit_code, supported
):
    source = tmp_path / "source"
    source.mkdir()
    original = KNOWN
    (source / "Containerfile").write_bytes(original)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Isolate PATH: the real host must not select an unintended builder.
    for command in (
        "bash",
        "dirname",
        "mktemp",
        "rm",
        "sha256sum",
        "awk",
        "git",
        "cp",
        "chmod",
        "cat",
        "cut",
    ):
        found = shutil.which(command)
        if found:
            (bin_dir / command).symlink_to(found)
    (bin_dir / "python3").symlink_to(sys.executable)
    capture = tmp_path / "capture"
    capture.mkdir()
    stub = bin_dir / builder
    stub.write_text("""#!/usr/bin/env python3
import os, pathlib, sys
args = sys.argv[1:]
if args == ['--version']:
    print(os.environ['MOCK_VERSION'])
    raise SystemExit(0)
out = pathlib.Path(os.environ['CAPTURE'])
out.joinpath('args').write_text('\\n'.join(args))
for i, arg in enumerate(args):
    if arg in ('-f', '--file'):
        path = pathlib.Path(args[i+1]); break
    if arg.startswith('--file='):
        path = pathlib.Path(arg.split('=', 1)[1]); break
else:
    raise SystemExit('missing explicit compatibility Containerfile')
out.joinpath('path').write_text(str(path.resolve()))
out.joinpath('content').write_bytes(path.read_bytes())
raise SystemExit(int(os.environ['BUILD_EXIT']))
""")
    stub.chmod(0o755)
    result = subprocess.run(
        [str(bin_dir / "bash"), str(ROOT / "scripts/build-chunkah.sh"), str(source)],
        env={
            **os.environ,
            "PATH": str(bin_dir),
            "CAPTURE": str(capture),
            "BUILD_EXIT": str(exit_code),
            "MOCK_VERSION": (
                "podman version 4.9.3"
                if builder == "podman"
                else "buildah version 1.33.7 (image-spec 1.1.0)"
            )
            if supported
            else builder + " version 99.0.0",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == exit_code, result.stderr
    assert capture.joinpath("content").read_bytes() == (
        MODULE.transform(original) if supported else original
    )
    assert source.joinpath("Containerfile").read_bytes() == original
    args = capture.joinpath("args").read_text()
    assert "--security-opt=label=disable" in args
    assert "--skip-unused-stages=false" in args
    assert "--privileged" not in args
    build_path = Path(capture.joinpath("path").read_text())
    assert build_path.exists() is (not supported)
    assert "command not found" not in result.stderr


@pytest.mark.parametrize(
    "unknown",
    [
        b"",
        KNOWN + b"\n",
        KNOWN[:-1],
        KNOWN.replace(b"\n", b"\r\n"),
        KNOWN.replace(b"id=cargo", b"id=other"),
        KNOWN.replace(b"type=cache,rw,", b"type=cache,ro,"),
        KNOWN.replace(b"type=cache,rw,", b"type=cache,rw,ro,"),
        KNOWN.replace(b"type=cache,rw,", b"type=cache,rw,readonly,"),
        KNOWN.replace(b"type=cache,rw,", b"type=cache,rw,nosuid,"),
        KNOWN.replace(b"type=cache,rw,", b"type=cache,rw,nodev,"),
        KNOWN.replace(b"type=cache,rw,", b"type=cache,rw,noexec,"),
        KNOWN.replace(b"type=cache,rw,", b"type=cache,"),
        b"# RUN literal comment\n" + KNOWN,
        b"COPY <<EOF /script\n" + KNOWN + b"EOF\n",
        b"ADD <<EOF /script\n" + KNOWN + b"EOF\n",
        b"RUN <<EOF\n" + KNOWN + b"EOF\n",
        b"RUN <<'EOF'\n" + KNOWN + b"EOF\n",
        b"RUN <<-EOF\n" + KNOWN + b"EOF\n",
        b'COPY <<"EOF" /script\n' + KNOWN + b"EOF\n",
        b"COPY file \\\n" + KNOWN,
        b"RUN echo literal \\\n# comment\n" + KNOWN,
        KNOWN.replace(b"RUN --mount=type=cache", b"RUN \\\n# comment\n --mount=type=cache"),
    ],
)
def test_unknown_bytes_fail_before_parse_or_output(tmp_path, unknown):
    with pytest.raises(ValueError, match="unrecognized"):
        MODULE.transform(unknown)
    source = tmp_path / "Containerfile"
    source.write_bytes(unknown)
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, HELPER, source, output], check=False, capture_output=True
    )
    assert result.returncode != 0
    assert not output.exists()
    assert source.read_bytes() == unknown
