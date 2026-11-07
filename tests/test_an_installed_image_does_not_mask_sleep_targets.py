"""The installed image must not mask suspend/hibernate (tunaOS#4305).

`build_scripts/26-packages-post.sh` once ran
`systemctl mask suspend.target hibernate.target ...` "to stop walkthrough VMs
sleeping". The script runs for the INSTALLED image, so every laptop shipped
with CanSuspend=no: GNOME offered no Suspend, idle auto-suspend failed
silently, and with the lid closed logind retried

    Unit suspend.target is masked, refusing operation.

in a tight loop (597,000 log lines in one two-hour lid-closed period, CPU
awake on battery; Dell Precision 7560, albacore:gnome d7c1398).

Masking belongs to the live installer session, which does it itself in
live-iso/common/src/desktop-*.sh. Nothing under build_scripts/ (the code that
builds the installed image) may mask a sleep target.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILD_SCRIPTS = REPO / "build_scripts"

MASK_SLEEP = re.compile(
    r"^[^#\n]*\b(?:systemctl|safe_mask)\b[^\n#]*\bmask\b[^\n#]*"
    r"\b(?:sleep|suspend|hibernate|hybrid-sleep|suspend-then-hibernate)\.target\b",
    re.MULTILINE,
)


class InstalledImageSleepTargets(unittest.TestCase):
    def test_no_build_script_masks_a_sleep_target(self) -> None:
        offenders = []
        for path in sorted(BUILD_SCRIPTS.rglob("*.sh")):
            text = path.read_text(encoding="utf-8", errors="replace")
            if MASK_SLEEP.search(text):
                offenders.append(str(path.relative_to(REPO)))
        self.assertEqual(
            offenders,
            [],
            "these installed-image scripts mask a sleep target; laptops would "
            "never suspend (tunaOS#4305). Mask in live-iso/ instead.",
        )

    def test_the_guard_matches_the_original_bug(self) -> None:
        original = (
            "systemctl mask suspend.target hibernate.target "
            "hybrid-sleep.target suspend-then-hibernate.target || true\n"
        )
        self.assertIsNotNone(MASK_SLEEP.search(original))
        self.assertIsNone(MASK_SLEEP.search("# systemctl mask suspend.target\n"))


if __name__ == "__main__":
    unittest.main()
