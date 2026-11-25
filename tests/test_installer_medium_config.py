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
    assert layout(tromso) == {"filesystem": "btrfs", "bootloader": "systemd-boot", "backend": "composefs"}
    assert tromso["source"] == "declared" and tromso["frontend"] == "kde"
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
    # Then the declared sibling cells (tromso:kde; a stacked branch adds more).
    siblings = [c["cell"] for c in source["installer_medium"]["cells"] if c["cell"] not in expected]
    assert "tromso:kde" in siblings
    assert [row["cell"] for row in rows] == [*expected, *siblings]
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


def test_a_sibling_cell_keeps_its_declared_filesystem_when_a_scan_reads_its_image():
    # The probe does not know the OS family of a BuildStream image, so its
    # filesystem answer is the fallback. Bootloader and backend are measured.
    source = config.load()
    evidence = dict(medium.load_evidence())
    evidence["tromso:kde"] = record("tromso:kde", "ext4", os_release="ID=org.freedesktop.platform\n", bootloader="systemd", composeFsBackend="true")
    row = by_cell(medium.resolve(source, evidence=evidence))["tromso:kde"]
    assert layout(row) == {"filesystem": "btrfs", "bootloader": "systemd-boot", "backend": "composefs"}
    assert row["status"] == "promoted" and row["source"] == "probe"
    evidence["tromso:kde"] = record("tromso:kde", "ext4", os_release="ID=org.freedesktop.platform\n")
    with pytest.raises(medium.MediumError, match="contradicts the image evidence"):
        medium.resolve(source, evidence=evidence)


def test_a_distro_chain_row_states_a_measured_gap_in_the_image():
    rows = by_cell(medium.resolve(config.load()))
    # Debian publishes a signed systemd-boot, and the flounder images carry only the unsigned one.
    assert "has no systemd-bootx64.efi.signed" in rows["flounder:kde"]["secure_boot_reason"]
    # Tumbleweed signs in place: there is no separate file to miss.
    assert "not complete" not in rows["sailfin:gnome"]["secure_boot_reason"]


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


def test_secure_boot_mode_follows_the_bootloader_and_the_base():
    rows = by_cell(medium.resolve(config.load()))
    # GRUB cells boot the chain the distribution signs.
    for cell in ("albacore:gnome", "bonito:kde", "wahoo:gnome", "hummingbird:gnome", "bonito-rawhide:gnome"):
        assert (rows[cell]["bootloader"], rows[cell]["secure_boot"], rows[cell]["secure_boot_enroll"]) == (
            "grub",
            "distro-chain",
            None,
        )
    # systemd-boot on the distro chain only where the shim accepts the signed binary.
    for cell in ("flounder:kde", "flounder-sid:gnome", "sailfin:gnome"):
        assert (rows[cell]["bootloader"], rows[cell]["secure_boot"]) == ("systemd-boot", "distro-chain")
    # Nobody signs systemd-boot for these bases: tunaOS CI does, and the key is enrolled if safe.
    for cell in ("marlin:gnome", "guppy:gnome", "grouper:gnome", "gurnard:pantheon", "tromso:kde"):
        assert (rows[cell]["bootloader"], rows[cell]["secure_boot"], rows[cell]["secure_boot_enroll"]) == (
            "systemd-boot",
            "tunaos-key",
            "if-safe",
        )
    for row in rows.values():
        if row["status"] in ("promoted", "supported"):
            assert row["secure_boot"] in medium.SECURE_BOOT and row["secure_boot_reason"]
            if row["secure_boot"] == "tunaos-key":
                assert row["bootloader"] == "systemd-boot"
                assert row["secure_boot_enroll"] in medium.SECURE_BOOT_ENROLL
                assert row["secure_boot_vendor_sha256"] == []
            else:
                assert row["secure_boot_enroll"] is None
        else:
            assert row["secure_boot"] is None


def test_bootloader_target_per_variant():
    targets = {t["variant"]: (t["target"], t["secure_boot"]) for t in medium.bootloader_targets(config.load())}
    assert targets == {
        "yellowfin": ("grub", "distro-chain"),
        "albacore": ("grub", "distro-chain"),
        "skipjack": ("grub", "distro-chain"),
        "wahoo": ("grub", "distro-chain"),
        "bonito": ("grub", "distro-chain"),
        "hummingbird": ("grub", "distro-chain"),
        "bonito-rawhide": ("grub", "distro-chain"),
        "gurnard": ("grub", "distro-chain"),
        "grouper": ("grub", "distro-chain"),
        "stingray": ("grub", "distro-chain"),
        "sailfin": ("systemd-boot", "distro-chain"),
        "flounder": ("systemd-boot", "distro-chain"),
        "flounder-sid": ("systemd-boot", "distro-chain"),
        "marlin": ("systemd-boot", "tunaos-key"),
        "guppy": ("systemd-boot", "tunaos-key"),
    }


def test_the_target_never_changes_a_cell():
    source = config.load()
    rows = by_cell(medium.resolve(source))
    # Ubuntu's target is GRUB, and its images boot systemd-boot today: the cell says today.
    assert rows["grouper:gnome"]["bootloader"] == "systemd-boot"
    # Rawhide publishes a signed systemd-boot that its shim rejects: GRUB stays.
    target = next(t for t in medium.bootloader_targets(source) if t["variant"] == "bonito-rawhide")
    assert target["signed"] == "yes" and target["target"] == "grub" and "rejects" in target["reason"]


