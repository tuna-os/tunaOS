#!/usr/bin/env python3
"""The contract sweep must pull the ref the pipeline actually publishes.

The sweep built its ref by concatenation:

    REF: ghcr.io/tuna-os/${{ matrix.variant }}:${{ matrix.desktop }}

That is not how this factory names published images. `.github/build-config.yml`
gives some variants a `publish_name` and a `tag_suffix`, so `bonito-rawhide:kde`
publishes as `bonito:kde-rawhide` and `flounder-sid:kde` as `flounder:kde-sid`.
The Promote job writes exactly those refs (run 34709168489) and never writes
`bonito-rawhide:kde` at all.

Nothing complained because the naive form still resolved: the pre-fold tags are
still in the registry, abandoned. Measured against ghcr.io on 2026-09-13:

    bonito-rawhide:kde   created 2026-07-14   <- what the sweep read
    bonito:kde-rawhide   created 2026-09-12   <- what Promote writes
    flounder-sid:kde     created 2026-07-13   <- what the sweep read
    flounder:kde-sid     created 2026-09-13   <- what Promote writes

So every verdict this sweep recorded for those two variants — eight cells, and
the contradiction filed as tunaOS#2496 — was about a two-month-old image the
factory had stopped publishing. All eight pass their desktop contract at build
time and all eight promoted.
"""

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / ".github" / "workflows" / "desktop-contract-sweep.yml"
CONFIG = ROOT / ".github" / "build-config.yml"
RESOLVER = ROOT / "scripts" / "published-image-ref.sh"


def _variants() -> list[dict]:
    return yaml.safe_load(CONFIG.read_text())["variants"]


def _folded() -> list[dict]:
    """Variants whose published ref differs from <id>:<flavor>."""
    return [v for v in _variants() if v.get("publish_name") or v.get("tag_suffix")]


def _canonical(variant: dict, flavor: str) -> str:
    name = variant.get("publish_name") or variant["id"]
    suffix = variant.get("tag_suffix") or ""
    tag = flavor
    if suffix and not tag.endswith(f"-{suffix}") and f"-{suffix}-" not in tag:
        tag = f"{tag}-{suffix}"
    return f"ghcr.io/tuna-os/{name}:{tag}"


class TheBugClassIsReal(unittest.TestCase):
    """tunaOS#1730: if no variant folds, everything below passes vacuously."""

    def test_some_variant_publishes_under_a_different_name(self):
        folded = _folded()
        self.assertTrue(folded, "no variant sets publish_name or tag_suffix")
        ids = {v["id"] for v in folded}
        self.assertIn("bonito-rawhide", ids)
        self.assertIn("flounder-sid", ids)

    def test_the_naive_ref_differs_from_the_published_one(self):
        for v in _folded():
            with self.subTest(variant=v["id"]):
                naive = f"ghcr.io/tuna-os/{v['id']}:kde"
                self.assertNotEqual(
                    naive, _canonical(v, "kde"),
                    "this variant folds, so the two spellings must differ",
                )


class TheSweepResolvesRatherThanAssumes(unittest.TestCase):

    def test_the_sweep_does_not_hardcode_the_naive_ref(self):
        self.assertNotRegex(
            SWEEP.read_text(),
            r"REF:\s*ghcr\.io/tuna-os/\$\{\{\s*matrix\.variant",
            "concatenating variant and desktop skips publish_name/tag_suffix "
            "and reads an abandoned pre-fold tag for every folded variant",
        )

    def test_the_sweep_uses_the_pipeline_s_own_resolver(self):
        self.assertRegex(
            SWEEP.read_text(),
            r'REF="\$\(bash \./scripts/published-image-ref\.sh '
            r'"\$VARIANT" "\$DESKTOP" ghcr\)"',
        )

    def test_that_resolver_exists_and_reads_both_config_fields(self):
        body = RESOLVER.read_text()
        self.assertIn("publish_name", body)
        self.assertIn("tag_suffix", body)

    def test_the_sweep_logs_which_ref_it_resolved(self):
        """A wrong ref was invisible for two months; make it readable."""
        self.assertIn("resolves to ${REF}", SWEEP.read_text())


class UnfoldedVariantsAreUnaffected(unittest.TestCase):

    def test_the_fix_is_a_no_op_for_every_other_variant(self):
        plain = [v for v in _variants()
                 if not v.get("publish_name") and not v.get("tag_suffix")]
        self.assertTrue(plain, "expected variants that do not fold")
        for v in plain:
            with self.subTest(variant=v["id"]):
                self.assertEqual(
                    _canonical(v, "gnome"), f"ghcr.io/tuna-os/{v['id']}:gnome",
                    "a non-folding variant must resolve exactly as before",
                )


if __name__ == "__main__":
    unittest.main()
