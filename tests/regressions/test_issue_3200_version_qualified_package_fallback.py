"""tunaOS#3200: version-qualified Hummingbird packages survive fallback discovery.

Hummingbird's first desktop transaction can fail for an unrelated package and
retry through ``install_available``.  ``dnf repoquery --qf '%{name}'`` reports
the bare name for a version-qualified request, so comparing that output with
the full request used to demote an available pinned Tuna package to the
wishlist and omit it from the retry.

Falsification: behavioural -- the harness returns the exact tuple requested
from one repoquery call. Both ordinary name-version-release and
name-epoch:version-release requests must reach the install command unchanged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "build_scripts" / "lib.sh"
PACKAGES = (
    "tuna-desktop-1.0.0~beta.1-1.bfin1",
    "tuna-desktop-1:1.0.0~beta.1-1.bfin1",
)


def _extract_install_available() -> str:
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1" >/dev/null 2>&1; declare -f install_available',
            "build_scripts/lib.sh",
            str(LIB),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.startswith("install_available ()"), (
        "lib.sh no longer exposes install_available as a shell function"
    )
    return result.stdout


@pytest.mark.parametrize("package", PACKAGES)
def test_version_qualified_package_is_installed_by_the_retry(
    tmp_path: Path, package: str
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "install-args"
    dnf = bin_dir / "dnf"
    dnf.write_text(
        f"""#!/usr/bin/env bash
if [[ "$1" == repoquery ]]; then
  [[ "$*" == *"%{{epoch}}:%{{version}}-%{{release}}"* ]] || exit 2
  printf '%s\\n' '{package}'
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
            f"install_available '{package}'",
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
    assert record.read_text(encoding="utf-8").splitlines()[-1] == package
