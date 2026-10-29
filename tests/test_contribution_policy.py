"""Keep onboarding examples consistent with optional DCO sign-off.

These checks cover instructions, not commit messages: existing and voluntary
Signed-off-by trailers remain valid. External GitHub settings need an admin.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", [
    "CONTRIBUTING.md",
    "CONTRIBUTING-ADVANCED.md",
    "docs/CONTRIBUTOR-FIRST-PR.md",
    "docs/FEDIVERSE-PLAYBOOK.md",
    ".github/ISSUE_TEMPLATE/starter-task.yml",
])
def test_onboarding_commands_do_not_add_attestations(name):
    text = (ROOT / name).read_text()
    for command in re.findall(r"git commit[^`\n]*", text):
        assert not re.search(r"(?:^|\s)(?:-s|--signoff)(?:\s|$)", command), name
    assert "#dco-sign-off" not in text, name


def test_agent_instructions_link_the_contribution_policy():
    text = (ROOT / "AGENTS.md").read_text()
    assert "CONTRIBUTING.md#commit-identity" in text
    assert "DCO sign-off is optional for all commits" in " ".join(text.split())


def test_workflows_do_not_delegate_to_a_dco_action():
    # A new external DCO action would restore blocking policy independently
    # of the contributor guide. Ordinary signing and provenance jobs are valid.
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        for action in re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*(\S+)", path.read_text()):
            assert not re.search(r"(?:^|[/_-])dco(?:[/_@.-]|$)", action, re.I), path
