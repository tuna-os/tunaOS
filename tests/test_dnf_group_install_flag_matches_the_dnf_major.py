"""`dnf group install` must get the skip-unavailable spelling its dnf takes.

`--skip-unavailable` is a dnf5 flag. EL10 ships dnf 4.20, whose
`dnf group install` answers

    dnf group: error: unrecognized arguments: --skip-unavailable

and installs nothing. install-desktop.sh followed it with `|| true`, so from
62543074 on every el10 desktop shipped without its manifest groups:
albacore:gnome had `dnf group list --installed` empty, no
google-noto-color-emoji-fonts (every emoji a hex box), no NetworkManager-wifi,
no CUPS (tunaOS#4308).

Measured on quay.io/almalinuxorg/almalinux-bootc:10 (dnf 4.20.0):
`dnf group install -y --skip-unavailable ...` exits 2; the same command with
`--setopt=strict=0` exits 0 and installs the groups' default packages.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = (REPO / "build_scripts" / "desktop" / "install-desktop.sh").read_text(
    encoding="utf-8"
)


class GroupInstallFlag(unittest.TestCase):
    def test_group_install_never_hardcodes_the_dnf5_flag(self) -> None:
        hardcoded = re.findall(
            r"^[^#\n]*dnf\s+group\s+install[^\n]*--skip-unavailable", SCRIPT, re.M
        )
        self.assertEqual(
            hardcoded,
            [],
            "dnf 4 (EL10) rejects `group install --skip-unavailable` and "
            "installs nothing; select the flag by dnf major (tunaOS#4308)",
        )

    def test_both_spellings_are_selected_by_dnf_version(self) -> None:
        self.assertIn('== dnf5*', SCRIPT)
        self.assertIn('_TD_GROUP_SKIP="--skip-unavailable"', SCRIPT)
        self.assertIn('_TD_GROUP_SKIP="--setopt=strict=0"', SCRIPT)
        self.assertRegex(
            SCRIPT, r"dnf group install -y \$\{_TD_GROUP_SKIP\} "
        )


if __name__ == "__main__":
    unittest.main()
