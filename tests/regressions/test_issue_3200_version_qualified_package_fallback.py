"""tunaOS#3200: version-qualified Hummingbird packages survive fallback discovery.

Hummingbird's first desktop transaction can fail for an unrelated package and
retry through ``install_available``.  ``dnf repoquery --qf '%{name}'`` reports
the bare name for a version-qualified request, so comparing that output with
the full request used to demote an available pinned Tuna package to the
wishlist and omit it from the retry.

Falsification: behavioural -- the harness returns the bare name for the first
repoquery format and the exact name-version-release tuple for the second.  If
the fallback only accepts bare names, the install stub is never called with
the pinned request.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "build_scripts" / "lib.sh"
PACKAGE = "tuna-desktop-1.0.0~beta.1-1.bfin1"


def _extract_install_available() -> str:
    source = LIB.read_text(encoding="utf-8")
    match = re.search(r"^install_available\(\) \{.*?^\}$", source, re.M | re.S)
    assert match, "install_available() no longer matches the extracted harness shape"
    return match.group(0)


def test_version_qualified_package_is_installed_by_the_retry(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "install-args"
    dnf = bin_dir / "dnf"
    dnf.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == repoquery ]]; then
  if [[ "$*" == *"%{name}-%{version}-%{release}"* ]]; then
    printf '%s\\n' 'tuna-desktop-1.0.0~beta.1-1.bfin1'
  else
    printf '%s\\n' 'tuna-desktop'
  fi
  exit 0
fi
printf '%s\\n' "$@" > "$TUNAOS_INSTALL_ARGS"
""",
        encoding="utf-8",
    )
    dnf.chmod(0o755)

    script = "\n".join(
        [
            "set -euo pipefail",
            f"export TUNAOS_INSTALL_ARGS={record!s}",
            "export IMAGE_NAME=hummingbird",
            "record_package_wishlist() { :; }",
            _extract_install_available(),
            f"install_available '{PACKAGE}'",
        ]
    )
    result = subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert record.read_text(encoding="utf-8").splitlines()[-1] == PACKAGE
