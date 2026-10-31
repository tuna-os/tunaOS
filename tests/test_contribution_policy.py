"""Keep workflow actions consistent with optional DCO sign-off.

Existing and voluntary Signed-off-by trailers remain valid. External GitHub
settings need an admin.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workflows_do_not_delegate_to_a_dco_action():
    # A new external DCO action would restore blocking policy independently
    # of the contributor guide. Ordinary signing and provenance jobs are valid.
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        for action in re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*(\S+)", path.read_text()):
            assert not re.search(r"(?:^|[/_-])dco(?:[/_@.-]|$)", action, re.I), path
