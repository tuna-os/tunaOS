"""Every version pinned next to a sha256 must actually hash to it.

WHY: renovate bumps a version and cannot bump the checksum beside it, so the
pair silently desynchronises. renovate.json already sets `automerge: false`
for these, but that only stops the PR merging itself -- it still needs a human
or an agent to notice.

#2420 is the case: it moved `dms_qml` v1.5.2 -> v1.6.0 and left v1.5.2's
sha256 in place. All 13 of its checks passed, because no PR job builds the
niri EL10 image, so nothing downloaded the tarball and nothing compared it.
The breakage would have surfaced in a nightly, far from the change.

These tests do the comparison at PR time. They are network tests and skip
cleanly when offline or when the asset is unreachable -- a flaky network must
not turn into a red gate, but a genuine mismatch must.
"""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]

# name -> (version key, sha key, URL template, per-arch?)
#
# The URL template gets {version} (as pinned, e.g. "v1.6.0"), {version_num}
# (the same without a leading "v", which is what asset filenames tend to use)
# and {arch} for per-arch pins.
PINNED_DOWNLOADS = {
    "dms_qml": (
        "dms_qml",
        "dms_qml_sha256",
        "https://github.com/AvengeMedia/DankMaterialShell/releases/download/{version}/dms-qml.tar.gz",
        False,
    ),
    # chezmoi pins one checksum PER ARCHITECTURE, and the asset name carries
    # the version without its leading "v" (build_scripts/desktop/niri.sh).
    "chezmoi": (
        "chezmoi",
        "chezmoi_sha256",
        "https://github.com/twpayne/chezmoi/releases/download/{version}/chezmoi_{version_num}_linux_{arch}.deb",
        True,
    ),
    "uupd": (
        "uupd",
        "uupd_sha256",
        "https://github.com/ublue-os/uupd/releases/download/{version}/uupd_Linux_{arch}.tar.gz",
        True,
    ),
}


def _downloads() -> dict:
    return yaml.safe_load((ROOT / "image-versions.yaml").read_text())["downloads"]

UUPD_SERVICE_FILES = ("uupd.service", "uupd.timer", "uupd-manual.service")


def test_every_uupd_service_hash_has_a_case_here() -> None:
    declared = set(_downloads()["uupd_service_hashes"])
    assert declared == set(UUPD_SERVICE_FILES)


@pytest.mark.parametrize("name", UUPD_SERVICE_FILES)
def test_uupd_service_matches_its_checksum(name: str) -> None:
    if os.environ.get("TUNAOS_SKIP_NETWORK_TESTS"):
        pytest.skip("network tests disabled")
    downloads = _downloads()
    version = downloads["uupd"]
    url = f"https://raw.githubusercontent.com/ublue-os/uupd/{version}/{name}"
    try:
        with urllib.request.urlopen(url, timeout=180) as resp:
            digest = hashlib.sha256(resp.read()).hexdigest()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"cannot reach {url}: {exc}")

    assert digest == downloads["uupd_service_hashes"][name], (
        f"{name} is pinned to {version} but its checksum is stale; "
        f"the asset at {url} hashes to {digest}. Bump the version and hash together."
    )


def test_every_sha256_pin_has_a_case_here() -> None:
    """A new `*_sha256` pin must be added above, or it goes unverified.

    Without this, the next hand-pinned download repeats #2420 unnoticed.
    """
    declared = {k for k in _downloads() if k.endswith("_sha256")}
    covered = {sha for _, sha, _, _ in PINNED_DOWNLOADS.values()}
    assert declared <= covered, f"unverified sha256 pins: {sorted(declared - covered)}"


@pytest.mark.parametrize("name", sorted(PINNED_DOWNLOADS))
def test_pinned_version_matches_its_checksum(name: str) -> None:
    if os.environ.get("TUNAOS_SKIP_NETWORK_TESTS"):
        pytest.skip("network tests disabled")
    ver_key, sha_key, url_tmpl, per_arch = PINNED_DOWNLOADS[name]
    downloads = _downloads()
    version = downloads[ver_key]
    version_num = version.lstrip("v")
    expected = downloads[sha_key]

    targets = (
        [(arch, sha) for arch, sha in sorted(expected.items())]
        if per_arch
        else [(None, expected)]
    )

    for arch, want in targets:
        url = url_tmpl.format(version=version, version_num=version_num, arch=arch or "")
        try:
            with urllib.request.urlopen(url, timeout=180) as resp:
                digest = hashlib.sha256(resp.read()).hexdigest()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            pytest.skip(f"cannot reach {url}: {exc}")

        label = f"{name}[{arch}]" if arch else name
        assert digest == want, (
            f"{label} is pinned to {version} but its checksum is {want}; "
            f"the asset at {url} hashes to {digest}. A version bump that leaves "
            "the checksum behind fails the build's verification step -- bump both."
        )
