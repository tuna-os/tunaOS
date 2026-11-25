"""[installer_medium] resolves every matrix cell by rule (tunaOS#4905, #4907).

Falsification: an unknown frontend, a desktop with neither a frontend nor a
headless entry, a promoted cell with no evidence, a declared layout that
contradicts the evidence, an EL10 cell declared on btrfs, a non-EL cell
declared on xfs, an unknown variant, flavor or sibling desktop, a duplicate
cell, a branch ref instead of a commit, or a chunk above the 256 MiB contract
cap all fail validation.
"""

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


config = module("installer_medium_config", ROOT / "scripts/lib/tunaos_config.py")
medium = config.installer_medium_policy()

PROMOTED = [
    "albacore:gnome",
    "bonito:gnome",
    "bonito:cosmic",
    "bonito:kde",
    "bonito:niri",
    "bonito:xfce",
    "tromso:kde",
]
GRUB_OSTREE = {"bootloader": "grub2", "composeFsBackend": "false"}


def record(cell, filesystem="btrfs", os_release="ID=fedora\n", **probe):
    return {
        "cell": cell,
        "image": "example.invalid/x",
        "digest": "sha256:" + "0" * 64,
        "read": "2026-11-25",
        "facts": {"os_release": os_release},
        "probe": {**GRUB_OSTREE, "filesystem": filesystem, **probe},
    }


def layout(row):
    return {key: row[key] for key in ("filesystem", "bootloader", "backend")}


def by_cell(rows):
    return {row["cell"]: row for row in rows}


def test_done_when_promoted_cells_resolve():
    source = config.load()
    assert layout(medium.cell(source, "albacore:gnome")) == {
        "filesystem": "xfs",
        "bootloader": "grub",
        "backend": "ostree",
    }
    tromso = medium.cell(source, "tromso:kde")
    # Kernel 6.19.11 is older than the btrfs fs-verity fix, so the probe says ext4.
    assert layout(tromso) == {"filesystem": "ext4", "bootloader": "systemd-boot", "backend": "composefs"}
    assert tromso["source"] == "probe" and tromso["frontend"] == "kde"
    assert tromso["image"] == "ghcr.io/tuna-os/tromso:latest" and tromso["secure_boot"] == "tunaos-key"
    brussels = medium.cell(source, "brussels:xfce")
    assert layout(brussels) == layout(tromso) and brussels["frontend"] == "xfce"
    # The sibling record keeps its old id and image; `installer_id` names the cell.
    assert brussels["image"] == "ghcr.io/tuna-os/xfce-linux:latest"
    assert brussels["secure_boot"] == "tunaos-key" and brussels["status"] == "supported"
    for desktop in ("gnome", "kde", "cosmic", "niri", "xfce"):
        row = medium.cell(source, f"bonito:{desktop}")
        assert layout(row) == {"filesystem": "btrfs", "bootloader": "grub", "backend": "ostree"}
        assert row["source"] == "probe" and row["digest"].startswith("sha256:")


def test_the_nightly_is_exactly_the_seven_promoted_cells():
    promoted = medium.cells(config.load(), promoted_only=True)
    assert [row["cell"] for row in promoted] == PROMOTED
    assert all(row["status"] == "promoted" for row in promoted)


def test_a_tree_without_the_evidence_file_still_loads_its_config(monkeypatch, tmp_path):
    source = config.load()
    monkeypatch.setattr(medium, "EVIDENCE", tmp_path / "absent.json")
    assert medium.validate(source) is source["installer_medium"]
    rows = by_cell(medium.resolve(source, evidence={}, strict=False))
    assert rows["bonito:gnome"]["status"] == "unverified" and not rows["bonito:gnome"]["promoted"]
    with pytest.raises(medium.MediumError, match="unverified"):
        medium.resolve(source, evidence={})


def test_every_matrix_flavor_has_exactly_one_row():
    source = config.load()
    rows = medium.resolve(source)
    expected = [
        f"{name}:{flavor['id']}" for name, variant in source["variants"].items() for flavor in variant["flavors"]
    ]
    assert [row["cell"] for row in rows] == [*expected, "tromso:kde", "brussels:xfce"]
    assert {row["status"] for row in rows} <= set(medium.STATUSES)


