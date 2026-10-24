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
import hashlib
import importlib.util

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
DESKTOPS = ["gnome", "kde", "cosmic", "niri", "xfce"]
POLICY = ROOT / "scripts" / "iso-delivery-policy.py"
PUBLISH_R2 = ROOT / "scripts" / "publish-iso-r2.sh"
SPEC = importlib.util.spec_from_file_location("iso_delivery_policy", POLICY)
POLICY_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(POLICY_MODULE)


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
            sys.executable,
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

def test_matrix_annotation_rejects_non_object_rows(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(_group_policy_config([], [])), encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(POLICY),
            "--config-json",
            str(config_path),
            "annotate-target-matrix",
        ],
        input='{"include":[null]}',
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "matrix include entries must be objects" in result.stderr


@pytest.mark.parametrize(
    "row, reason",
    [
        ({"variant": "", "flavor": "gnome", "platform": "linux/amd64"}, ".variant"),
        ({"variant": "fish", "flavor": 7, "platform": "linux/amd64"}, ".flavor"),
        ({"variant": "fish", "flavor": "gnome", "platform": "linux/riscv64"}, "unsupported"),
    ],
)
def test_target_matrix_annotation_rejects_invalid_identity(tmp_path: Path, row: dict, reason: str):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(_group_policy_config([], [])), encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(POLICY),
            "--config-json",
            str(config_path),
            "annotate-target-matrix",
        ],
        input=json.dumps({"include": [row]}),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert reason in result.stderr


@pytest.mark.parametrize(
    "row, reason",
    [
        ({"platform": "linux/amd64", "required_flavors": ["gnome"]}, ".variant"),
        ({"variant": "fish", "required_flavors": ["gnome"]}, ".platform"),
        ({"variant": "fish", "platform": "linux/riscv64", "required_flavors": ["gnome"]}, ".platform"),
        ({"variant": "fish", "platform": "linux/amd64", "required_flavors": [""]}, "required_flavors"),
        ({"variant": "fish", "platform": "linux/amd64", "required_flavors": [7]}, "required_flavors"),
    ],
)
def test_group_matrix_annotation_rejects_invalid_identity(tmp_path: Path, row: dict, reason: str):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(_group_policy_config([], [])), encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(POLICY),
            "--config-json",
            str(config_path),
            "annotate-group-matrix",
        ],
        input=json.dumps({"include": [row]}),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert reason in result.stderr


def test_nonempty_cutover_is_rejected_until_receipts_are_integrated(tmp_path: Path):
    result = _annotate_group(
        tmp_path,
        _group_policy_config(
            [_qualification("kde"), _qualification("kde-hwe")],
            ["fish-kde-latest.iso", "fish-kde-10.2-x86_64.iso"],
        ),
    )
    assert result.returncode != 0
    assert "#3381" in result.stderr
    assert "current qualification catalog" in result.stderr


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "bait.iso\n+ *\n- retained.iso",
        "bait.iso\r\n+ /retained.iso",
    ],
)
def test_retained_inventory_rejects_filter_injection(unsafe_name):
    with pytest.raises(POLICY_MODULE.PolicyError, match="safe single-line"):
        POLICY_MODULE.retained_isos({"retained_r2_isos": [unsafe_name]})


def test_versioned_target_inventory_does_not_accept_a_sibling_flavor():
    retained = (
        "fish-gnome-latest.iso",
        "fish-gnome-nvidia-10.2-x86_64.iso",
    )
    assert not POLICY_MODULE.has_dated_iso(
        retained, "fish", "gnome", "linux/amd64"
    )
    assert POLICY_MODULE.has_dated_iso(
        retained + ("fish-gnome-10.2-x86_64.iso",),
        "fish",
        "gnome",
        "linux/amd64",
    )


def test_versioned_group_inventory_does_not_accept_a_sibling_group():
    cfg = _group_policy_config([], [])
    active = {
        ("fish", "kde", "linux/amd64"),
        ("fish", "kde-hwe", "linux/amd64"),
    }
    with pytest.raises(POLICY_MODULE.PolicyError, match="versioned ISO"):
        POLICY_MODULE.validate_group_retention(
            cfg,
            active,
            ("fish-kde-latest.iso", "fish-kde-nvidia-10.2-x86_64.iso"),
        )
    POLICY_MODULE.validate_group_retention(
        cfg,
        active,
        ("fish-kde-latest.iso", "fish-kde-10.2-x86_64.iso"),
    )


