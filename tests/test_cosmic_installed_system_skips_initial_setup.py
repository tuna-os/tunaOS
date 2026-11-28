"""Installed COSMIC images do not start COSMIC Initial Setup.

bonito:cosmic (run 45669552583): the first login of the account that the
installer made opened a second wizard, which asks for language, keyboard and
time zone again.
"""

import re
from pathlib import Path

import pytest

DESKTOP = Path(__file__).resolve().parents[1] / "build_scripts" / "desktop"


@pytest.mark.parametrize(
    "script, condition",
    [
        # Ubuntu builds run the first script, the package paths the second.
        ("configure-desktop-runtime.sh", r'if \[\[ "\$desktop" == cosmic \]\]'),
        ("install-desktop.sh", r'if \[\[ "\$\{_TD_DESKTOP\}" == cosmic\* \]\]'),
    ],
)
def test_the_autostart_entry_is_removed(script, condition):
    """Falsification: without the block the wizard starts in the first session."""
    text = (DESKTOP / script).read_text()
    block = re.search(
        condition + r"; then\n\trm -f (\S+)\nfi\n",
        text,
    )
    assert block, f"{script} keeps the autostart entry"
    assert block.group(1) == "/etc/xdg/autostart/com.system76.CosmicInitialSetup*.desktop"