def test_desktop_to_frontend_map():
    rows = by_cell(medium.resolve(config.load()))
    for cell, frontend, installer in (
        ("yellowfin:gnome", "gnome", "gnome-setup"),
        ("yellowfin:tuna", "tuna", "gnome-setup"),
        ("gurnard:pantheon", "pantheon", "gnome-setup"),
        ("bonito:kde", "kde", "org.tunaos.InstallerKde"),
        ("bonito:cosmic", "cosmic", "org.tunaos.InstallerCosmic"),
        ("bonito:niri", "niri", "org.tunaos.InstallerNiri"),
        ("bonito:xfce", "xfce", "org.tunaos.InstallerXfce"),
    ):
        assert (rows[cell]["frontend"], rows[cell]["installer"]) == (frontend, installer)


def test_hardware_suffixes_use_the_frontend_of_their_desktop():
    rows = by_cell(medium.resolve(config.load()))
    for cell, frontend in (
        ("yellowfin:gnome-hwe", "gnome"),
        ("bonito:kde-nvidia", "kde"),
        ("bonito:gnome-asahi", "gnome"),
        ("bonito:gnome-x13s", "gnome"),
        ("yellowfin:gnome-nvidia-hwe", "gnome"),
        ("marlin:niri-cachyos", "niri"),
        ("grouper:gnome-zfs", "gnome"),
    ):
        assert rows[cell]["frontend"] == frontend
    assert rows["bonito:gnome-x13s"]["architectures"] == ["arm64"]
    assert rows["yellowfin:gnome"]["architectures"] == ["amd64"]


def test_every_frontend_directory_exists_and_is_executable():
    for frontend in medium.FRONTENDS:
        script = ROOT / "installer-medium/frontends" / frontend / "install.sh"
        assert script.is_file() and script.stat().st_mode & 0o111, script
    source = config.load()
    assert set(source["installer_medium"]["frontends"].values()) <= set(medium.FRONTENDS)


def test_base_flavors_get_no_medium():
    source = config.load()
    rows = by_cell(medium.resolve(source))
    headless = [row for row in rows.values() if row["desktop"] == "base"]
    assert headless and all(row["status"] == "no-medium" and row["frontend"] is None for row in headless)
    with pytest.raises(medium.MediumError, match="no-medium"):
        medium.cell(source, "bonito:base")
    assert "bonito:base-hwe" not in {c["cell"] for c in medium.scan_candidates(source)}


def test_a_flavor_that_is_not_built_is_unverified_with_the_reason():
    source = config.load()
    row = by_cell(medium.resolve(source))["flounder:gnome"]
    assert row["status"] == "unverified" and "build_image is false" in row["reason"]
    with pytest.raises(medium.MediumError, match="unverified"):
        medium.cell(source, "flounder:gnome")


def test_a_cell_without_evidence_is_unverified_never_guessed():
    source = config.load()
    source["installer_medium"]["cells"] = [c for c in source["installer_medium"]["cells"] if "reason" in c]
    rows = by_cell(medium.resolve(source, evidence={}))
    assert rows["bonito:gnome"]["status"] == "unverified"
    assert rows["bonito:gnome"]["bootloader"] is None and rows["bonito:gnome"]["backend"] is None
    assert "no evidence record" in rows["bonito:gnome"]["reason"]
    # The EL10 filesystem is policy, so it is known without an image.
    assert rows["albacore:gnome"]["filesystem"] == "xfs" and rows["bonito:gnome"]["filesystem"] is None
    # The declared sibling cell needs no evidence.
    assert rows["tromso:kde"]["status"] == "promoted"


def test_an_unreadable_image_keeps_its_reason():
    source = config.load()
    source["installer_medium"]["cells"] = [c for c in source["installer_medium"]["cells"] if "reason" in c]
    evidence = {"bonito:gnome": {"cell": "bonito:gnome", "unverified": "image not published: HTTP 404"}}
    row = by_cell(medium.resolve(source, evidence=evidence))["bonito:gnome"]
    assert row["status"] == "unverified" and row["reason"] == "image not published: HTTP 404"


