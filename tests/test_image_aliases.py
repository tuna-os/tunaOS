"""Friendly image aliases must be unambiguous.

Each variant may declare `aliases:` — friendly names the same digest is also
published under, so users need not know the fish names (grouper -> ubuntu).
The alias is additive: canonical `<variant>:<flavor>` tags are unchanged.

The hazard is collision. Two variants sharing an alias would race for the same
`<alias>:<tag>`, and whichever built last would silently win — a published tag
pointing at a different distro than the user asked for. bonito/bonito-rawhide
and flounder/flounder-sid legitimately share an alias and are kept apart by
`tag_suffix`; this test is what stops a future variant breaking that.
"""
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[1] / ".github" / "build-config.yml"


def _config():
    return yaml.safe_load(CONFIG.read_text())


def test_no_two_variants_claim_the_same_alias_tag():
    seen: dict[tuple[str, str], str] = {}
    for variant in _config()["variants"]:
        suffix = variant.get("tag_suffix") or ""
        for alias in variant.get("aliases", []) or []:
            for flavor in variant.get("flavors", []):
                tag = flavor["id"] + (f"-{suffix}" if suffix else "")
                key = (alias, tag)
                assert key not in seen, (
                    f"{alias}:{tag} is claimed by both {seen[key]} and "
                    f"{variant['id']}. Give one of them a tag_suffix, or a "
                    f"different alias — otherwise the last build to finish "
                    f"silently owns the tag."
                )
                seen[key] = variant["id"]


def test_aliases_do_not_shadow_a_real_variant_or_publish_name():
    cfg = _config()
    reserved = {v["id"] for v in cfg["variants"]}
    reserved |= {v["publish_name"] for v in cfg["variants"] if v.get("publish_name")}
    for variant in cfg["variants"]:
        for alias in variant.get("aliases", []) or []:
            assert alias not in reserved, (
                f"{variant['id']} declares alias {alias!r}, which is already a "
                f"variant id or publish_name. That would overwrite a canonical "
                f"image with an alias."
            )


def test_aliases_are_lowercase_registry_safe():
    for variant in _config()["variants"]:
        for alias in variant.get("aliases", []) or []:
            assert alias == alias.lower() and " " not in alias, (
                f"{variant['id']}: alias {alias!r} is not a valid image name"
            )


IMAGE_INFO = Path(__file__).resolve().parents[1] / "build_scripts" / "90-image-info.sh"


def test_every_alias_folds_back_onto_its_variant():
    """90-image-info.sh must recognise every alias, not just the canonical ids.

    IMAGE_NAME is not always the variant id: lib.sh derives it from the detected
    base image when the Containerfile does not pin one, which hands back the
    distro alias (`opensuse` for sailfin, `gentoo` for guppy). An alias the
    script's canonical_variant() does not know falls through to the codename
    table's default branch and aborts the build for a perfectly known variant.
    """
    script = IMAGE_INFO.read_text()
    body = script.split("canonical_variant() {", 1)[1].split("\nesac", 1)[0]
    for variant in _config()["variants"]:
        for alias in variant.get("aliases", []) or []:
            assert alias in body, (
                f"{variant['id']} declares alias {alias!r}, which "
                f"build_scripts/90-image-info.sh does not fold back onto a "
                f"canonical variant id, so a build tagged with that alias would "
                f"abort in the codename lookup."
            )


def test_every_variant_has_a_codename():
    """Every variant id must hit a codename branch, never the abort default."""
    script = IMAGE_INFO.read_text()
    table = script.split("VARIANT_KEY=", 1)[1].split("\nesac", 1)[0]
    labels = set()
    for line in table.splitlines():
        label, _, rest = line.partition(") CODE_NAME=")
        if rest:
            labels.update(part.strip() for part in label.split("|"))
    for variant in _config()["variants"]:
        assert variant["id"] in labels, (
            f"{variant['id']} has no scientific fish codename in "
            f"build_scripts/90-image-info.sh; every build of it would abort."
        )
