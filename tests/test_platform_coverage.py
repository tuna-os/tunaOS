#!/usr/bin/env python3
"""The ROADMAP platform matrix stays derived from build-config (tunaOS#2735)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gen-platform-coverage.py"

_spec = importlib.util.spec_from_file_location("gen_platform_coverage", SCRIPT)
gpc = importlib.util.module_from_spec(_spec)
sys.modules["gen_platform_coverage"] = gpc
_spec.loader.exec_module(gpc)


def fixture() -> dict:
    return {
        "config": {"global_platforms": ["linux/amd64", "linux/arm64"]},
        "variants": [
            {
                "id": "both",
                "flavors": [
                    {"id": "gnome", "build_image": True},
                    {"id": "gnome-asahi", "build_image": True,
                     "platforms": ["linux/arm64"]},
                    {"id": "kde", "build_image": True,
                     "platforms": ["linux/amd64"]},
                    {"id": "cosmic", "build_image": False},
                ],
            },
            {
                "id": "arm",
                "platforms": ["linux/arm64"],
                "flavors": [{"id": "niri", "build_image": True}],
            },
        ],
    }


class TestDerivation(unittest.TestCase):
    def test_standard_platforms_follow_enabled_desktop_flavors(self):
        rows = {row["variant"]: row for row in gpc.coverage(fixture())}
        self.assertEqual(rows["both"]["amd64"], {"gnome", "kde"})
        self.assertEqual(rows["both"]["arm64"], {"gnome"})
        self.assertEqual(rows["arm"]["arm64"], {"niri"})
        self.assertNotIn("cosmic", rows["both"]["amd64"])

    def test_apple_silicon_requires_an_enabled_asahi_flavor(self):
        rows = {row["variant"]: row for row in gpc.coverage(fixture())}
        self.assertEqual(rows["both"]["asahi"], {"gnome"})
        self.assertEqual(rows["arm"]["asahi"], set())

    def test_generic_arm64_does_not_imply_apple_silicon(self):
        rows = {row["variant"]: row for row in gpc.coverage(fixture())}
        self.assertIn("niri", rows["arm"]["arm64"])
        self.assertNotIn("niri", rows["arm"]["asahi"])

    def test_arm64_variant_suffix_counts_as_arm64(self):
        config = fixture()
        config["variants"][1]["platforms"] = ["linux/arm64/v8"]
        config["variants"][0]["flavors"][1]["platforms"] = ["linux/arm64/v8"]
        rows = {row["variant"]: row for row in gpc.coverage(config)}
        self.assertEqual(rows["arm"]["arm64"], {"niri"})
        self.assertEqual(rows["both"]["asahi"], {"gnome"})

    def test_platforms_string_is_rejected(self):
        config = fixture()
        config["variants"][1]["platforms"] = "linux/arm64"
        with self.assertRaises(ValueError):
            gpc.coverage(config)

    def test_empty_flavor_platforms_means_none_not_inherit(self):
        config = fixture()
        config["variants"][1]["flavors"][0]["platforms"] = []
        rows = {row["variant"]: row for row in gpc.coverage(config)}
        self.assertNotIn("niri", rows["arm"]["arm64"])

    def test_pantheon_and_tuna_cells_are_counted(self):
        config = fixture()
        config["variants"].append({
            "id": "extra",
            "flavors": [
                {"id": "pantheon", "build_image": True},
                {"id": "tuna", "build_image": True,
                 "platforms": ["linux/amd64"]},
            ],
        })
        rows = {row["variant"]: row for row in gpc.coverage(config)}
        self.assertEqual(rows["extra"]["amd64"], {"pantheon", "tuna"})
        self.assertEqual(rows["extra"]["arm64"], {"pantheon"})
        block = gpc.build(config)
        self.assertIn("**S:** Pantheon, Tuna", block)


class TestRenderedPolicy(unittest.TestCase):
    def test_every_missing_desktop_is_explicitly_unsupported(self):
        block = gpc.build(fixture())
        self.assertIn("**U:**", block)
        self.assertIn("no release or maintenance commitment", block)

    def test_apple_policy_is_gnome_only_without_a_parity_date(self):
        block = gpc.build(fixture())
        self.assertIn("GNOME is the only Apple Silicon target for a desktop now", block)
        self.assertIn("no parity date or release commitment", block)

    def test_committed_roadmap_block_is_current(self):
        text = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        expected = gpc.replace_block(text, gpc.build(gpc.load_config()))
        self.assertEqual(
            text,
            expected,
            "ROADMAP.md's platform matrix drifted from build-config; run "
            "scripts/gen-platform-coverage.py",
        )

    def test_scheduled_refresh_updates_and_commits_the_matrix(self):
        workflow = (ROOT / ".github/workflows/matrix-status.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("./scripts/gen-platform-coverage.py", workflow)
        self.assertIn("./scripts/gen-platform-coverage.py --check", workflow)
        self.assertIn(
            "git add ROADMAP.md docs/MATRIX-STATUS.md docs/matrix-provenance.json",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
