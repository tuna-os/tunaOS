"""tunaOS#3329: desktop builds installed an unverified yq release asset.

The manifest-driven desktop installer downloaded a pinned yq URL directly to
`/usr/bin/yq`, so a replaced release asset could execute as root during an
image build. The installer now selects a reviewed architecture-specific
SHA-256, checks the downloaded file, and atomically renames it into place.

Falsification: structural -- reverting the installer to its former direct
`curl -o /usr/bin/yq` download removes the architecture checksum map and the
per-download `sha256sum -c` gate, so these tests fail before an unverified
binary can be accepted as the build's yq.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"

EXPECTED_CHECKSUMS = {
    "x86_64": (
        "amd64",
        "fa52a4e758c63d38299163fbdd1edfb4c4963247918bf9c1c5d31d84789eded4",
    ),
    "aarch64": (
        "arm64",
        "578648e463a11c1b6db6010cbf41eafed6bee79466fcffa1bb446672cf7945ea",
    ),
}


def _installer_code() -> str:
    return "\n".join(
        line
        for line in INSTALLER.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_desktop_yq_download_has_reviewed_architecture_checksums():
    code = _installer_code()
    assert 'YQ_VERSION="v4.53.3"' in code
    assert '"https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_${YQ_ARCH}"' in code

    for machine, (archive_arch, checksum) in EXPECTED_CHECKSUMS.items():
        branch = re.search(
            rf"{re.escape(machine)}\)\n(?P<body>.*?)\n\s*;;",
            code,
            re.DOTALL,
        )
        assert branch, f"no yq checksum branch for {machine}"
        body = branch.group("body")
        assert f'YQ_ARCH="{archive_arch}"' in body
        assert f'YQ_SHA256="{checksum}"' in body

    assert re.search(
        r"\n\s*\*\)\n\s*echo \"ERROR: no pinned yq checksum for \$\(uname -m\)\"",
        code,
    )


def test_desktop_yq_download_is_verified_before_atomic_install():
    code = _installer_code()
    download = code.index("curl -fsSL")
    verify = code.index("sha256sum -c -", download)
    mode = code.index('chmod 0755 "$YQ_TMP/yq"', verify)
    install = code.index('mv -fT "$YQ_TMP/yq" /usr/bin/yq', mode)

    assert "set -xeuo pipefail" in code
    assert 'YQ_TMP="$(mktemp -d /usr/bin/.yq.XXXXXX)"' in code
    assert '-o "$YQ_TMP/yq"' in code
    assert 'echo "${YQ_SHA256}  $YQ_TMP/yq" | sha256sum -c -' in code
    assert download < verify < mode < install
    assert 'curl -fsSL -o /usr/bin/yq' not in code
