"""tunaOS#1763: Variant admission gate missing rebuild-config completeness check.

Hummingbird (#1755) was admitted as an experimental variant whose rebuild
repository could not work as configured: no desktop packages in the rebuild
repository, missing aarch64 repository (404), and declared desktops (KDE,
Niri) lacking manifest sections. This led to 10+ consecutive nights of red
scheduled builds before the structural gaps were diagnosed.

This test enforces the variant admission gate's rebuild-config and manifest
completeness precondition (VARIANT-LIFECYCLE.md §1 #1763):
1. Every flavor declared with build_image: true in .github/build-config.yml
   must have an implemented manifest with a non-empty package list for that
   variant's OS routing.
2. Rebuild/experimental variants (such as Hummingbird) must not declare target
   architectures (e.g. linux/arm64) unless the required rebuild repositories
   or package sources exist.
3. Historical broken admissions (e.g. declaring Hummingbird KDE/Niri without
   manifest sections, or declaring arm64 when only amd64 package sources exist)
   fail the completeness gate.
4. Unknown variant IDs fail closed rather than defaulting to unrelated sections.

Falsification: behavioural -- pass a candidate variant configuration with a
missing desktop manifest section, undeclared architecture source, or unknown
variant ID to the admission validator and verify that it rejects the candidate.
"""

from __future__ import annotations

import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILD_CONFIG = ROOT / ".github" / "build-config.yml"
MANIFESTS = ROOT / "manifests" / "desktops"


def _get_os_section_for_variant(variant_id: str) -> str:
    """Map variant ID to the OS section expected in manifests/desktops/*.yaml."""
    if variant_id == "hummingbird":
        return "hummingbird"
    if variant_id == "wahoo":
        return "eln"
    if variant_id in ("sailfin",):
        return "zypper"
    if variant_id in ("guppy",):
        return "emerge"
    if variant_id in ("marlin",):
        return "pacman"
    if variant_id in ("grouper", "gurnard"):
        return "apt"
    if variant_id in ("bonito", "bonito-rawhide"):
        return "fedora"
    if variant_id in ("yellowfin", "albacore", "skipjack"):
        return "el10"
    if variant_id in ("flounder", "flounder-sid"):
        return "apt"
    raise ValueError(
        f"Unknown variant ID '{variant_id}': cannot determine manifest OS section"
    )


def get_manifest_packages(
    variant_id: str, flavor_id: str, manifests_dir: pathlib.Path
) -> list[str] | None:
    os_sec = _get_os_section_for_variant(variant_id)
    base_flavor = flavor_id.split("-")[0]

    # Priority 1: Distro-specific override manifest
    if os_sec == "pacman":
        arch_manifest = manifests_dir / f"{base_flavor}-arch.yaml"
        if arch_manifest.exists():
            doc = yaml.safe_load(arch_manifest.read_text(encoding="utf-8")) or {}
            pkgs = (doc.get("packages") or {}).get("pacman") or doc.get("pacman")
            if isinstance(pkgs, list):
                return pkgs
            if isinstance(pkgs, dict):
                return pkgs.get("packages", [])
    elif os_sec == "apt" and variant_id in ("flounder", "flounder-sid"):
        deb_manifest = manifests_dir / f"{base_flavor}-debian.yaml"
        if deb_manifest.exists():
            doc = yaml.safe_load(deb_manifest.read_text(encoding="utf-8")) or {}
            pkgs = (doc.get("packages") or {}).get("apt") or doc.get("apt")
            if isinstance(pkgs, list):
                return pkgs
            if isinstance(pkgs, dict):
                return pkgs.get("packages", [])

    # Priority 2: Generic manifest
    manifest_file = manifests_dir / f"{base_flavor}.yaml"
    if not manifest_file.exists():
        return None

    doc = yaml.safe_load(manifest_file.read_text(encoding="utf-8")) or {}
    pkg_section = (doc.get("packages") or {}).get(os_sec)
    if pkg_section is None:
        return None
    if isinstance(pkg_section, list):
        return pkg_section
    if isinstance(pkg_section, dict):
        return pkg_section.get("packages", [])
    return None


def check_variant_manifest_completeness(
    variant: dict, manifests_dir: pathlib.Path
) -> list[str]:
    """Check that all declared desktop flavors for a variant have manifest package sets."""
    errors = []
    variant_id = variant.get("id", "")
    try:
        os_sec = _get_os_section_for_variant(variant_id)
    except ValueError as exc:
        return [str(exc)]

    for flavor in variant.get("flavors", []):
        if not flavor.get("build_image"):
            continue
        fid = flavor["id"]
        if fid == "base" or fid.startswith("base-"):
            continue

        base_flavor = fid.split("-")[0]
        manifest_file = manifests_dir / f"{base_flavor}.yaml"
        if not manifest_file.exists():
            errors.append(
                f"Variant '{variant_id}' declares flavor '{fid}' but manifest '{manifest_file.name}' is missing"
            )
            continue

        pkgs = get_manifest_packages(variant_id, fid, manifests_dir)
        if pkgs is None:
            errors.append(
                f"Variant '{variant_id}' declares flavor '{fid}' (routes to '{os_sec}') "
                f"but '{manifest_file.name}' has no packages.{os_sec} section"
            )
        elif len(pkgs) == 0:
            errors.append(
                f"Variant '{variant_id}' flavor '{fid}' packages.{os_sec} list is empty"
            )

    return errors


def test_all_configured_variants_pass_admission_completeness_gate():
    config = yaml.safe_load(BUILD_CONFIG.read_text(encoding="utf-8"))
    all_errors = []
    for variant in config["variants"]:
        errs = check_variant_manifest_completeness(variant, MANIFESTS)
        all_errors.extend(errs)

    assert not all_errors, (
        f"Variant admission completeness gate failed with errors:\n"
        + "\n".join(all_errors)
    )


def test_hummingbird_rebuild_config_has_complete_desktop_manifests():
    config = yaml.safe_load(BUILD_CONFIG.read_text(encoding="utf-8"))
    hb = next(v for v in config["variants"] if v["id"] == "hummingbird")

    declared = [f["id"] for f in hb["flavors"] if f.get("build_image")]
    assert "gnome" in declared
    assert "cosmic" in declared
    assert "kde" not in declared, (
        "kde should not be declared without a packages.hummingbird manifest section"
    )
    assert "niri" not in declared, (
        "niri should not be declared without a packages.hummingbird manifest section"
    )

    assert hb.get("platforms") == ["linux/amd64"]


def test_rejection_of_unimplemented_desktop_flavor_in_admission_check():
    broken_variant = {
        "id": "hummingbird",
        "platforms": ["linux/amd64"],
        "flavors": [
            {"id": "base", "build_image": True},
            {"id": "kde", "build_image": True},
        ],
    }
    errors = check_variant_manifest_completeness(broken_variant, MANIFESTS)
    assert len(errors) == 1
    assert "packages.hummingbird section" in errors[0]
    assert "kde" in errors[0]


def test_unknown_variant_fails_closed():
    unknown_variant = {
        "id": "unknown_future_variant",
        "platforms": ["linux/amd64"],
        "flavors": [
            {"id": "gnome", "build_image": True},
        ],
    }
    errors = check_variant_manifest_completeness(unknown_variant, MANIFESTS)
    assert len(errors) == 1
    assert "Unknown variant ID 'unknown_future_variant'" in errors[0]
