"""tunaOS#3664: the Hummingbird base-stage repo shipped with no RPM signing.

build_scripts/10-base-packages.sh wrote /etc/yum.repos.d/tunaos-hummingbird.repo
with gpgcheck=0 and no gpgkey, for a baseurl fetched over the network
(https://repo.tunaos.org/hummingbird/20251124-$basearch/). Both that repo and
its public-key endpoint were measured live (repomd.xml and
https://repo.tunaos.org/public.gpg both returned HTTP 200 at audit time), so a
compromised or replaced RPM served from it could enter every Hummingbird image
with no signature check -- during the base stage, which is the FIRST writer of
this file and runs before install-desktop.sh's gnome/cosmic stage can overwrite
it, and which never runs a desktop stage at all for base/base-hwe/base-nvidia.

docs/HUMMINGBIRD.md and install-desktop.sh's own repo writer
(tuna-os/tunaOS#1655) already state the policy this file was outside of:
gpgcheck=0 is allowed ONLY for a file:// baseurl bind-mounted from a
digest-pinned OCI image, where the digest stands in for the RPM signature.
Anything fetched over the network must carry gpgcheck=1 plus the matching
gpgkey. This test extends that gate to every `*.repo` heredoc
10-base-packages.sh writes, the same way tests/test_build_scripts_remaining.bats
already covers install-desktop.sh's manifest-driven writer.

Falsification: structural -- parses the real heredoc(s) 10-base-packages.sh
writes and asserts gpgcheck=1 plus a gpgkey for every baseurl that is not
file://. Reverting the fix (gpgcheck=0, no gpgkey line, as shipped) trips
every assertion below; confirmed by feeding the pre-fix heredoc text through
the same parser.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_PACKAGES = ROOT / "build_scripts" / "10-base-packages.sh"

# Matches every `cat >some/path.repo <<'REPO' ... REPO` heredoc the script
# writes. The quoted delimiter (<<'REPO') is what makes the body opaque to
# bash -- no variable expansion happens before dnf reads it -- so treating it
# as plain INI text here mirrors how dnf itself will parse the file.
REPO_HEREDOC = re.compile(
    r"cat\s*>\s*(?P<target>\S+\.repo)\s*<<'REPO'\n(?P<body>.*?)\nREPO",
    re.S,
)


def _parse_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("["):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            fields[key.strip()] = value.strip()
    return fields


def repo_blocks(script: str | None = None) -> dict[str, dict[str, str]]:
    """Every `*.repo` heredoc 10-base-packages.sh writes, parsed to fields."""
    text = script if script is not None else BASE_PACKAGES.read_text(encoding="utf-8")
    return {m.group("target"): _parse_fields(m.group("body")) for m in REPO_HEREDOC.finditer(text)}


def test_the_script_still_writes_the_hummingbird_repo():
    """Sanity: fails loudly, not vacuously, if the heredoc is renamed or the
    regex below stops matching -- otherwise the gate tests would pass on an
    empty set and prove nothing."""
    blocks = repo_blocks()
    assert "/etc/yum.repos.d/tunaos-hummingbird.repo" in blocks, (
        "no *.repo heredoc for tunaos-hummingbird found in 10-base-packages.sh"
    )


def test_every_network_repo_this_script_writes_requires_gpgcheck():
    """The package-admission gate, extended to 10-base-packages.sh: any
    `*.repo` heredoc for a baseurl that is not file:// must require RPM
    signature verification. The file:// digest-pinned exception
    (tuna-os/tunaOS#1655) stays scoped to file:// and is untouched here."""
    blocks = repo_blocks()
    assert blocks, "no *.repo heredoc found at all -- the regex is the thing under test"
    for target, fields in blocks.items():
        baseurl = fields.get("baseurl", "")
        if baseurl.startswith("file://"):
            continue
        assert fields.get("gpgcheck") == "1", (
            f"{target}: baseurl={baseurl!r} is fetched over the network and must "
            f"set gpgcheck=1 (got gpgcheck={fields.get('gpgcheck')!r})"
        )
        assert fields.get("gpgkey", "").startswith("https://"), (
            f"{target}: gpgcheck=1 with no gpgkey verifies nothing against any key "
            f"(got gpgkey={fields.get('gpgkey')!r})"
        )


def test_the_hummingbird_repo_specifically_uses_the_published_tunaos_key():
    fields = repo_blocks()["/etc/yum.repos.d/tunaos-hummingbird.repo"]
    assert fields["baseurl"].startswith("https://repo.tunaos.org/hummingbird/")
    assert fields["gpgcheck"] == "1"
    # Same key install-desktop.sh's writer uses for every other repo.tunaos.org
    # consumer (tuna-os/tunaOS#1655) -- one published key, not a new exception.
    assert fields["gpgkey"] == "https://repo.tunaos.org/public.gpg"


def test_the_parser_catches_the_shape_this_file_actually_shipped():
    """Confirms the Falsification claim directly: the exact heredoc body this
    file shipped before the fix (gpgcheck=0, no gpgkey) fails the gate above."""
    shipped = (
        "\tcat >/etc/yum.repos.d/tunaos-hummingbird.repo <<'REPO'\n"
        "[tunaos-hummingbird]\n"
        "name=TunaOS Hummingbird published packages\n"
        "baseurl=https://repo.tunaos.org/hummingbird/20251124-$basearch/\n"
        "enabled=1\n"
        "gpgcheck=0\n"
        "priority=5\n"
        "REPO\n"
    )
    fields = repo_blocks(shipped)["/etc/yum.repos.d/tunaos-hummingbird.repo"]
    assert fields["gpgcheck"] == "0"
    assert "gpgkey" not in fields
