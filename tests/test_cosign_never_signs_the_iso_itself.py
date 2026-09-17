"""`cosign sign-blob` must never be handed an ISO.

It reads its payload into memory. The runners have 16 GB and no swap, so an
ISO above roughly 7 GiB exhausts the machine, and Actions reports that as

    ##[error]The runner has received a shutdown signal.

not as a failure of the signing step. The ISO is built and boot-gated by then,
so the cell goes red having done every expensive thing right. That is the worst
shape a failure can have: it costs a full build and names nothing.

publish-iso-groups.yml learned this with the step instrumented (job
97677987562: 8.0 GiB payload, 14.8 GiB available, dead 32s in) and switched to
signing the ~100-byte .sha256. reusable-build-artifacts.yml did not, and went
on failing every night on the only flavor big enough to trip it:

    niri  amd64  5.8G -> Wrote bundle
    kde   arm64  7.9G -> runner shutdown
    kde   amd64  8.3G -> runner shutdown

Five siblings signed fine in the same window, so this was never Sigstore. It
was the payload size, and it was reproducible on both arches for five days.

This test is a shape assertion because the real thing needs an 8 GiB file and a
runner to kill. It pins the property that survived that investigation: the
signed payload is the checksum.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github/workflows/reusable-build-artifacts.yml",
    ROOT / ".github/workflows/publish-iso-groups.yml",
)


def _uncommented(text):
    """Drop comment lines; the notes explaining this quote the wrong form."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


class CosignSignsTheChecksum(unittest.TestCase):
    def test_no_workflow_passes_an_iso_to_sign_blob(self):
        for wf in WORKFLOWS:
            body = _uncommented(wf.read_text())
            for call in re.findall(r"cosign sign-blob[^\n]*", body):
                with self.subTest(workflow=wf.name, call=call):
                    self.assertNotRegex(
                        call, r'"\$ISO"|\$\{ISO\}(?!\.)',
                        "sign-blob is being handed the ISO; it reads the payload "
                        "into memory and OOM-kills the runner. Sign $CHECKSUM.")

    def test_every_sign_blob_payload_is_a_checksum(self):
        for wf in WORKFLOWS:
            body = _uncommented(wf.read_text())
            calls = re.findall(r"cosign sign-blob[^\n]*", body)
            self.assertTrue(calls, f"{wf.name} signs nothing at all")
            for call in calls:
                with self.subTest(workflow=wf.name, call=call):
                    self.assertRegex(
                        call, r'"\$CHECKSUM"',
                        "the signed payload must be the checksum file")

    def test_verify_blob_checks_the_same_payload_it_signed(self):
        # Verifying the ISO against a bundle made over the checksum fails, and
        # would fail only at release time, on a consumer's machine.
        for wf in WORKFLOWS:
            body = _uncommented(wf.read_text())
            for call in re.findall(r"cosign verify-blob[^\n]*", body):
                with self.subTest(workflow=wf.name, call=call):
                    self.assertRegex(call, r'"\$CHECKSUM"')

    def test_the_signing_step_is_bounded(self):
        # Unbounded, a wedged sign-blob dies as a runner shutdown with no step
        # to blame. The bound turns the next regression into a readable error.
        for wf in WORKFLOWS:
            text = wf.read_text()
            step = re.search(r"name: Checksum, sign, and verify[^\n]*\n(.*?)\n      - name:",
                             text, re.S)
            self.assertIsNotNone(step, f"{wf.name}: signing step not found")
            self.assertIn("timeout-minutes:", step.group(1),
                          f"{wf.name}: signing step has no timeout")
            self.assertIn("timeout 300 cosign", step.group(1),
                          f"{wf.name}: cosign calls are unbounded")


class TheDocsDescribeWhatIsActuallySigned(unittest.TestCase):
    """A consumer following the old instructions gets a verification failure."""

    def test_the_docs_verify_the_checksum_not_the_iso(self):
        for doc in (ROOT / "docs/INSTALL.md", ROOT / "docs/VERIFY-ARTIFACTS.md"):
            text = doc.read_text()
            for call in re.findall(r"cosign verify-blob [^\n]*", text):
                with self.subTest(doc=doc.name, call=call):
                    self.assertNotRegex(
                        call, r"\.iso\s*\\?$",
                        "the docs tell users to verify the ISO against a bundle "
                        "that signs the checksum; that verification fails")


if __name__ == "__main__":
    unittest.main()
