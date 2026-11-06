#!/usr/bin/env python3
"""Tests for the executable custom/packages.yaml contract."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
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

    def test_accepts_empty_mapping_and_empty_lists(self):
        document = custom_packages.validate_document({}, Path("packages.yaml"))
        self.assertEqual(document, {})
        document_none = custom_packages.validate_document(None, Path("packages.yaml"))
        self.assertEqual(document_none, {})
        document_empty_keys = custom_packages.validate_document(
            {"dnf": [], "apt": None}, Path("packages.yaml")
        )
        self.assertEqual(document_empty_keys, {"dnf": [], "apt": []})

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

    def test_rejects_non_mapping_root(self):
        with self.assertRaisesRegex(ValueError, "root must be a mapping"):
            custom_packages.validate_document(["htop"], Path("packages.yaml"))

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

    def test_loads_real_yaml_flat_lists(self):
        content = """\
dnf:
  - neovim
  - btop
  - syncthing
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        try:
            document = custom_packages.load_document(path)
            self.assertEqual(document["dnf"], ["neovim", "btop", "syncthing"])
        finally:
            path.unlink(missing_ok=True)

    def test_loads_real_yaml_inline_lists(self):
        content = """\
apt: [neovim, btop, "-gnome-tour"]
flatpak: ["org.example.AppOne", "org.example.AppTwo"]
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        try:
            document = custom_packages.load_document(path)
            self.assertEqual(document["apt"], ["neovim", "btop", "-gnome-tour"])
            self.assertEqual(
                document["flatpak"], ["org.example.AppOne", "org.example.AppTwo"]
            )
        finally:
            path.unlink(missing_ok=True)

    def test_loads_real_yaml_quoted_values_and_comments(self):
        content = """\
# Top-level comment
dnf:
  # Section comment
  - neovim # inline trailing comment
  - "-gnome-tour"
  - "pkg#with#hash"
  - 'single-quoted-pkg'
copr:
  - user/repo
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        try:
            document = custom_packages.load_document(path)
            self.assertEqual(
                document["dnf"],
                ["neovim", "-gnome-tour", "pkg#with#hash", "single-quoted-pkg"],
            )
            self.assertEqual(document["copr"], ["user/repo"])
        finally:
            path.unlink(missing_ok=True)

    def test_loads_real_yaml_empty_or_comments_only(self):
        content = """\
# Only comments
# Nothing here
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        try:
            document = custom_packages.load_document(path)
            self.assertEqual(document, {})
        finally:
            path.unlink(missing_ok=True)

    def test_rejects_malformed_yaml_syntax(self):
        content = "dnf: [unclosed list"
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        try:
            with self.assertRaisesRegex(ValueError, "invalid YAML"):
                custom_packages.load_document(path)
        finally:
            path.unlink(missing_ok=True)

    def test_cli_validate_and_items(self):
        content = """\
dnf:
  - neovim
  - "-gnome-tour"
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        try:
            # Validate valid file
            self.assertEqual(custom_packages.main(["--validate", str(path)]), 0)

            # Query items
            with mock.patch("builtins.print") as mock_print:
                self.assertEqual(
                    custom_packages.main(["--items", "dnf", str(path)]), 0
                )
                printed = [call.args[0] for call in mock_print.call_args_list]
                self.assertEqual(printed, ["neovim", "-gnome-tour"])

            # Query absent key prints nothing
            with mock.patch("builtins.print") as mock_print:
                self.assertEqual(
                    custom_packages.main(["--items", "apt", str(path)]), 0
                )
                self.assertEqual(mock_print.call_count, 0)
        finally:
            path.unlink(missing_ok=True)

    def test_cli_validate_reports_error_on_invalid_file(self):
        content = "fedora:\n  - htop\n"
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(content)
            f.flush()
            path = Path(f.name)
        try:
            with mock.patch("sys.stderr.write"):
                self.assertEqual(custom_packages.main(["--validate", str(path)]), 1)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
