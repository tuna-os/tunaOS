"""AT-SPI matchers follow the shared/flow contract (tunaOS#4910, #4901).

Falsification: an insensitive button standing in for a sensitive press
target, a same-named panel beating the button, a recovery key matched by
its label instead of its shape, a done signal outranking a failure, or a
glib NBSP size missed by a plain-space query all fail this module.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "scripts/installer-e2e"
FIX = ROOT / "tests/fixtures/installer-e2e"


def load(name):
    """Load a scripts/installer-e2e module once; reuse it after that."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, E2E / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


atspi_match = load("atspi_match")
Page = atspi_match.Page


def fixture(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def node(
    name,
    role="push button",
    states=("showing", "visible", "sensitive"),
    text="",
    ext=(10, 10, 100, 30),
    path="0.0",
):
    return {
        "name": name,
        "role": role,
        "states": list(states),
        "text": text,
        "ext": list(ext),
        "path": path,
    }


def test_nbsp_and_narrow_nbsp_normalise_to_plain_spaces():
    assert atspi_match.canon_space("51.5 GB") == "51.5 GB"
    assert atspi_match.canon_space("100 GB") == "100 GB"


def test_size_queries_match_glib_nbsp_text():
    nodes = fixture("disk-page.json")
    assert atspi_match.has_text(nodes, "vda - 20 GB")
    assert atspi_match.has_text(nodes, "Only 100 GB free on vda")


def test_mnemonic_underscore_never_blocks_a_match():
    nodes = [node("_Next")]
    assert atspi_match.qualify(nodes, "Next", role="push button") == nodes[0]


def test_insensitive_button_never_stands_in_for_a_press_target():
    nodes = fixture("disk-page.json")
    assert atspi_match.qualify(nodes, "Install", role="push button") is None
    found = atspi_match.qualify(nodes, "Install", role="push button", sensitive=False)
    assert found is not None and found["path"] == "0.3"


def test_sensitive_button_matches_by_role_and_sensitivity():
    nodes = fixture("disk-page.json")
    found = atspi_match.qualify(nodes, "Continue", role="push button")
    assert found is not None and found["path"] == "0.2"


def test_panel_never_beats_the_button_with_the_same_name():
    nodes = [
        node("Done", role="panel", states=("showing", "visible", "sensitive")),
        node("Done", role="push button", states=("showing", "visible"), path="0.1"),
    ]
    assert atspi_match.qualify(nodes, "Done", role="push button") is None
    found = atspi_match.qualify(nodes, "Done", role="push button", sensitive=False)
    assert found is not None and found["role"] == "push button"


def test_topmost_dialog_beats_the_page_behind_it():
    nodes = fixture("recovery-key-page.json")
    found = atspi_match.qualify(nodes, "Done", role="push button")
    assert found is not None and found["path"] == "0.5.0"


def test_recovery_key_matches_by_shape_not_by_label():
    nodes = fixture("recovery-key-page.json")
    found = atspi_match.find_recovery_key(nodes)
    assert found is not None and found["role"] == "label"
    assert atspi_match.RECOVERY_KEY_RE.search(found["name"])


def test_recovery_key_label_without_shape_matches_nothing():
    nodes = [
        node("Recovery Key", role="label"),
        node("abcdefgh-ijklmnop", role="label", path="0.1"),
    ]
    assert atspi_match.find_recovery_key(nodes) is None


def test_disk_page_classifies_from_its_text():
    assert atspi_match.classify_page(fixture("disk-page.json")) is Page.DISK


def test_recovery_page_classifies_from_key_or_heading():
    assert atspi_match.classify_page(fixture("recovery-key-page.json")) is Page.RECOVERY_KEY


def test_failure_beats_done_on_the_same_page():
    assert atspi_match.classify_page(fixture("failure-page.json")) is Page.FAILURE


def test_done_progress_confirm_and_next_classify():
    assert (
        atspi_match.classify_page(
            [node("Installation finished! Reboot now to complete the installation.")]
        )
        is Page.COMPLETE
    )
    assert atspi_match.classify_page([node("Installing files")]) is Page.PROGRESS
    assert atspi_match.classify_page([node("Confirm Installation")]) is Page.INSTALL_CONFIRMATION
    assert atspi_match.classify_page([node("Confirm Changes")]) is Page.DISK_CONFIRMATION
    assert atspi_match.classify_page([node("Next")]) is Page.NEXT
    assert atspi_match.classify_page([]) is Page.WAIT


def test_recovery_key_failure_counts_as_failure_not_recovery():
    nodes = [node("Recovery Key failed to enrol", role="label")]
    assert atspi_match.classify_page(nodes) is Page.FAILURE
