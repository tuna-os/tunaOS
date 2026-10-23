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
