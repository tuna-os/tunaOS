"""tunaOS#2693: one refused apk download failed the Manifest job, and with it the variant.

The Manifest job installs its tools with apk in the wolfi-base container.
apk.cgr.dev sometimes answers one package download with 401/403, and
apk-tools 2.14 reports that as EACCES:

    (56/69) Installing libgpg-error (1.61-r3)
    ERROR: libgpg-error-1.61-r3: Permission denied
    2 errors; 257 MiB in 88 packages          (exit 2)

Measured on bonito-rawhide base (run 36046888245: stage 2 skipped, all 10
stage-2 ISOs stopped at the provenance gate), flounder-sid kde (run
36083457907, 5 packages, exit 5) and yellowfin gnome-hwe (run 35957716969).
A second `apk add` installs only the packages that the first one did not
install and exits 0 (reproduced against the pinned wolfi-base digest).

Falsification: behavioural. The test runs the step's own shell, up to the
install call, under `sh -e` with a stub apk that refuses the first `add`.
On the unfixed step (`apk update` then one bare `apk add`) the shell exits
2 at the first refusal, and the first test fails.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"
PACKAGES = "jq git podman uutils bash conmon crun netavark fuse-overlayfs libstdc++ yq"

STUB_APK = """#!/bin/sh
state="$STUB_DIR/adds"
case "$1" in
  update) echo "OK: 111076 distinct packages available"; exit 0 ;;
  add)
    n=$(( $(cat "$state" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$state"
    shift
    echo "$*" >> "$STUB_DIR/args"
    if [ "$n" -le "$REFUSALS" ]; then
      echo "ERROR: libgpg-error-1.61-r3: Permission denied" >&2
      echo "1 error; 257 MiB in 88 packages" >&2
      exit 2
    fi
    echo "OK: 261 MiB in 90 packages"
    exit 0 ;;
esac
exit 99
"""


def _install_prefix() -> str:
    """The step's shell up to (not including) the /bin/sh relink.

    Everything after that point rewrites /bin/sh and /etc/containers, which
    must not run on the test host.
    """
    manifest = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["manifest"]
    run = next(s for s in manifest["steps"] if s.get("name") == "Install dependencies")["run"]
    cut = run.index("# Point /bin/sh at bash")
    prefix = run[:cut]
    assert PACKAGES in prefix, "the step no longer installs the package list this test expects"
    return prefix


def _run(tmp_path: Path, refusals: int) -> tuple[subprocess.CompletedProcess, int, list[str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "apk").write_text(STUB_APK)
    (bindir / "apk").chmod(0o755)
    (bindir / "sleep").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "sleep").chmod(0o755)
    env = dict(os.environ)
    env.update(
        PATH=f"{bindir}:{env['PATH']}",
        STUB_DIR=str(tmp_path),
        REFUSALS=str(refusals),
    )
    # `shell: sh -e {0}` is what the job runs under before bash exists.
    proc = subprocess.run(
        ["sh", "-e", "-c", _install_prefix()],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    adds_file = tmp_path / "adds"
    adds = int(adds_file.read_text()) if adds_file.exists() else 0
    args_file = tmp_path / "args"
    args = args_file.read_text().splitlines() if args_file.exists() else []
    return proc, adds, args


def test_one_refused_download_does_not_fail_the_step(tmp_path):
    proc, adds, args = _run(tmp_path, refusals=1)
    assert proc.returncode == 0, (
        f"one refused package download failed Install dependencies "
        f"(exit {proc.returncode}):\n{proc.stdout}{proc.stderr}"
    )
    assert adds == 2, f"expected one retry after the refusal, saw {adds} apk add call(s)"
    assert all(a == PACKAGES for a in args), f"the retry changed the package list: {args}"


def test_a_persistent_refusal_still_fails_and_the_retry_is_bounded(tmp_path):
    proc, adds, _ = _run(tmp_path, refusals=100)
    assert proc.returncode != 0, "apk never succeeded, yet the step reported success"
    assert adds == 4, f"expected 4 bounded attempts, saw {adds}"
    assert "::error::" in proc.stdout, "the final failure is not reported as an error"