def test_group_without_a_buildable_live_flavor_requires_no_inventory():
    cfg = {
        "iso_groups": [{
            "suffix": "",
            "flavors": ["gnome-nvidia"],
            "offline_flavors": ["gnome"],
        }],
        "variants": [{
            "id": "grouper",
            "platforms": ["linux/amd64"],
            "flavors": [{"id": "gnome", "build_image": True}],
        }],
    }
    POLICY_MODULE.validate_group_retention(
        cfg, {("grouper", "gnome", "linux/amd64")}, ()
    )


def test_guarded_uploader_never_writes_retained_destinations(tmp_path: Path):
    iso = tmp_path / "fish-gnome-10.2-x86_64.iso"
    iso.write_bytes(b"iso")
    signed_checksum = f"{hashlib.sha256(b'iso').hexdigest()}  {iso.name}\n"
    (tmp_path / f"{iso.name}.sha256").write_text(signed_checksum)
    (tmp_path / f"{iso.name}.sigstore.json").write_text('{"signed":"checksum"}')
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "iso_delivery": {
            "cutover_targets": [],
            "retained_r2_isos": [
                iso.name,
                "fish-gnome-latest.iso",
            ],
        },
        "iso_groups": [],
        "variants": [],
    }))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    rclone_log = tmp_path / "rclone.log"
    capture_dir = tmp_path / "uploaded"
    capture_dir.mkdir()
    rclone = fake_bin / "rclone"
    rclone.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  lsf)\n"
        "    candidate=; for arg in \"$@\"; do case \"$arg\" in /*) candidate=${arg#/};; esac; done\n"
        "    [ \"$candidate\" = \"${RCLONE_EXISTING:-}\" ] && printf '%s\\n' \"$candidate\"; exit 0\n"
        "    ;;\n"
        "  *)\n"
        "    printf '%s\\n' \"$*\" >> \"$RCLONE_LOG\"\n"
        "    before=; last=; for arg in \"$@\"; do before=$last; last=$arg; done\n"
        "    cp \"$before\" \"$CAPTURE_DIR/$(basename \"$last\")\"\n"
        "    ;;\n"
        "esac\n"
    )
    rclone.chmod(0o755)

    result = subprocess.run(
        [
            str(PUBLISH_R2),
            str(iso),
            "fish-gnome-latest.iso",
            str(config_path),
            "R2:bucket/live-isos",
        ],
        cwd=tmp_path,
        env=os.environ | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RCLONE_LOG": str(rclone_log),
            "CAPTURE_DIR": str(capture_dir),
            "TUNAOS_PUBLICATION_ID": "test-run-1",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    uploads = rclone_log.read_text().splitlines()
    assert len(uploads) == 7
    destinations = [upload.rsplit(" ", 1)[-1] for upload in uploads]
    assert not any(destination.endswith(f"/{iso.name}") for destination in destinations)
    assert not any(destination.endswith("/fish-gnome-latest.iso") for destination in destinations)
    snapshot = (
        f"fish-gnome-10.2-x86_64-run-test-run-1-sha256-"
        f"{hashlib.sha256(b'iso').hexdigest()[:16]}.iso"
    )
    latest_snapshot = (
        f"fish-gnome-snapshot-run-test-run-1-sha256-"
        f"{hashlib.sha256(b'iso').hexdigest()[:16]}.iso"
    )
    assert any(destination.endswith(f"/{snapshot}") for destination in destinations)
    assert any(destination.endswith(f"/{latest_snapshot}") for destination in destinations)
    assert any(destination.endswith("/fish-gnome-latest.json")
               for destination in destinations)
    assert (capture_dir / f"{latest_snapshot}.sha256").read_text() == signed_checksum
    assert (capture_dir / f"{latest_snapshot}.sigstore.json").read_text() == (
        tmp_path / f"{iso.name}.sigstore.json"
    ).read_text()
    resolver = json.loads((capture_dir / "fish-gnome-latest.json").read_text())
    assert resolver["iso"] == latest_snapshot
    assert resolver["checksum_subject"] == iso.name

    config_path.write_text(json.dumps({
        "iso_delivery": {
            "cutover_targets": [],
            "retained_r2_isos": ["fish-gnome-latest.iso"],
        },
        "iso_groups": [],
        "variants": [],
    }))
    result = subprocess.run(
        [
            str(PUBLISH_R2),
            str(iso),
            "fish-gnome-latest.iso",
            str(config_path),
            "R2:bucket/live-isos",
        ],
        cwd=tmp_path,
        env=os.environ | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RCLONE_LOG": str(rclone_log),
            "CAPTURE_DIR": str(capture_dir),
            "TUNAOS_PUBLICATION_ID": "test-run-2",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    uploads = rclone_log.read_text().splitlines()
    assert len(uploads) == 14
    second_destinations = [
        upload.rsplit(" ", 1)[-1] for upload in uploads[7:]
    ]
    assert any(destination.endswith(f"/{iso.name}") for destination in second_destinations)
    assert not any(destination.endswith("/fish-gnome-latest.iso")
                   for destination in second_destinations)
    assert any(destination.endswith("/fish-gnome-latest.json")
               for destination in second_destinations)


def test_snapshot_reactivation_fails_closed(tmp_path: Path):
    iso = tmp_path / "fish-gnome-10.2-x86_64.iso"
    iso.write_bytes(b"iso")
    checksum = hashlib.sha256(b"iso").hexdigest()
    (tmp_path / f"{iso.name}.sha256").write_text(f"{checksum}  {iso.name}\n")
    (tmp_path / f"{iso.name}.sigstore.json").write_text("{}")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "iso_delivery": {
            "cutover_targets": [],
            "retained_r2_isos": [iso.name, "fish-gnome-latest.iso"],
        },
        "iso_groups": [],
        "variants": [],
    }))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture_dir = tmp_path / "uploaded"
    capture_dir.mkdir()
    rclone_log = tmp_path / "rclone.log"
    rclone = fake_bin / "rclone"
    rclone.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  lsf)\n"
        "    candidate=; for arg in \"$@\"; do case \"$arg\" in /*) candidate=${arg#/};; esac; done\n"
        "    [ \"$candidate\" = \"${RCLONE_EXISTING:-}\" ] && printf '%s\\n' \"$candidate\"\n"
        "    ;;\n"
        "  *)\n"
        "    printf '%s\\n' \"$*\" >> \"$RCLONE_LOG\"\n"
        "    before=; last=; for arg in \"$@\"; do before=$last; last=$arg; done\n"
        "    cp \"$before\" \"$CAPTURE_DIR/$(basename \"$last\")\"\n"
        "    ;;\n"
        "esac\n"
    )
    rclone.chmod(0o755)
    digest_suffix = checksum[:16]
    existing = (
        f"fish-gnome-snapshot-run-reused-sha256-{digest_suffix}.iso"
    )
    result = subprocess.run(
        [
            str(PUBLISH_R2),
            str(iso),
            "fish-gnome-latest.iso",
            str(config_path),
            "R2:bucket/live-isos",
        ],
        cwd=tmp_path,
        env=os.environ | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RCLONE_LOG": str(rclone_log),
            "CAPTURE_DIR": str(capture_dir),
            "RCLONE_EXISTING": existing,
            "TUNAOS_PUBLICATION_ID": "reused",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "refusing to reactivate existing snapshot object" in result.stderr
    assert not (capture_dir / "fish-gnome-latest.json").exists()
    assert not any(existing in line for line in rclone_log.read_text().splitlines())


def test_routine_publication_keeps_two_iso_copies_and_no_resolver(tmp_path: Path):
    iso = tmp_path / "fish-gnome-10.2-x86_64.iso"
    iso.write_bytes(b"iso")
    digest = hashlib.sha256(b"iso").hexdigest()
    (tmp_path / f"{iso.name}.sha256").write_text(f"{digest}  {iso.name}\n")
    (tmp_path / f"{iso.name}.sigstore.json").write_text("{}")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "iso_delivery": {"cutover_targets": [], "retained_r2_isos": []},
        "iso_groups": [],
        "variants": [],
    }))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    rclone_log = tmp_path / "rclone.log"
    rclone = fake_bin / "rclone"
    rclone.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$RCLONE_LOG\"\n"
    )
    rclone.chmod(0o755)

    result = subprocess.run(
        [
            str(PUBLISH_R2),
            str(iso),
            "fish-gnome-latest.iso",
            str(config_path),
            "R2:bucket/live-isos",
        ],
        cwd=tmp_path,
        env=os.environ | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RCLONE_LOG": str(rclone_log),
            "TUNAOS_PUBLICATION_ID": "routine-run",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    destinations = [
        call.rsplit(" ", 1)[-1] for call in rclone_log.read_text().splitlines()
    ]
    assert len(destinations) == 6
    assert sum(name.endswith(".iso") for name in destinations) == 2
    assert any(name.endswith(f"/{iso.name}") for name in destinations)
    assert any(name.endswith("/fish-gnome-latest.iso") for name in destinations)
    assert not any("-snapshot-" in name for name in destinations)
    assert not any(name.endswith("/fish-gnome-latest.json")
                   for name in destinations)


def test_frozen_resolver_remains_valid_after_later_publication(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "iso_delivery": {
            "cutover_targets": [],
            "retained_r2_isos": ["fish-gnome-latest.iso"],
        },
        "iso_groups": [],
        "variants": [],
    }))
    remote = tmp_path / "remote"
    remote.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    rclone = fake_bin / "rclone"
    rclone.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  lsf) exit 0 ;;\n"
        "  *)\n"
        "    before=; last=; for arg in \"$@\"; do before=$last; last=$arg; done\n"
        "    cp \"$before\" \"$REMOTE/$(basename \"$last\")\"\n"
        "    ;;\n"
        "esac\n"
    )
    rclone.chmod(0o755)

    def publish(directory: Path, content: bytes, publication_id: str) -> dict:
        directory.mkdir()
        iso = directory / "fish-gnome-10.2-x86_64.iso"
        iso.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        (directory / f"{iso.name}.sha256").write_text(
            f"{digest}  {iso.name}\n"
        )
        (directory / f"{iso.name}.sigstore.json").write_text(
            json.dumps({"signed": digest})
        )
        result = subprocess.run(
            [
                str(PUBLISH_R2),
                str(iso),
                "fish-gnome-latest.iso",
                str(config_path),
                "R2:bucket/live-isos",
            ],
            cwd=directory,
            env=os.environ | {
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "REMOTE": str(remote),
                "TUNAOS_PUBLICATION_ID": publication_id,
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads((remote / "fish-gnome-latest.json").read_text())

    # Model prune capturing A's resolver targets, then an identical
    # publication reactivating those bytes while prune still holds its stale
    # candidate set. B must get a new key that stale deletion cannot name.
    resolver_a = publish(tmp_path / "build-a", b"same publication", "run-a")
    stale_prune_candidates = {path.name for path in remote.iterdir()}
    resolver_b = publish(tmp_path / "build-b", b"same publication", "run-b")

    assert resolver_a["iso"] != resolver_b["iso"]
    assert resolver_b["iso"] not in stale_prune_candidates
    for resolver in (resolver_a, resolver_b):
        target = remote / resolver["iso"]
        assert target.exists()
        assert "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest() == (
            resolver["digest"]
        )


def test_guarded_uploader_aborts_before_r2_write_on_invalid_policy(tmp_path: Path):
    iso = tmp_path / "fish-gnome-10.2-x86_64.iso"
    iso.write_bytes(b"iso")
    (tmp_path / f"{iso.name}.sha256").write_text("digest  iso\n")
    (tmp_path / f"{iso.name}.sigstore.json").write_text("{}")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "iso_delivery": {
            "cutover_targets": [],
            "retained_r2_isos": "not-a-list",
        },
        "iso_groups": [],
        "variants": [],
    }))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    rclone_log = tmp_path / "rclone.log"
    rclone = fake_bin / "rclone"
    rclone.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$RCLONE_LOG\"\n")
    rclone.chmod(0o755)

    result = subprocess.run(
        [
            str(PUBLISH_R2),
            str(iso),
            "fish-gnome-latest.iso",
            str(config_path),
            "R2:bucket/live-isos",
        ],
        cwd=tmp_path,
        env=os.environ | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "RCLONE_LOG": str(rclone_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not rclone_log.exists()
    assert "policy is invalid" in result.stderr
