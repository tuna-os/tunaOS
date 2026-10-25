"""Inert candidate tests: temporary trees and a mock make; no mounts or boot."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate", ROOT / "scripts/bootc-candidate.py")
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def touch(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def test_all_upstream_marker_combinations(self):
        for native in (False, True):
            for usr in (False, True):
                for etc in (False, True):
                    with self.subTest(native=native, usr=usr, etc=etc):
                        for name, present in zip((candidate.NATIVE, *candidate.OSTREE), (native, usr, etc)):
                            (self.root / name).unlink(missing_ok=True)
                            if present:
                                self.touch(name)
                        result = candidate.inspect(self.root, "arch")
                        expected = "conflict" if native and (usr or etc) else "composefs-native" if native else "ostree" if usr or etc else "unknown"
                        self.assertEqual(result["backend"], expected)
                        self.assertFalse(result["install_allowed"])
                        self.assertIsNone(result["binary_version"])

    def test_bootupd_and_systemd_boot_do_not_select_native(self):
        self.touch("usr/lib/bootupd/updates/EFI/vendor/grubx64.efi")
        self.touch("usr/lib/systemd/boot/efi/systemd-bootx64.efi")
        self.assertEqual(candidate.inspect(self.root, "arch")["backend"], "unknown")
        self.touch(candidate.NATIVE)
        self.assertEqual(candidate.inspect(self.root, "arch")["backend"], "composefs-native")

    def test_capabilities_fail_independently(self):
        self.touch(candidate.NATIVE)
        cases = [({"firmware": "bios"}, "BIOS"), ({"architecture": "arm64"}, "ARM64"),
                 ({"asahi": True}, "Asahi"), ({"luks": True}, "LUKS"),
                 ({"unified": True}, "Unified"), ({"partial": True}, "Partial"),
                 ({"filesystem": "xfs"}, "fs-verity")]
        for options, reason in cases:
            result = candidate.inspect(self.root, "arch", **options)
            self.assertFalse(result["install_allowed"])
            self.assertTrue(any(reason in message for message in result["blockers"]))

    def test_inherited_families_never_claim_binary_versions(self):
        self.touch(candidate.NATIVE)
        for family in candidate.INHERITED:
            result = candidate.inspect(self.root, family)
            self.assertIsNone(result["binary_version"])
            self.assertTrue(any("Inherited" in message for message in result["blockers"]))

    def test_no_live_root_or_symlink_inspection(self):
        with self.assertRaises(ValueError):
            candidate.inspect(Path("/"), "arch")
        (self.root / "usr").symlink_to("/usr", target_is_directory=True)
        with self.assertRaises(ValueError):
            candidate.inspect(self.root, "arch")

    def test_features_cover_install_and_completion_rebuild(self):
        for family in candidate.FAMILIES:
            command = candidate.build_command(Path("/source"), Path("/stage"), family)
            self.assertIn("bin", command)
            self.assertIn("install-all", command)
            self.assertIn("prefix=/usr", command)
            options = command[-1]
            self.assertIn("install-to-disk", options)
            self.assertIn("pre-6.15", options)
            if family == "arch":
                self.assertIn("--no-default-features", options)
            else:
                self.assertNotIn("--no-default-features", options)
                self.assertIn("selinux", options)

    def test_bootstrap_validates_source_and_scrubs_feature_overrides(self):
        source, output = self.root / "source", self.root / "output"
        source.mkdir()
        output.mkdir()
        with patch.object(candidate.subprocess, "check_output", side_effect=[candidate.COMMIT, ""]), \
             patch.object(candidate.subprocess, "run") as run, \
             patch.dict(candidate.os.environ, {"CARGO_FEATURES": "bad", "MAKEFLAGS": "bad", "MAKEFILES": "bad"}):
            result = candidate.bootstrap(source, output, "fedora")
        self.assertFalse(result["qualified"])
        self.assertNotIn("MAKEFLAGS", run.call_args.kwargs["env"])
        self.assertNotIn("MAKEFILES", run.call_args.kwargs["env"])
        self.assertNotIn("CARGO_FEATURES", run.call_args.kwargs["env"])
        for head, dirty in [("wrong", ""), (candidate.COMMIT, " M Makefile")]:
            with patch.object(candidate.subprocess, "check_output", side_effect=[head, dirty]), \
                 patch.object(candidate.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    candidate.bootstrap(source, output, "arch")
                run.assert_not_called()

    def test_destination_must_be_empty_and_outside_source(self):
        source = self.root / "source"
        source.mkdir()
        for target in (Path("/"), source, source / "out", self.root):
            with self.assertRaises(ValueError):
                candidate.bootstrap(source, target, "arch")

    def test_make_unsafe_paths_are_rejected_before_execution(self):
        source = self.root / "source"
        source.mkdir()
        for name in ("has space", "$(id)", "semi;colon", "quote'", "back`tick"):
            output = self.root / name
            output.mkdir()
            with patch.object(candidate.subprocess, "check_output") as read:
                with self.assertRaises(ValueError):
                    candidate.bootstrap(source, output, "arch")
                read.assert_not_called()

    def test_packaged_family_requires_artifact_evidence(self):
        result = candidate.inspect(self.root, "opensuse")
        self.assertTrue(any("Packaged" in message for message in result["blockers"]))

    def run_arch_branch(self, value, failed_tool=""):
        text = (ROOT / "Containerfile.arch").read_text()
        branch = text.split('RUN if [ "${TUNAOS_BOOTC_CANDIDATE}"', 1)[1].split('\nRUN ', 1)[0]
        branch = 'if [ "${TUNAOS_BOOTC_CANDIDATE}"' + branch.replace('\\\n', ' ')
        # Execute the actual RUN control flow with only inert shell functions.
        # No clone, package operation, filesystem write or build can occur.
        stubs = []
        for tool in ("pacman", "git", "mkdir", "python", "make", "cd"):
            code = 9 if tool == failed_tool else 0
            stubs.append(f'{tool}() {{ printf "%s\\n" "{tool} $*"; return {code}; }}')
        env = dict(candidate.os.environ, TUNAOS_BOOTC_CANDIDATE=value, BOOTC_VERSION="v1.16.10")
        return subprocess.run(["/bin/sh", "-c", "\n".join(stubs) + "\n" + branch],
                              env=env, text=True, capture_output=True)

    def test_arch_opt_in_uses_checked_bootstrap(self):
        result = self.run_arch_branch("1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--branch v1.17.1", result.stdout)
        self.assertIn("bootstrap --source /tmp/bootc --destination /output --family arch", result.stdout)
        self.assertNotIn("make bin", result.stdout)

    def test_arch_default_preserves_production_path(self):
        text = (ROOT / "Containerfile.arch").read_text()
        self.assertIn("ARG TUNAOS_BOOTC_CANDIDATE=0", text)
        result = self.run_arch_branch("0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--branch v1.16.10", result.stdout)
        self.assertIn("make install-all DESTDIR=/output", result.stdout)
        self.assertNotIn("bootstrap", result.stdout)

    def test_arch_invalid_opt_in_and_clone_failure_stop(self):
        result = self.run_arch_branch("yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        result = self.run_arch_branch("1", "git")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("bootstrap", result.stdout)

    def test_cli_returns_failure_even_for_native_marker(self):
        self.touch(candidate.NATIVE)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/bootc-candidate.py"),
                                 "inspect", "--root", str(self.root), "--family", "arch"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["install_allowed"])


if __name__ == "__main__":
    unittest.main()
