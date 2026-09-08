"""The PR quality contract must stay self-consistent.

AGENTS.md's contract is prose, so nothing stopped it drifting: the header
said "Five rules" while the list grew, and a rule that is miscounted is a
rule nobody is sure applies. These tests are cheap and keep the doc honest.

They deliberately do NOT check wording. They check the things that go stale
without anyone noticing: the count in the header, the numbering of the list,
and that the rules the repo actually enforces are present by name.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
GUIDE = ROOT / "docs" / "AGENT_GUIDE.md"
TROUBLESHOOTING = ROOT / "docs" / "ci-troubleshooting.md"

_WORDS = {
    "One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5,
    "Six": 6, "Seven": 7, "Eight": 8, "Nine": 9, "Ten": 10,
}


def _contract_rules() -> list[int]:
    text = AGENTS.read_text()
    body = text[text.index("## PR quality contract"):]
    body = body[: body.index("\nEvidence style,")]
    return [int(m) for m in re.findall(r"^(\d+)\. \*\*", body, re.M)]


def test_the_header_count_matches_the_list() -> None:
    """The header said "Five rules" while six were listed."""
    text = AGENTS.read_text()
    header = re.search(r"^(\w+) rules, each one written because", text, re.M)
    assert header, "the contract lost its 'N rules' header"
    claimed = _WORDS[header.group(1)]
    assert claimed == len(_contract_rules())


def test_the_rules_are_numbered_consecutively_from_one() -> None:
    """A duplicated or skipped number makes 'rule 4' ambiguous in review."""
    assert _contract_rules() == list(range(1, len(_contract_rules()) + 1))


def test_the_docs_rule_is_present() -> None:
    """Every PR that diagnoses something records what it learned.

    Without this rule the knowledge lives in one PR body and is gone.
    """
    text = AGENTS.read_text()
    assert "Leave the docs better than you found them" in text
    assert "ci-troubleshooting.md" in text


def test_troubleshooting_rows_are_uniquely_numbered() -> None:
    """Two rows sharing a number means one of them cannot be cited."""
    rows = re.findall(r"^\| (\d+) \|", TROUBLESHOOTING.read_text(), re.M)
    assert rows, "no numbered rows found"
    assert len(rows) == len(set(rows)), "duplicate troubleshooting row numbers"


def test_the_guide_distinguishes_dev_from_published_iso_testing() -> None:
    """Production media ships sshd disabled.

    Every SSH-based iso-e2e mode fails against a downloadable ISO, which is
    why the LUKS gate only ever covered dev media. An agent that does not
    know this concludes the published ISO is broken.
    """
    text = GUIDE.read_text()
    assert "--published" in text
    assert "sshd disabled" in text or "sshd is disabled" in text
