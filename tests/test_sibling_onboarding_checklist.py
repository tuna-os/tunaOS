"""The onboarding checklist of a BuildStream sibling image stays true to the config.

installer-medium/docs/retire-path.md says what makes a sibling entirely
onboarded. The checklist names the record fields, so a field that the config
adds or drops must change the checklist in the same commit.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "installer-medium" / "docs" / "retire-path.md"
SPEC = importlib.util.spec_from_file_location(
    "sibling_checklist_config_under_test", ROOT / "scripts" / "lib" / "tunaos_config.py"
)
primary_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(primary_config)

# What the validator knows for a sibling record.
COMMON = ("id", "emoji", "description", "repo", "desktops", "mark", "availability")
PUBLISHED = ("image", "workflow", "installer_tag")


def checklist() -> str:
    text = DOC.read_text()
    start = text.index("### Onboarding checklist")
    return text[start:]


def item(number: int) -> str:
    body = checklist()
    match = re.search(rf"^{number}\. (.*?)(?=^\d+\. |\Z)", body, re.S | re.M)
    assert match, f"checklist item {number} is missing"
    return match.group(1)


def test_the_checklist_has_eight_numbered_lines():
    numbers = re.findall(r"^(\d+)\. \*\*", checklist(), re.M)
    assert numbers == [str(n) for n in range(1, 9)]


def test_the_record_line_names_every_field_the_validator_requires():
    record = item(1)
    for key in COMMON + PUBLISHED:
        assert f"`{key}`" in record, f"checklist line 1 does not name {key}"


def test_every_field_of_a_live_record_is_on_the_checklist():
    """A record that grows a field must grow the checklist line in the same commit."""
    records = primary_config.load(ROOT / "tunaos.toml")["sibling_images"]
    used = {key for record in records for key in record}
    # `target` is the unpublished twin of `image`; the line says so in prose.
    for key in used:
        assert f"`{key}`" in item(1), f"checklist line 1 does not name `{key}`"


def test_every_published_sibling_declares_the_installer_tag():
    for record in primary_config.load(ROOT / "tunaos.toml")["sibling_images"]:
        if record.get("image"):
            assert record.get("installer_tag"), f"{record['id']}: the medium reads installer_tag"


def test_the_checklist_covers_each_required_proof():
    text = checklist()
    for needle in (
        "scan-images.py",
        "verify-image.sh",
        "anonymous pull",
        "cosign",
        "USB and from CD",
        "seven stages",
        "`publish=false`",
        "promoted = true",
    ):
        assert needle in text, f"checklist does not mention {needle}"


def test_every_sibling_cell_has_a_status_row_and_every_gate_a_line():
    text = DOC.read_text()
    status = text[text.index("### Status of each sibling cell"):]
    config = primary_config.load(ROOT / "tunaos.toml")
    siblings = {s["id"] for s in config["sibling_images"]}
    declared = {
        c["cell"] for c in config["installer_medium"]["cells"] if c["cell"].partition(":")[0] in siblings
    }
    for cell in declared | {"athens:pantheon", "ubuntu-core-desktop"}:
        assert f"| `{cell}` |" in status, f"no status row for {cell}"
    standard = text[text.index("### The same standard for every sibling"):text.index("### Status of each sibling cell")]
    for gate in ("Stage 6", "Stage 7", "Signature", "Public image", "Security module", "Boot gate", "Screen reader"):
        assert f"| {gate}" in standard, f"no standard line for {gate}"