def test_filesystem_policy_from_the_probe_result():
    source = config.load()
    source["installer_medium"]["cells"] = [c for c in source["installer_medium"]["cells"] if "reason" in c]
    evidence = {
        "bonito:gnome": record("bonito:gnome"),
        # A composefs image on a kernel without the fs-verity fix: ext4.
        "bonito:kde": record("bonito:kde", "ext4", bootloader="systemd", composeFsBackend="true"),
        "albacore:gnome": record("albacore:gnome", "xfs", os_release='ID="almalinux"\nID_LIKE="rhel centos fedora"\n'),
        # hummingbird is not an EL10 base image, but its ID_LIKE has rhel.
        "hummingbird:gnome": record("hummingbird:gnome", "xfs", os_release='ID=hummingbird\nID_LIKE="fedora rhel"\n'),
        # xfs with no EL word: the probe did not know the family.
        "marlin:gnome": record("marlin:gnome", "xfs", os_release="ID=mystery\n"),
        # A sealed EL10 image: the probe says ext4, the policy says xfs.
        "yellowfin:gnome": record("yellowfin:gnome", "ext4", os_release="ID=almalinux\n"),
    }
    rows = by_cell(medium.resolve(source, evidence=evidence))
    assert layout(rows["bonito:gnome"]) == {"filesystem": "btrfs", "bootloader": "grub", "backend": "ostree"}
    assert layout(rows["bonito:kde"]) == {"filesystem": "ext4", "bootloader": "systemd-boot", "backend": "composefs"}
    assert rows["albacore:gnome"]["filesystem"] == "xfs" and rows["albacore:gnome"]["status"] == "supported"
    assert rows["hummingbird:gnome"]["filesystem"] == "xfs" and rows["hummingbird:gnome"]["status"] == "supported"
    assert rows["marlin:gnome"]["status"] == "unverified" and "does not know" in rows["marlin:gnome"]["reason"]
    assert rows["yellowfin:gnome"]["status"] == "unverified" and "sealed" in rows["yellowfin:gnome"]["reason"]


def test_a_declared_ext4_may_replace_a_measured_btrfs():
    source = config.load()
    source["installer_medium"]["cells"] = [
        {"cell": "bonito:gnome", "filesystem": "ext4", "reason": "test"},
    ]
    row = by_cell(medium.resolve(source, evidence={"bonito:gnome": record("bonito:gnome")}))["bonito:gnome"]
    assert row["filesystem"] == "ext4" and row["source"] == "probe" and row["status"] == "supported"


@pytest.mark.parametrize(
    "entry",
    [
        {"cell": "bonito:gnome", "bootloader": "systemd-boot", "reason": "r"},
        {"cell": "bonito:gnome", "backend": "composefs", "reason": "r"},
        {"cell": "bonito:gnome", "filesystem": "xfs", "reason": "r"},
        # No evidence for these cells: a partial layout, a wrong filesystem
        # for the base, a promotion with nothing behind it.
        {"cell": "bonito:kde", "filesystem": "btrfs", "reason": "r"},
        {"cell": "bonito:kde", "filesystem": "xfs", "bootloader": "grub", "backend": "ostree", "reason": "r"},
        {"cell": "albacore:kde", "filesystem": "btrfs", "bootloader": "grub", "backend": "ostree", "reason": "r"},
        {"cell": "bonito:kde", "promoted": True},
        {"cell": "flounder:gnome", "filesystem": "btrfs", "bootloader": "grub", "backend": "ostree", "reason": "r"},
        {"cell": "bonito:base", "promoted": True},
    ],
)
def test_explicit_rows_are_checked_against_evidence_and_policy(entry):
    source = config.load()
    source["installer_medium"]["cells"] = [entry]
    with pytest.raises(medium.MediumError):
        medium.resolve(source, evidence={"bonito:gnome": record("bonito:gnome")})


def test_pin_is_a_main_commit_past_encrypted_root():
    source = config.load()
    policy = source["installer_medium"]
    assert policy["systemd_repo"] == "https://github.com/systemd/systemd.git"
    assert len(policy["systemd_ref"]) == 40
    assert policy["chunk_bytes"] <= medium.MAX_CHUNK_BYTES


