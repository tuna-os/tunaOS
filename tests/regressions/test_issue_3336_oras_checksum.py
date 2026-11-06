"""tunaOS#3336: ORAS release archives must be checksum-verified before extraction.

Workflows used to pipe the ORAS release archive straight into `sudo tar`, so a
replaced release asset ran as root on the runner. Every workflow now installs
ORAS through .github/scripts/install-oras.sh, which pins a SHA-256 per
version/arch and verifies it before extracting.

Falsification: structural — reintroducing a direct ORAS download in any
workflow, or removing/reordering the checksum gate in the helper, fails here.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github" / "scripts" / "install-oras.sh"
ORAS_RELEASE = "oras-project/oras/releases"


def _gh_files():
    for pattern in ("workflows/*.yml", "workflows/*.yaml", "actions/**/*.yml"):
        yield from sorted((ROOT / ".github").glob(pattern))


def test_no_workflow_downloads_oras_directly():
    offenders = [
        str(p.relative_to(ROOT))
        for p in _gh_files()
        if ORAS_RELEASE in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"download ORAS via install-oras.sh, not inline: {offenders}"


def test_no_oras_archive_piped_into_tar():
    pipe = re.compile(r"oras_[^\n]*\.tar\.gz[^\n]*\\?\n?[^\n]*\|\s*(sudo\s+)?tar")
    offenders = [
        str(p.relative_to(ROOT))
        for p in _gh_files()
        if pipe.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders


def test_oras_installs_go_through_the_helper():
    users = [
        p
        for p in (ROOT / ".github" / "workflows").glob("*.yml")
        if re.search(r"^\s*(?:#.*)?\s*oras (login|push|pull)\b",
                     p.read_text(encoding="utf-8"), re.M)
    ]
    assert users, "expected workflows that use oras"
    for p in users:
        text = p.read_text(encoding="utf-8")
        # A workflow that installs oras at all must do so via the helper.
        if re.search(r"Install oras|command -v oras", text):
            assert ".github/scripts/install-oras.sh" in text, p.name


def test_helper_pins_digests_and_verifies_before_extracting():
    text = HELPER.read_text(encoding="utf-8")
    digests = re.findall(r'sha256="([0-9a-f]+)"', text)
    assert digests and all(len(d) == 64 for d in digests)
    # Digests of the archives the workflows use (upstream checksums assets).
    assert "5b3f1cbb86d869eee68120b9b45b9be983f3738442f87ee5f06b00edd0bab336" in text
    assert "27df680a39fc2fcedc549cb737891623bc696c9a92a03fd341e9356a35836bae" in text
    assert "6cdc692f929100feb08aa8de584d02f7bcc30ec7d88bc2adc2054d782db57c64" in text
    assert text.index("sha256sum -c -") < text.index("tar -xzf")
    assert "set -euo pipefail" in text
    # Unknown version/arch fails closed rather than skipping verification.
    assert re.search(r"\*\)[^;]*\n[^;]*exit 1", text)


def test_workflow_call_sites_use_pinned_versions():
    helper_keys = set(
        re.findall(r"^\s*(\d+\.\d+\.\d+_\w+)\)", HELPER.read_text(encoding="utf-8"), re.M)
    )
    assert helper_keys
    pairs = set()
    for p in (ROOT / ".github" / "workflows").glob("*.yml"):
        for m in re.finditer(
            r"install-oras\.sh\s+(\d+\.\d+\.\d+)\s+(\S+)", p.read_text(encoding="utf-8")
        ):
            pairs.add((m.group(1), m.group(2).strip('"')))
    assert pairs, "no install-oras.sh call sites found"
    for version, arch in pairs:
        if arch.startswith("$"):  # matrix arch, covered by the amd64/arm64 rows
            continue
        assert f"{version}_{arch}" in helper_keys, (version, arch)
