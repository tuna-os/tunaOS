#!/usr/bin/env python3
"""Tests for the executable custom/packages.yaml contract."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "build_scripts" / "lib" / "custom_packages.py"
_spec = importlib.util.spec_from_file_location("custom_packages", SCRIPT)
custom_packages = importlib.util.module_from_spec(_spec)
sys.modules["custom_packages"] = custom_packages
assert _spec.loader is not None
_spec.loader.exec_module(custom_packages)


class CustomPackageContract(unittest.TestCase):
    def test_accepts_supported_lists(self):
        document = custom_packages.validate_document(
            {
                "dnf": ["htop", "-gnome-tour"],
                "optional": ["fastfetch"],
                "flatpak": ["org.example.App"],
            },
            Path("packages.yaml"),
        )
        self.assertEqual(document["dnf"], ["htop", "-gnome-tour"])
        self.assertEqual(document["flatpak"], ["org.example.App"])

    def test_rejects_unknown_keys(self):
        with self.assertRaisesRegex(ValueError, "unsupported key"):
            custom_packages.validate_document(
                {"fedora": ["htop"]}, Path("packages.yaml")
            )

    def test_rejects_scalar_and_empty_package_values(self):
        for value in ("htop", [""], [1]):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "must be a non-empty-string list"
            ):
                custom_packages.validate_document(
                    {"dnf": value}, Path("packages.yaml")
                )

    def test_loads_yq_json_and_validates_result(self):
        output = {"dnf": ["htop"], "flatpak": ["org.example.App"]}
        completed = subprocess.CompletedProcess(
            args=["yq"], returncode=0, stdout=json.dumps(output), stderr=""
        )
        run = mock.Mock(return_value=completed)
        with mock.patch.dict("os.environ", {"YQ": "/usr/local/bin/yq"}):
            document = custom_packages.load_document(Path("packages.yaml"), runner=run)

        self.assertEqual(document, output)
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/local/bin/yq", "-o=json", ".", "packages.yaml"],
        )

    def test_reports_yq_parse_failure(self):
        completed = subprocess.CompletedProcess(
            args=["yq"], returncode=2, stdout="", stderr="bad indentation"
        )
        run = mock.Mock(return_value=completed)
        with mock.patch.dict("os.environ", {"YQ": "/usr/local/bin/yq"}), self.assertRaisesRegex(
            ValueError, "invalid YAML: bad indentation"
        ):
            custom_packages.load_document(Path("packages.yaml"), runner=run)



if __name__ == "__main__":
    unittest.main()
