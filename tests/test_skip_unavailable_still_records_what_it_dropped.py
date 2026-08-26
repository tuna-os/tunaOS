"""Fixing the dnf flag removed the only trace the dropped packages left.

Before, `install-desktop.sh` mis-spelled `--skip-unavailable`, the transaction
failed as a usage error, and the `|| install_available` fallback ran — and
install_available reports every package it could not find, both as a
`::warning::` and into `/usr/share/tunaos/missing-on-<image>.txt`, which the
weekly boot report reads.

Correcting the flag made the primary transaction succeed, so the fallback
stopped running, so nothing reported anything. `--skip-unavailable` means
exactly that dnf drops what it cannot satisfy WITHOUT failing, and the caller
is never told which.

Measured on run 32925587829, the first gnome cell to build after the fix:
hummingbird:gnome requested 52 desktop packages, installed 14, and emitted
zero "Missing package" warnings and no wishlist file. A correctness fix that
makes a known gap invisible is a bad trade, and this is the half that pays it
back.

The accounting deliberately does not distinguish dnf's two reasons. "No match
for argument" (the package is absent) and "Skipping packages with broken
dependencies" (it is present and unusable) are very different problems — 16
of that run's 38 were the second kind — but both end with the package not
installed, and neither fails the build.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "build_scripts" / "lib.sh"
INSTALL_DESKTOP = ROOT / "build_scripts" / "desktop" / "install-desktop.sh"


def extract(name: str) -> str:
    source = LIB.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{$.*?^\}}$", source, re.M | re.S)
    assert match, f"{name}() no longer matches the shape this test extracts"
    return match.group(0)


class RecordsWhatSkipUnavailableDropped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = extract("record_unsatisfied_requests") + "\n" + extract(
            "record_package_wishlist"
        )

    def _run(self, requested, installed, provides=(), with_rpm=True):
        """Run the real helper against a stubbed rpm database."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            if with_rpm:
                stub = bin_dir / "rpm"
                stub.write_text(
                    "#!/usr/bin/env bash\n"
                    # rpm -q --quiet [--whatprovides] NAME
                    "whatprovides=0\n"
                    'for a in "$@"; do [[ "$a" == --whatprovides ]] && whatprovides=1; done\n'
                    'name="${@: -1}"\n'
                    f"installed='{' '.join(installed)}'\n"
                    f"provided='{' '.join(provides)}'\n"
                    'for i in $installed; do [[ "$i" == "$name" ]] && exit 0; done\n'
                    'if [[ $whatprovides == 1 ]]; then\n'
                    '  for i in $provided; do [[ "$i" == "$name" ]] && exit 0; done\n'
                    "fi\n"
                    "exit 1\n"
                )
                stub.chmod(0o755)
            script = tmp / "harness.sh"
            script.write_text(
                "#!/usr/bin/env bash\nset -uo pipefail\n"
                f'export TUNAOS_WISHLIST_DIR="{tmp}/wishlist"\n'
                'export IMAGE_NAME=hummingbird\n'
                f"{self.helpers}\n"
                'record_unsatisfied_requests "install-desktop.sh:gnome" '
                + " ".join(f'"{p}"' for p in requested)
                + "\n"
            )
            proc = subprocess.run(
                ["bash", str(script)],
                capture_output=True,
                text=True,
                env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
                timeout=60,
            )
            wishlist = tmp / "wishlist" / "missing-on-hummingbird.txt"
            recorded = []
            if wishlist.exists():
                recorded = [
                    ln.strip()
                    for ln in wishlist.read_text().splitlines()
                    if ln.strip() and not ln.startswith("#")
                ]
            return proc, recorded

    REQUESTED = ["gnome-shell", "gdm", "nautilus", "avahi", "dconf"]

    def test_the_packages_dnf_dropped_are_named_in_the_wishlist(self):
        _, recorded = self._run(self.REQUESTED, installed=["avahi", "dconf"])
        self.assertEqual(sorted(recorded), ["gdm", "gnome-shell", "nautilus"])

    def test_the_warning_gives_both_numbers_not_just_the_misses(self):
        """'3 missing' is not actionable; '3 of 5' says how bad it is."""
        proc, _ = self._run(self.REQUESTED, installed=["avahi", "dconf"])
        self.assertIn("::warning title=Desktop packages dropped", proc.stdout)
        self.assertIn("3 of 5 packages", proc.stdout)

    def test_a_complete_install_reports_nothing(self):
        proc, recorded = self._run(self.REQUESTED, installed=self.REQUESTED)
        self.assertEqual(recorded, [])
        self.assertNotIn("::warning", proc.stdout)

    def test_a_package_installed_under_another_name_is_not_reported_missing(self):
        """Several manifest entries are provides, not package names.

        Reporting one of those as missing when it is installed would put noise
        into the file the boot report reads, which is how a wishlist stops
        being read at all.
        """
        _, recorded = self._run(
            ["librsvg2", "avahi"], installed=["avahi"], provides=["librsvg2"]
        )
        self.assertEqual(recorded, [])

    def test_a_base_without_rpm_is_left_alone(self):
        """flounder, grouper, marlin and guppy have no rpm database."""
        proc, recorded = self._run(self.REQUESTED, installed=[], with_rpm=False)
        self.assertEqual(recorded, [])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_an_empty_request_is_a_no_op(self):
        proc, recorded = self._run([], installed=[])
        self.assertEqual(recorded, [])
        self.assertEqual(proc.returncode, 0)

    def test_the_helper_is_actually_called_after_the_desktop_transaction(self):
        """Guard the guard: an uncalled helper passes every test above."""
        body = INSTALL_DESKTOP.read_text(encoding="utf-8")
        self.assertIn('record_unsatisfied_requests "install-desktop.sh:', body)
        call = body.index("record_unsatisfied_requests")
        install = body.index("dnf_retry -y install --skip-unavailable")
        self.assertLess(
            install,
            call,
            "the accounting must run AFTER the transaction it is accounting for",
        )

    def test_it_is_the_full_requested_list_that_is_accounted_for(self):
        """Passing the excludes or a subset would understate the gap."""
        body = INSTALL_DESKTOP.read_text(encoding="utf-8")
        self.assertIn(
            'record_unsatisfied_requests "install-desktop.sh:${_TD_DESKTOP}" "${_TD_PKGS[@]}"',
            body,
        )


if __name__ == "__main__":
    unittest.main()
