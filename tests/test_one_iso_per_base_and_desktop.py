"""One ISO per base+desktop, each embedding its own NVIDIA and HWE flavors.

`iso_groups` already built deduplicated multi-image ISOs — the GNOME group
ships `<variant>.iso` carrying gnome, gnome-hwe, gnome-nvidia and
gnome-nvidia-hwe in one offline store, so a user downloads one ISO and the
installer picks the right image. That is the shape wanted everywhere.

The other four desktops did not have it. They shared a single `community`
group that packed KDE, COSMIC, Niri and XFCE into ONE ISO and carried
`publish: false`, on the reasoning that the browser ISO Builder covers the
long tail on demand so a five-flavor offline store was not worth the storage.

The cost argument was sound; the conclusion was not. Someone who wants KDE
should get a KDE ISO, not a four-desktop ISO and not a browser build step.
And these are deduplicated groups over a shared squashfs, so per-desktop ISOs
do not multiply storage the way per-flavor ISOs did — that was the thing
grouping was introduced to stop.

Guarded by tests because the config is what the whole publish pipeline reads,
and a typo here is a silently missing ISO rather than an error.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
DESKTOPS = ["gnome", "kde", "cosmic", "niri", "xfce"]
POLICY = ROOT / "scripts" / "iso-delivery-policy.py"


def config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def groups() -> list[dict]:
    g = config()["iso_groups"]
    assert g, "iso_groups is empty; every assertion below would be vacuous"
    return g


def test_there_is_one_group_per_desktop():
    by_desktop = {}
    for g in groups():
        # The flagship group's suffix is "" and it is the gnome one.
        desktop = g.get("suffix") or "gnome"
        assert desktop not in by_desktop, f"two groups claim {desktop}"
        by_desktop[desktop] = g
    assert sorted(by_desktop) == sorted(DESKTOPS), sorted(by_desktop)


def test_no_group_packs_more_than_one_desktop():
    """The `community` group put four desktops in one ISO.

    A group is single-desktop when every flavor it names, live and offline,
    starts with that desktop's id.
    """
    for g in groups():
        desktop = g.get("suffix") or "gnome"
        named = list(g["flavors"]) + list(g["offline_flavors"])
        for f in named:
            assert f.split("-")[0] == desktop, (
                f"group {desktop!r} names {f!r} from another desktop"
            )


def test_every_group_embeds_its_own_nvidia_and_hwe():
    """The point of grouping: one download, the installer picks the image."""
    for g in groups():
        desktop = g.get("suffix") or "gnome"
        offline = set(g["offline_flavors"])
        assert desktop in offline, (desktop, offline)
        assert any("nvidia" in f for f in offline), (desktop, offline)
        assert any("hwe" in f for f in offline), (desktop, offline)


def test_every_group_is_published():
    """`publish: false` is what kept four desktops off the download page."""
    for g in groups():
        assert g.get("publish", True) is not False, g


def test_the_live_flavor_is_the_nvidia_one():
    """The ISO boots the NVIDIA image so a machine with the card works on
    first boot; the non-NVIDIA images ride along in the offline store."""
    for g in groups():
        assert g["flavors"], g
        for f in g["flavors"]:
            assert "nvidia" in f, (g.get("suffix"), f)


def test_no_group_names_a_flavor_no_variant_has():
    """A typo here is a silently missing ISO, not an error.

    Both the matrix generator and build-iso-group.sh intersect group flavors
    against each variant's real ones, so a flavor that no variant defines is
    dropped everywhere and the group quietly shrinks or vanishes.
    """
    cfg = config()
    defined = {f["id"] for v in cfg["variants"] for f in v.get("flavors", [])}
    for g in groups():
        for f in list(g["flavors"]) + list(g["offline_flavors"]):
            assert f in defined, f"{f!r} is not a flavor of any variant"


def test_the_intersection_that_makes_partial_variants_safe_still_exists():
    """skipjack has no xfce-nvidia; bonito has no kde-hwe.

    Those groups must shrink or be skipped rather than fail the build. Both
    halves of that are asserted here because a group referencing a flavor a
    variant lacks is now the normal case, not an edge one.
    """
    builder = (ROOT / "scripts" / "build-iso-group.sh").read_text(encoding="utf-8")
    assert "Intersect, preserving group/offline order." in builder
    assert "SELECTED_OFFLINE=()" in builder

    wf = (ROOT / ".github" / "workflows" / "publish-iso-groups.yml").read_text(
        encoding="utf-8")
    assert "iso_groups ∩ variant flavors" in wf
    assert "select(($sel | length) > 0)" in wf


def _qualification(flavor: str) -> dict:
    return {
        "variant": "fish",
        "flavor": flavor,
        "platform": "linux/amd64",
        "qualification": "browser-qualified",
        "qualified_at": "2026-10-18",
        "evidence": f"qualification/fish-{flavor}.json",
    }


def _group_policy_config(targets: list[dict], retained: list[str]) -> dict:
    return {
        "iso_delivery": {
            "cutover_targets": targets,
            "retained_r2_isos": retained,
        },
        "iso_groups": [
            {
                "suffix": "kde",
                "flavors": ["kde"],
                "offline_flavors": ["kde", "kde-hwe"],
            }
        ],
        "variants": [
            {
                "id": "fish",
                "platforms": ["linux/amd64"],
                "flavors": [
                    {"id": "kde", "build_image": True, "build_iso": False},
                    {"id": "kde-hwe", "build_image": True, "build_iso": False},
                ],
            }
        ],
    }


def _annotate_group(tmp_path: Path, config: dict) -> subprocess.CompletedProcess[str]:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    matrix = {
        "include": [
            {
                "variant": "fish",
                "group": "kde",
                "platform": "linux/amd64",
                "required_flavors": ["kde", "kde-hwe"],
            }
        ]
    }
    return subprocess.run(
        [
            str(POLICY),
            "--config-json",
            str(config_path),
            "annotate-group-matrix",
        ],
        input=json.dumps(matrix),
        text=True,
        capture_output=True,
        check=False,
    )


def test_partially_covered_group_keeps_r2_publication(tmp_path: Path):
    result = _annotate_group(
        tmp_path,
        _group_policy_config([_qualification("kde")], []),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["include"][0]["r2_cutover"] is False


def test_fully_covered_group_closes_r2_publication(tmp_path: Path):
    result = _annotate_group(
        tmp_path,
        _group_policy_config(
            [_qualification("kde"), _qualification("kde-hwe")],
            ["fish-kde-latest.iso", "fish-kde-20261018-x86_64.iso"],
        ),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["include"][0]["r2_cutover"] is True


def test_fully_covered_group_requires_retained_r2_inventory(tmp_path: Path):
    result = _annotate_group(
        tmp_path,
        _group_policy_config(
            [_qualification("kde"), _qualification("kde-hwe")],
            [],
        ),
    )
    assert result.returncode != 0
    assert "fully cut-over group" in result.stderr
