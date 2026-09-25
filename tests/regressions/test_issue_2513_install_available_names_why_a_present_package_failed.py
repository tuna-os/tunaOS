"""tunaOS#2513: hummingbird:cosmic shipped without cosmic-comp, and the log gave the wrong reason.

Build Hummingbird run 35938968035 (2026-09-24, image revision c46f3fc, now
ghcr.io/tuna-os/hummingbird:cosmic) requested cosmic-comp. The repoquery in
install_available found it in the tunaos-hummingbird index. The batch install
and then the per-package install both failed on an rpm file conflict:

    file /usr/lib64/libxml2.so.16 from install of libxml2-2.15.4-1.hum1
    conflicts with file from package libxml2-16-2.15.3-0.1.2.hum1

The per-package loop ran `dnf ... 2>/dev/null || true`, so the log did not
keep that line. The only annotation came from record_package_wishlist:
"cosmic-comp ... is not in the active repos". That statement was false, and
it sent the diagnosis to the package factory, not to the conflict. The
Desktop Contract Sweep (run 36069044544) then reported `missing required
command: cosmic-comp` against the published image.

This test holds that a package that IS in the repos but does not install
from the per-package fallback gets its own annotation, with dnf's reason.

Falsification: behavioural -- the harness runs the real install_available
against a stub dnf that fails cosmic-comp with the measured conflict line.
With the 2>/dev/null loop restored, no "resolves in the active repos"
annotation is printed and the conflict line is not in the output, so both
assertions fail.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "build_scripts" / "lib.sh"

CONFLICT = (
    "  - file /usr/lib64/libxml2.so.16 from install of libxml2-2.15.4-1.hum1.x86_64 "
    "conflicts with file from package libxml2-16-2.15.3-0.1.2.hum1.x86_64"
)


def _extract(name: str) -> str:
    source = LIB.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{$.*?^\}}$", source, re.M | re.S)
    assert match, f"{name}() no longer matches the shape this test extracts"
    return match.group(0)


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("bash", "grep", "cat", "basename", "touch"):
        source = shutil.which(tool)
        assert source, f"{tool} is not on PATH; the harness cannot run"
        (bin_dir / tool).symlink_to(source)
    db = tmp_path / "rpmdb"
    db.mkdir()
    # repoquery: every name resolves. install: the batch fails; one package
    # at a time, cosmic-comp fails on the measured conflict and dconf installs.
    _stub(
        bin_dir / "dnf",
        f"""
if [[ "$1" == repoquery ]]; then echo "${{@: -1}}"; exit 0; fi
pkgs=(); for a in "$@"; do [[ "$a" == -* || "$a" == install ]] || pkgs+=("$a"); done
if (( ${{#pkgs[@]}} > 1 )); then echo "Transaction failed: Rpm transaction failed." >&2; exit 1; fi
if [[ "${{pkgs[0]}}" == cosmic-comp ]]; then
  echo "Transaction failed: Rpm transaction failed." >&2
  echo "{CONFLICT}" >&2
  exit 1
fi
touch "{db}/${{pkgs[0]}}"; echo "Complete!"
""",
    )
    _stub(bin_dir / "rpm", f'[[ -e "{db}/${{@: -1}}" ]]\n')
    script = "\n".join(
        [
            "set -uo pipefail",
            "export IMAGE_NAME=hummingbird",
            "record_package_wishlist() { :; }",
            _extract("install_available"),
            "install_available dconf cosmic-comp",
        ]
    )
    return subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": str(bin_dir)},
        timeout=60,
    )


def test_a_present_package_that_fails_to_install_is_named_with_the_reason(tmp_path):
    result = _run(tmp_path)
    out = result.stdout + result.stderr

    warnings = [ln for ln in out.splitlines() if "resolves in the active repos" in ln]
    assert len(warnings) == 1, out
    assert warnings[0].startswith("::warning"), out
    assert "cosmic-comp" in warnings[0], out
    assert "libxml2.so.16" in warnings[0] and "conflicts with file" in warnings[0], out
    # The package that installed is not reported.
    assert "dconf resolves" not in out, out
