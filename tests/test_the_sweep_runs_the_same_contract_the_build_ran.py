#!/usr/bin/env python3
"""The sweep must not judge an image more harshly than the build did.

`build_scripts/checks/verify-desktop-experience.sh` reads two environment
flags, IS_ELN and IS_HUMMINGBIRD, to tell a packaging mistake from a measured
property of the upstream compose. `.github/workflows/reusable-build-image.yml`
passes both when it runs the script at build time.

`.github/workflows/desktop-contract-sweep.yml` runs that same script against
the published image and passed neither. So the sweep enforced a stricter
contract than the gate the image had already cleared, and failed cells for
gaps the script is written to name and allow.

reusable-build-image.yml has a long comment recording what that cost the first
time round — wahoo's gnome, cosmic and kde cells, on the ELN codec gap, run
34609709028, "Nothing was wrong with the images". That fix was never ported to
the sweep, which went on failing the same three cells for the same reason:
`ffmpeg cannot decode h264` in all three, run 34692178123.

These tests hold the two call sites to the same flags.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / ".github" / "workflows" / "desktop-contract-sweep.yml"
BUILD = ROOT / ".github" / "workflows" / "reusable-build-image.yml"
SCRIPT = ROOT / "build_scripts" / "checks" / "verify-desktop-experience.sh"

FLAGS = ("IS_ELN", "IS_HUMMINGBIRD")


def _contract_invocation(text: str) -> str:
    """The `podman run ... /vde.sh` command, with the -e flags before it."""
    i = text.index("verify-desktop-experience.sh:/vde.sh")
    return text[max(0, i - 1200):text.index("/vde.sh ", i) + 40]


class TheFlagsAreWorthPassing(unittest.TestCase):
    """tunaOS#1730: prove the script reads them before pinning who sends them."""

    def test_the_contract_script_reads_both_flags(self):
        body = SCRIPT.read_text()
        for flag in FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(f"${{{flag}:-false}}", body)

    def test_both_workflows_run_the_contract_script(self):
        for wf in (SWEEP, BUILD):
            with self.subTest(workflow=wf.name):
                self.assertIn("verify-desktop-experience.sh:/vde.sh",
                              wf.read_text())


class TheSweepPassesWhatTheBuildPasses(unittest.TestCase):

    def test_the_sweep_sets_both_flags_on_the_contract_run(self):
        call = _contract_invocation(SWEEP.read_text())
        for flag in FLAGS:
            with self.subTest(flag=flag):
                self.assertRegex(
                    call, rf'-e {flag}="\$\w+"',
                    f"the sweep must pass {flag} to the contract, as "
                    f"reusable-build-image.yml does; without it the sweep "
                    f"fails images the build deliberately passed",
                )

    def test_the_build_still_sets_both_flags(self):
        """If the build ever stops, these two have drifted apart again."""
        call = _contract_invocation(BUILD.read_text())
        for flag in FLAGS:
            with self.subTest(flag=flag):
                self.assertRegex(call, rf'-e {flag}="\$\w+"')

    def test_both_derive_eln_from_the_wahoo_variant_id(self):
        """Derived from the variant id in both places, so neither can drift.

        The two spell the variant differently — the sweep reads the matrix
        entry, the build job an env var — so match either form rather than
        forcing one workflow to adopt the other's idiom.
        """
        for wf in (SWEEP, BUILD):
            with self.subTest(workflow=wf.name):
                self.assertRegex(
                    wf.read_text(),
                    r'is_eln=false\s*\n\s*\[\[ "\$\{?\{?[^"]+\}?\}?" == wahoo\* \]\]'
                    r' && is_eln=true',
                )

    def test_both_derive_hummingbird_from_the_variant_id(self):
        for wf in (SWEEP, BUILD):
            with self.subTest(workflow=wf.name):
                self.assertRegex(
                    wf.read_text(),
                    r'is_hb=false\s*\n\s*\[\[ "\$\{?\{?[^"]+\}?\}?" == hummingbird\* \]\]'
                    r' && is_hb=true',
                )


class TheEvidenceIsKept(unittest.TestCase):

    def test_the_captured_contract_output_is_written_to_a_file(self):
        self.assertIn('> desktop-contract.log', SWEEP.read_text())

    def test_that_file_is_uploaded_with_the_cell_result(self):
        text = SWEEP.read_text()
        upload = text[text.index("name: contract-${{ matrix.variant }}"):]
        self.assertIn("desktop-contract.log", upload[:400])


if __name__ == "__main__":
    unittest.main()
