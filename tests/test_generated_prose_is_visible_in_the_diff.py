"""Prose a generator emits must match the prose already committed.

The STE ratchet lints `README.md` and `docs/MATRIX-STATUS.md`. Neither is
hand-written: `.github/scripts/update-build-status.sh` and
`scripts/gen-matrix-status.py` write them, and automation commits the result on
its own schedule. So a pull request can change linted prose without that prose
appearing anywhere in its diff, and the gate stays green until a nightly
refresh lands the new wording days later.

That is not hypothetical. tunaOS#2512 changed the README paragraph inside
update-build-status.sh. STE read 3048 locally, because the committed README
still held the old sentence. The automation regenerated it on 2026-09-14, the
new wording carried an "actually" and a passive "are omitted", and the repo went
to 3052 against a budget of 3050. The gate then failed on main and on every
pull request touching any .md for three days, and the PR that caused it had
been green.

The fix is to keep the two in step: whoever edits the generator's sentence
applies the same sentence to the committed file, so the linted bytes are in the
diff where a reviewer and the gate can both see them.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / ".github/scripts/update-build-status.sh"
README = ROOT / "README.md"

# The one paragraph of static prose the README generator emits. Everything else
# between the markers is a function of live CI state.
_ECHOED = re.compile(r'^\techo "(_Each cell reports.*_)"$', re.MULTILINE)


class TheReadmeParagraphMatchesItsGenerator(unittest.TestCase):
    def setUp(self):
        match = _ECHOED.search(GENERATOR.read_text())
        self.assertIsNotNone(
            match, f"{GENERATOR.name} no longer echoes a '_Each cell reports…_' "
                   "paragraph; if the prose moved, move this test with it")
        self.sentence = match.group(1)

    def test_the_committed_readme_carries_it_verbatim(self):
        self.assertIn(
            self.sentence, README.read_text(),
            "the generator emits a paragraph the committed README does not have. "
            "Apply the same sentence to README.md in this commit: it is linted by "
            "STE, and leaving it for the nightly refresh means the gate breaks "
            "later, on main, for a change that passed here.")

    def test_it_sits_inside_the_generated_block(self):
        # Outside the markers it would survive regeneration and then disagree
        # with the generator forever.
        block = README.read_text().split("<!-- build-status:start -->")[1]
        block = block.split("<!-- build-status:end -->")[0]
        self.assertIn(self.sentence, block)


class TheProseStaysOutOfTheRatchetsWay(unittest.TestCase):
    """The two words that actually cost three red days, pinned by name.

    Not a reimplementation of the linter — this repo cannot run it, since it
    lives in tuna-os/.github. These are the specific shapes that broke it, and a
    reviewer reading a failure here gets told which gate they are about to trip.
    """

    def _generated_prose(self):
        gen = GENERATOR.read_text()
        match = _ECHOED.search(gen)
        yield "README paragraph", match.group(1) if match else ""
        py = (ROOT / "scripts/gen-matrix-status.py").read_text()
        start = py.find('"The most recent sweep left ')
        self.assertNotEqual(start, -1, "the sweep caveat moved; move this with it")
        yield "sweep caveat", py[start:start + 400]

    def test_no_filler_word_the_ratchet_rejects(self):
        for name, prose in self._generated_prose():
            for filler in (" actually ", " simply ", " rather than "):
                with self.subTest(prose=name, filler=filler.strip()):
                    self.assertNotIn(filler, prose)

    def test_no_passive_construction_the_ratchet_rejects(self):
        for name, prose in self._generated_prose():
            for passive in ("are omitted", "is omitted", "are counted", "was measured"):
                with self.subTest(prose=name, passive=passive):
                    self.assertNotIn(passive, prose)


if __name__ == "__main__":
    unittest.main()
