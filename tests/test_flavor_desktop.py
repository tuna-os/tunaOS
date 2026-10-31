"""A flavor's desktop comes from its [flavor_metadata] entry, not a suffix list.

scripts/lib/flavor-desktop.sh used to strip a hard-coded list of overlay
suffixes, so every new hardware flavor needed a code edit. It now reads
docs/iso-builder.flavors.json. SUFFIX_REFERENCE below is that retired
function, kept only to prove the cutover changed no answer for any configured
non-hardware flavor.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/lib/flavor-desktop.sh"

SUFFIX_REFERENCE = r"""
old_desktop_flavor() {
	local desktop="$1" suffix
	for suffix in -nvidia-hwe -nvidia -hwe -t2 -cachyos -asahi -x13s -zfs; do
		if [[ "$desktop" == *"$suffix" ]]; then
			desktop="${desktop%"$suffix"}"
			break
		fi
	done
	printf '%s\n' "$desktop"
}
"""


def _flavors() -> list[dict]:
    config = tomllib.loads((ROOT / "tunaos.toml").read_text(encoding="utf-8"))
    return [f for v in config["variants"].values() for f in v["flavors"]]


def _run(function: str, flavors: list[str], metadata: Path | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin"}
    if metadata is not None:
        env["TUNAOS_FLAVOR_METADATA"] = str(metadata)
    return subprocess.run(
        ["bash", "-euc", SUFFIX_REFERENCE + f'source "$1"; shift; for f; do {function} "$f"; done',
         "flavor-desktop-test", str(HELPER), *flavors],
        capture_output=True, text=True, env=env,
    )


def test_every_non_hardware_flavor_resolves_as_the_suffix_list_did() -> None:
    ids = sorted({f["id"] for f in _flavors() if "hardware" not in f})
    assert {"gnome-hwe", "gnome-nvidia-hwe", "cosmic-cachyos", "gnome-asahi", "base-nvidia"} <= set(ids)
    old = _run("old_desktop_flavor", ids)
    new = _run("tunaos_desktop_flavor", ids)
    assert new.returncode == 0, new.stderr
    assert dict(zip(ids, new.stdout.split())) == dict(zip(ids, old.stdout.split()))


def test_hardware_flavors_resolve_to_their_configured_desktop() -> None:
    result = _run("tunaos_desktop_flavor", ["gnome-x13s", "gnome-t2"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["gnome", "gnome"]


def test_desktop_is_read_from_metadata_not_the_flavor_name(tmp_path: Path) -> None:
    metadata = tmp_path / "flavors.json"
    metadata.write_text('{"flavors": [{"id": "gnome-newboard", "desktop": "kde"}]}')
    result = _run("tunaos_desktop_flavor", ["gnome-newboard"], metadata)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "kde"


@pytest.mark.parametrize("flavor", ["gnome-unconfigured", ""])
def test_an_unconfigured_flavor_fails_instead_of_guessing(flavor: str) -> None:
    result = _run("tunaos_desktop_flavor", [flavor])
    assert result.returncode != 0
    assert "no [flavor_metadata] entry" in result.stderr