def test_fisherman_ref_is_a_commit_on_the_live_repo():
    policy = config.load()["installer_medium"]
    assert policy["fisherman_repo"] == "https://github.com/tuna-os/fisherman.git"
    assert len(policy["fisherman_ref"]) == 40


def test_unknown_cell_lookup_fails():
    with pytest.raises(medium.MediumError, match="no cell"):
        medium.cell(config.load(), "bonito:plasma")


def declared(policy, name):
    return next(c for c in policy["cells"] if c["cell"] == name)


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(schema_version=1),
        lambda p: p.update(systemd_repo="git@github.com:systemd/systemd.git"),
        lambda p: p.update(systemd_ref="main"),
        lambda p: p.update(systemd_ref="5371d8fe"),
        lambda p: p.update(fisherman_ref="dev"),
        lambda p: p.update(fisherman_ref="2fc33965"),
        lambda p: p.update(fisherman_repo="git@github.com:tuna-os/fisherman.git"),
        lambda p: p.update(fisherman_repo="https://github.com/projectbluefin/fisherman.git"),
        lambda p: p.pop("fisherman_ref"),
        lambda p: p.pop("frontends"),
        lambda p: p.pop("headless"),
        lambda p: p["cells"].append({"cell": "bonito:base", "promoted": True}),
        lambda p: p.update(chunk_bytes=1 << 20 - 1),
        lambda p: p.update(chunk_bytes=(256 << 20) + 1),
        lambda p: p.update(cells=[]),
        lambda p: p["cells"].append(copy.deepcopy(p["cells"][0])),
        lambda p: p["cells"][0].update(cell="no-such-variant:gnome"),
        lambda p: p["cells"][0].update(cell="albacore:no-such-flavor"),
        lambda p: p["cells"][0].update(cell="tromso:gnome"),
        lambda p: p["cells"][0].update(cell="not-a-cell"),
        lambda p: p["cells"][0].update(promoted="yes"),
        lambda p: p["cells"].append({"cell": "bonito:gnome-hwe"}),
        lambda p: p["cells"][0].update(filesystem="btrfs", reason="r"),
        lambda p: p["cells"][0].update(filesystem="ext4"),
        lambda p: p["cells"][0].update(reason="a reason with no layout"),
        lambda p: declared(p, "tromso:kde").update(bootloader="shim"),
        lambda p: declared(p, "tromso:kde").update(backend="zfs"),
        lambda p: declared(p, "tromso:kde").update(filesystem="xfs"),
        lambda p: declared(p, "tromso:kde").update(filesystem="btrfs"),
        lambda p: declared(p, "tromso:kde").update(secure_boot="mok"),
        lambda p: declared(p, "albacore:gnome").update(secure_boot="tunaos-key"),
        lambda p: declared(p, "tromso:kde").pop("reason"),
        # The dispatcher has no default: an unmapped desktop is an error.
        lambda p: p["frontends"].pop("niri"),
        lambda p: p["frontends"].update(kde="plasma"),
        lambda p: p.update(headless=["base", "kde"]),
        lambda p: p.update(headless=[]),
    ],
)
def test_invalid_medium_declarations_fail_closed(change):
    source = config.load()
    change(source["installer_medium"])
    with pytest.raises((medium.MediumError, config.ConfigError)):
        config.validate(source)


def test_a_sibling_without_evidence_must_declare_the_whole_layout():
    source = config.load()
    source["installer_medium"]["cells"] = [c for c in source["installer_medium"]["cells"] if "reason" in c]
    declared(source["installer_medium"], "tromso:kde").pop("backend")
    with pytest.raises(medium.MediumError, match="must all be declared"):
        medium.resolve(source, evidence={})


def test_secure_boot_mode_is_optional_and_reaches_the_row():
    source = config.load()
    rows = by_cell(medium.resolve(source))
    assert rows["albacore:gnome"]["secure_boot"] is None
    declared(source["installer_medium"], "albacore:gnome").update(secure_boot="distro-chain")
    assert by_cell(medium.resolve(source))["albacore:gnome"]["secure_boot"] == "distro-chain"
