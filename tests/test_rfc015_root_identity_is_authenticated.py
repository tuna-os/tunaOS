"""RFC 015: the sealed-root identity must be authenticated by the boot chain.

A root hash that only the installed system checks is not sealed: whoever can
write the ESP or the cmdline can swap it. The contract text has to bind the
identity to the signed UKI cmdline and say what a verifier rejects.
"""

import re
from pathlib import Path

RFC = Path(__file__).resolve().parent.parent / "docs/rfc/rfc015-sealed-uki-image-mode.md"


def _text() -> str:
    return " ".join(RFC.read_text().split())


def test_root_identity_binding_is_a_field_of_the_contract():
    root = re.search(r"^root:\n(?:[ \t].*\n|\n)*", RFC.read_text(), re.M)
    assert root, "contract has no root: block"
    block = root.group(0)
    assert re.search(r"binding:\s*signed-uki-cmdline", block), block
    assert "cmdline_parameter" in block, block


def test_a_rule_requires_authenticated_root_identity():
    text = _text()
    assert re.search(
        r"root identity MUST be bound to the signed UKI cmdline and verified "
        r"through the trusted boot chain",
        text,
    )
    # Acceptance statement: what is accepted and what is rejected.
    assert "A verifier MUST accept a root identity only when" in text
    assert "unsigned or host-supplied root identity" in text


def test_root_integrity_assurance_is_not_self_checked_only():
    text = _text()
    assert "the boot path checks the declared root identity" not in text
    assert "authenticated by the signed UKI" in text


def test_trust_negatives_cover_a_swapped_root_identity():
    assert re.search(r"(swapped|altered) root identity", _text())