@pytest.mark.parametrize(
    "entry",
    [
        # tunaos-key needs systemd-boot.
        {"cell": "bonito:gnome", "secure_boot": "tunaos-key", "secure_boot_reason": "r"},
        # systemd-boot on the distro chain needs shim_accepts = yes (Arch has no shim).
        {"cell": "marlin:gnome", "secure_boot": "distro-chain", "secure_boot_reason": "r"},
        {"cell": "grouper:gnome", "secure_boot": "distro-chain", "secure_boot_reason": "r"},
        # Only a tunaos-key cell enrolls; only a distro-chain cell pins.
        {"cell": "bonito:gnome", "secure_boot": "distro-chain", "secure_boot_enroll": "off", "secure_boot_reason": "r"},
        {"cell": "marlin:gnome", "secure_boot": "tunaos-key", "secure_boot_vendor_sha256": ["a" * 64], "secure_boot_reason": "r"},
        {"cell": "marlin:gnome", "secure_boot": "tunaos-key", "secure_boot_enroll": "always", "secure_boot_reason": "r"},
        {"cell": "bonito:gnome", "secure_boot": "distro-chain", "secure_boot_vendor_sha256": ["abc"], "secure_boot_reason": "r"},
        {"cell": "bonito:gnome", "secure_boot": "distro-chain"},
        {"cell": "bonito:gnome", "secure_boot": "mok", "secure_boot_reason": "r"},
        {"cell": "bonito:gnome", "secure_boot_enroll": "off"},
        {"cell": "bonito:gnome", "secure_boot_reason": "a reason with no mode"},
        # A sibling cell has no base record unless it is mapped: it must declare the mode.
        {"cell": "athens:pantheon", "filesystem": "btrfs", "bootloader": "systemd-boot", "backend": "composefs", "reason": "r"},
    ],
)
def test_secure_boot_declarations_fail_closed(entry):
    source = config.load()
    source["installer_medium"]["cells"] = [entry]
    with pytest.raises(medium.MediumError):
        medium.resolve(source)


def test_bases_toml_of_4958_is_the_authority_when_present(monkeypatch, tmp_path):
    bases = tmp_path / "bases.toml"
    bases.write_text(
        '[[base]]\nname = "Arch Linux"\nshim_accepts = "yes"\nshim_vendor_sha256 = ["' + "b" * 64 + '"]\n'
        '[[base]]\nname = "Debian 13"\nshim_accepts = "no"\nshim_vendor_sha256 = []\n'
    )
    monkeypatch.setattr(medium, "SECURE_BOOT_BASES", bases)
    rows = by_cell(medium.resolve(config.load()))
    assert rows["marlin:gnome"]["secure_boot"] == "distro-chain"
    assert rows["marlin:gnome"]["secure_boot_vendor_sha256"] == ["b" * 64]
    assert rows["flounder:kde"]["secure_boot"] == "tunaos-key"
    # A base the file does not name keeps the record of evidence/bootloader-target.json.
    assert rows["sailfin:gnome"]["secure_boot"] == "distro-chain"


def test_explicit_secure_boot_rows_stay_possible():
    source = config.load()
    pin = "a3b384810d48f1666d5df01c0684c5f5325b57ef5dee5223d9bf66aeefef332e"
    source["installer_medium"]["cells"] = [
        {"cell": "marlin:gnome", "secure_boot": "tunaos-key", "secure_boot_enroll": "manual", "secure_boot_reason": "lab"},
        {"cell": "bonito:gnome", "secure_boot": "distro-chain", "secure_boot_vendor_sha256": [pin], "secure_boot_reason": "pin"},
        {
            "cell": "athens:pantheon",
            "filesystem": "btrfs",
            "bootloader": "systemd-boot",
            "backend": "composefs",
            "reason": "BuildStream image",
            "secure_boot": "tunaos-key",
            "secure_boot_enroll": "off",
            "secure_boot_reason": "BuildStream image",
        },
    ]
    rows = by_cell(medium.resolve(source))
    assert rows["marlin:gnome"]["secure_boot_enroll"] == "manual" and rows["marlin:gnome"]["secure_boot_reason"] == "lab"
    assert rows["bonito:gnome"]["secure_boot_vendor_sha256"] == [pin]
    assert (rows["athens:pantheon"]["status"], rows["athens:pantheon"]["frontend"]) == ("supported", "pantheon")
    assert rows["athens:pantheon"]["secure_boot_enroll"] == "off"


def brussels_row(cell):
    return {
        "cell": cell,
        "filesystem": "btrfs",
        "bootloader": "systemd-boot",
        "backend": "composefs",
        "reason": "BuildStream sibling image",
        "secure_boot": "tunaos-key",
        "secure_boot_reason": "BuildStream image: nobody signs its systemd-boot",
    }


@pytest.mark.parametrize("sibling_id", ["xfce-linux", "brussels"])
@pytest.mark.parametrize("declared_as", ["xfce-linux:xfce", "brussels:xfce"])
def test_brussels_is_the_cell_and_xfce_linux_a_deprecated_alias(sibling_id, declared_as):
    source = config.load()
    for sibling in source["sibling_images"]:
        if sibling["id"] in ("xfce-linux", "brussels"):
            sibling["id"] = sibling_id
    source["installer_medium"]["cells"].append(brussels_row(declared_as))
    for name in ("brussels:xfce", "xfce-linux:xfce"):
        if declared_as == "brussels:xfce" or name == declared_as:
            row = medium.cell(source, name)
            assert row["frontend"] == "xfce" and row["bootloader"] == "systemd-boot"
            assert (row["secure_boot"], row["secure_boot_enroll"]) == ("tunaos-key", "if-safe")
    assert medium.canonical("xfce-linux:xfce") == "brussels:xfce"
    assert medium.canonical("bonito:kde") == "bonito:kde"


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
        lambda p: declared(p, "tromso:kde").pop("backend"),
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
